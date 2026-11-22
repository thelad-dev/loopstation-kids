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
    assert controller.parent_undo(0)
    assert controller.pad_gain(0) == pytest.approx(1.0)
    assert audio.pad_gains[0] == pytest.approx(1.0)
    assert controller.parent_redo(0)
    assert controller.pad_gain(0) == pytest.approx(0.4)
    # Replay of the log restores the same gain.
    text = controller.store.log_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    state = replay([ev.Event.from_json(line) for line in lines], controller.pad_count)
    assert state.pads[0].gain == pytest.approx(0.4)


def test_pad_name_is_on_the_parents_track_not_the_childs(world):
    controller, audio, clock = world
    record_bar(controller, clock)
    stack = list(controller.store.state.undo_stack)
    controller.set_pad_name(0, "Trommel")
    assert controller.pad_name(0) == "Trommel"
    assert controller.store.state.undo_stack == stack
    controller.undo()  # undoes the recording, not the name
    assert controller.pad(0).sample is None
    assert controller.pad_name(0) == "Trommel"
    assert controller.parent_undo(0)
    assert controller.pad_name(0) == ""


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
    assert controller.parent_undo(0)  # start
    assert controller.parent_undo(0)  # bars
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


def _replayed(controller):
    text = controller.store.log_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    return replay([ev.Event.from_json(line) for line in lines], controller.pad_count)


def test_child_undo_takes_the_recording_back_after_many_parent_changes(world):
    controller, _audio, clock = world
    record_bar(controller, clock)
    for gain in (0.9, 0.8, 0.7, 0.6, 0.5):
        controller.set_pad_gain(0, gain)
    controller.set_pad_start(0, 100)
    controller.set_pad_bars(0, 2)
    assert controller.undo_depth() == 1  # only the recording
    controller.undo()
    assert controller.pad(0).sample is None
    assert controller.pad_gain(0) == pytest.approx(0.5)  # the parents' settings stay
    assert controller.pad_bars(0) == 2


def test_parent_undo_leaves_recordings_alone(world):
    controller, _audio, clock = world
    record_bar(controller, clock)
    sample = controller.pad(0).sample
    undo_stack = list(controller.store.state.undo_stack)
    controller.set_pad_gain(0, 0.3)
    controller.set_pad_gain(0, 0.6)
    assert controller.parent_undo(0)
    assert controller.pad_gain(0) == pytest.approx(0.3)
    assert controller.parent_undo(0)
    assert controller.pad_gain(0) == pytest.approx(1.0)
    assert not controller.parent_undo(0) and not controller.can_parent_undo(0)
    assert controller.pad(0).sample == sample
    assert controller.store.state.undo_stack == undo_stack
    assert controller.parent_redo(0)
    assert controller.pad_gain(0) == pytest.approx(0.3)


def test_parent_track_is_per_pad_and_a_new_change_ends_its_redo(world):
    controller, _audio, clock = world
    record_bar(controller, clock, pad=0)
    record_bar(controller, clock, pad=1)
    controller.set_pad_gain(0, 0.4)
    controller.set_pad_gain(1, 0.7)
    assert controller.parent_undo(0)
    assert controller.pad_gain(0) == pytest.approx(1.0) and controller.pad_gain(1) == pytest.approx(0.7)
    assert controller.can_parent_redo(0) and not controller.can_parent_redo(1)
    controller.set_pad_gain(0, 0.2)
    assert not controller.can_parent_redo(0)


def test_child_changes_do_not_end_the_parents_redo(world):
    controller, _audio, clock = world
    record_bar(controller, clock, pad=0)
    controller.set_pad_gain(0, 0.4)
    controller.parent_undo(0)
    record_bar(controller, clock, pad=1)
    assert controller.can_parent_redo(0)
    assert controller.parent_redo(0)
    assert controller.pad_gain(0) == pytest.approx(0.4)


def test_parent_events_are_marked_and_replay_matches(world):
    controller, _audio, clock = world
    record_bar(controller, clock)
    controller.set_pad_name(0, "Bass")
    controller.set_pad_gain(0, 0.5)
    controller.set_pad_start(0, 200)
    controller.set_pad_bars(0, 2)
    controller.undo()  # child undo in between
    controller.redo()
    controller.parent_undo(0)  # bars
    controller.parent_undo(0)  # start
    controller.parent_redo(0)  # start again
    events = [ev.Event.from_json(line) for line in
              controller.store.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    parent_types = {ev.PAD_NAME, ev.PAD_GAIN, ev.PAD_START, ev.PAD_BARS, ev.PARENT_UNDO, ev.PARENT_REDO}
    marked = [e for e in events if e.type in parent_types]
    assert marked and all(e.data.get("source") == ev.PARENT_SOURCE for e in marked)
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    replayed = _replayed(controller)
    live = controller.store.state
    for pad_id, pad in live.pads.items():
        again = replayed.pads[pad_id]
        assert (again.name, again.gain, again.start_frames, again.bars, again.sample) == (
            pad.name, pad.gain, pad.start_frames, pad.bars, pad.sample)
    assert replayed.undo_stack == live.undo_stack
    assert replayed.parent_undo_stack == live.parent_undo_stack
    assert replayed.parent_redo_stack == live.parent_redo_stack
    assert AppState.from_dict(live.to_dict()).parent_undo_stack == live.parent_undo_stack


def test_parent_undo_of_start_restores_exactly_the_state_before(world):
    controller, audio, clock = world
    record_bar(controller, clock)
    controller.set_pad_start(0, 500)
    assert controller.pad_start_frames(0) == 500
    assert controller.parent_undo(0)
    assert controller.pad_start_frames(0) == 0
    assert controller.parent_redo(0)
    assert controller.pad_start_frames(0) == 500
