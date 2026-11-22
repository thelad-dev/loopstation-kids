"""Pad name, gain, start offset and length in bars (core + undo/replay)."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import FakeAudio, FakeClock, make_settings

from loopstation import events as ev
from loopstation.audio.sync import shape_loop
from loopstation.controller import Controller, Mode
from loopstation.state import AppState, apply, replay
from loopstation.store import EventStore

SR = 8000
GRID = 8000  # one bar at 60 BPM / 4/4 with this fixture's first take


@pytest.fixture
def world(tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock, sample_rate=SR)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    yield controller, audio, clock
    store.close()


def record_bar(controller: Controller, clock: FakeClock, pad: int = 0, seconds: float = 1.0) -> None:
    controller.set_mode(Mode.RECORD)
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)
    controller.set_mode(Mode.LOOP)


def test_shape_loop_cuts_pads_and_rotates():
    data = np.arange(2500, dtype=np.float32)
    assert len(shape_loop(data, 1000, bars=1)) == 1000
    assert len(shape_loop(data, 1000, bars=4)) == 4000
    rotated = shape_loop(data, 1000, bars=2, start_frames=100)
    assert rotated[0] == data[100]
    assert len(rotated) == 2000


def test_pad_gain_is_live_undoable_and_replays(world):
    controller, audio, clock = world
    record_bar(controller, clock)
    assert controller.pad_gain(0) == 1.0
    controller.set_pad_gain(0, 0.4)
    assert controller.pad_gain(0) == pytest.approx(0.4)
    assert audio.pad_gains[0] == pytest.approx(0.4)
    controller.undo()
    assert controller.pad_gain(0) == pytest.approx(1.0)
    assert audio.pad_gains[0] == pytest.approx(1.0)
    controller.redo()
    assert controller.pad_gain(0) == pytest.approx(0.4)
    # Replay of the log restores the same gain.
    text = controller.store.log_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    state = replay([ev.Event.from_json(line) for line in lines], controller.pad_count)
    assert state.pads[0].gain == pytest.approx(0.4)


def test_pad_name_is_annotation_not_on_undo(world):
    controller, audio, clock = world
    record_bar(controller, clock)
    stack = list(controller.store.state.undo_stack)
    controller.set_pad_name(0, "Trommel")
    assert controller.pad_name(0) == "Trommel"
    assert controller.store.state.undo_stack == stack  # name is not a Zurück step
    controller.undo()  # undoes the recording, not the name
    assert controller.pad(0).sample is None
    assert controller.pad_name(0) == "Trommel"


def test_pad_start_and_bars_change_what_is_heard(world):
    controller, audio, clock = world
    record_bar(controller, clock, seconds=1.0)  # first take sets the bar
    sample = controller.pad(0).sample
    grid = controller.grid_frames()
    assert grid == GRID
    base = controller.loop_view_audio(sample, 0)
    assert base is not None and len(base) == GRID
    controller.set_pad_bars(0, 2)
    long = controller.loop_view_audio(sample, 0)
    assert long is not None and len(long) == 2 * GRID
    controller.set_pad_start(0, GRID // 4)
    heard = controller.loop_audio(sample, 0)
    assert heard is not None and heard[0] == long[GRID // 4]
    controller.undo()  # start
    controller.undo()  # bars
    assert controller.pad_bars(0) is None
    assert controller.pad_start_frames(0) == 0
    assert len(controller.loop_view_audio(sample, 0)) == len(base)


def test_old_snapshot_without_shape_fields_defaults():
    raw = {
        "pads": {"0": {"sample": "a.wav", "looping": False, "history": ["a.wav"]}},
        "undo_stack": [],
        "redo_stack": [],
        "last_seq": 1,
        "master": None,
        "markers": {},
    }
    state = AppState.from_dict(raw)
    pad = state.pads[0]
    assert pad.gain == 1.0 and pad.name == "" and pad.start_frames == 0 and pad.bars is None
    # Round-trip leaves defaults out of the snapshot (old sets stay compact).
    out = state.to_dict()["pads"]["0"]
    assert "gain" not in out and "name" not in out and "start_frames" not in out and "bars" not in out


def test_pad_gain_event_json_roundtrip():
    event = ev.Event(7, "2026-11-22T12:00:00.000Z", ev.PAD_GAIN, 2, {"gain": 0.25})
    assert ev.Event.from_json(event.to_json()) == event
    assert apply(AppState.empty(4), event).pads[2].gain == pytest.approx(0.25)


def test_normalize_pad_gain_lifts_quiet_take(world):
    from loopstation.audio.dynamics import PAD_NORMALIZE_TARGET, gain_to_db

    controller, _audio, clock = world
    record_bar(controller, clock)
    # FakeAudio sine peaks at 0.25 → normalize toward −3 dBFS.
    gain = controller.normalize_pad_gain(0)
    assert gain is not None and gain > 1.0
    peak = float(np.max(np.abs(controller.loop_view_audio(controller.pad(0).sample, 0))))
    assert peak * gain == pytest.approx(PAD_NORMALIZE_TARGET, rel=0.05)
    assert gain_to_db(gain) > 0


def test_pad_boost_persists_above_unity(world):
    from loopstation.audio.dynamics import db_to_gain

    controller, audio, clock = world
    record_bar(controller, clock)
    boost = db_to_gain(12.0)
    controller.set_pad_gain(0, boost)
    assert controller.pad_gain(0) == pytest.approx(boost)
    assert audio.pad_gains[0] == pytest.approx(boost)
    text = controller.store.log_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    state = replay([ev.Event.from_json(line) for line in lines], controller.pad_count)
    assert state.pads[0].gain == pytest.approx(boost)
