"""Markers (W4-MARKER): the event, undo/redo and sets, stretching between them, cue points. No hardware."""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile
from conftest import FakeAudio, FakeClock, clap_signal, make_settings
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from loopstation import events as ev
from loopstation import export as ex
from loopstation import sets
from loopstation.audio.stretch import (
    MarkerStretchError,
    map_back,
    marker_targets,
    rubberband_status,
    stretch_between_markers,
)
from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import LIVE_SETTINGS, MARKER_STRETCH_REFUSALS, Controller, Mode
from loopstation.gui.detail_panel import DetailPanel, LoopTab
from loopstation.gui.export_dialog import ExportDialog
from loopstation.gui.waveform import MARKER_COLOR, WaveformWidget, marker_name
from loopstation.state import MAX_MARKERS, AppState, apply, parse_markers, replay
from loopstation.store import EventStore

SR = 8000
GRID = 2 * SR  # the first take: claps at 0.5 s and 1.0 s -> one bar of 2 s (120 BPM)
BEAT = GRID // 4


def build(tmp_path, clock: FakeClock, claps=None, snapshot_interval: int = 200, **overrides):
    overrides.setdefault("auto_grid", True)
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, snapshot_interval=snapshot_interval, clock=clock)
    audio = FakeAudio(clock)
    audio.clap_times = claps
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def on_grid(tmp_path, clock, claps_pad1=(0.54, 1.06), **overrides):
    """Pad 0 sets the bar (2 s); pad 1 is exactly one bar with claps slightly off the beats."""
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0], **overrides)
    record(controller, clock, 0, 3.0)
    audio.clap_times = list(claps_pad1)
    record(controller, clock, 1, 2.0)
    assert controller.grid_frames() == GRID
    return controller, audio


def events_of(controller: Controller, type_: str) -> list[dict]:
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["type"] == type_]


def reopen(tmp_path, clock, **overrides) -> Controller:
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    return controller


# --- the event and the state ---------------------------------------------------------------------


def state_with(sample: str = "a.wav") -> AppState:
    state = AppState.empty(2)
    return apply(state, ev.Event(1, "t", ev.RECORD_STOP, 0, {"sample": sample}))


def marker_event(seq: int, sample: str, frames, rate: int = SR, pad: int | None = 0) -> ev.Event:
    return ev.Event(seq, "t", ev.MARKER_SET, pad, {"sample": sample, "rate": rate, "frames": frames})


def test_marker_set_is_a_known_event_type_that_parses():
    line = marker_event(2, "a.wav", [10, 20]).to_json()
    assert ev.Event.from_json(line).type == ev.MARKER_SET


def test_the_state_keeps_sorted_unique_positive_markers_per_sample():
    state = apply(state_with(), marker_event(2, "a.wav", [30, 10, 10, 0, -4, 20]))
    assert state.markers == {"a.wav": {"rate": SR, "frames": [10, 20, 30]}}
    assert state.undo_stack[-1]["seq"] == 1  # the marker is no step of the child's undo


def test_an_empty_list_removes_the_markers_and_bad_data_is_ignored():
    state = apply(state_with(), marker_event(2, "a.wav", [10]))
    assert apply(state, marker_event(3, "a.wav", [])).markers == {}
    for bad in (
        marker_event(3, "nobody.wav", [10]),  # no pad ever held it
        ev.Event(3, "t", ev.MARKER_SET, 0, {"sample": "a.wav", "rate": "x", "frames": [10]}),
        ev.Event(3, "t", ev.MARKER_SET, 0, {"sample": "a.wav", "rate": SR, "frames": "no"}),
        ev.Event(3, "t", ev.MARKER_SET, 0, {"rate": SR, "frames": [1]}),
    ):
        assert apply(state, bad).markers == state.markers


def test_markers_are_capped_and_survive_the_snapshot_round_trip():
    state = apply(state_with(), marker_event(2, "a.wav", list(range(1, 40))))
    assert len(state.markers["a.wav"]["frames"]) == MAX_MARKERS
    assert AppState.from_dict(state.to_dict()).markers == state.markers
    assert json.loads(json.dumps(state.to_dict()))["markers"]["a.wav"]["rate"] == SR


def test_old_snapshots_and_logs_without_markers_read_as_before():
    raw = state_with().to_dict()
    del raw["markers"]
    assert AppState.from_dict(raw).markers == {}
    assert replay([ev.Event(1, "t", ev.RECORD_STOP, 0, {"sample": "a.wav"})], 2).markers == {}
    assert parse_markers(None) == {} and parse_markers({"a": {"rate": 0, "frames": [1]}}) == {}


# --- markers and the child's steps: undo, redo, history, restart ---------------------------------


def test_setting_markers_logs_one_event_and_leaves_the_undo_stack_alone(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    before = list(controller.store.state.undo_stack)
    assert controller.add_marker(1, 4320) and controller.add_marker(1, 8480)
    assert controller.markers(1) == [4320, 8480]
    assert not controller.add_marker(1, 4320)  # already there: nothing logged
    assert not controller.set_markers(1, [8480, 4320])
    assert controller.store.state.undo_stack == before
    assert len(events_of(controller, "marker_set")) == 2
    assert controller.remove_marker(1, 4320) and controller.markers(1) == [8480]
    assert not controller.remove_marker(1, 99)
    assert not controller.add_marker(2, 100)  # an empty pad has nothing to mark
    assert not controller.add_marker(1, 0)


def test_markers_survive_a_restart_with_and_without_a_snapshot(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock, snapshot_interval=3)
    controller.add_marker(1, 4320)
    controller.add_marker(1, 8480)
    for _ in range(4):  # push a snapshot behind the markers
        controller.add_marker(0, 100)
        controller.remove_marker(0, 100)
    assert events_of(controller, "snapshot")
    controller.shutdown()
    again = reopen(tmp_path, clock)
    assert again.markers(1) == [4320, 8480] and again.markers(0) == []
    again.shutdown()


def test_markers_follow_their_sample_through_undo_redo_and_the_history(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    first = controller.pad(0).sample
    controller.add_marker(0, 4000)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 0, 2.0)  # a new take on the same pad
    second = controller.pad(0).sample
    assert second != first and controller.markers(0) == []  # markers belong to the take, not the pad
    controller.add_marker(0, 6000)
    controller.undo(0)
    assert controller.pad(0).sample == first and controller.markers(0) == [4000]
    controller.redo(0)
    assert controller.pad(0).sample == second and controller.markers(0) == [6000]
    controller.restore(0, first)
    assert controller.pad(0).sample == first and controller.markers(0) == [4000]
    controller.undo()  # the restore
    assert controller.pad(0).sample == second and controller.markers(0) == [6000]
    controller.undo()  # the second take
    assert controller.pad(0).sample == first and controller.markers(0) == [4000]
    controller.redo()
    assert controller.pad(0).sample == second and controller.markers(0) == [6000]


def test_markers_stay_after_delete_and_undo_brings_the_sample_and_its_markers_back(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.add_marker(0, 5000)
    controller.delete_all()
    assert controller.markers(0) == []
    controller.undo()
    assert controller.markers(0) == [5000]


def test_markers_travel_in_a_set(tmp_path, clock):
    controller, _ = on_grid(tmp_path / "live", clock)
    controller.add_marker(1, 4320)
    controller.add_marker(1, 8480)
    settings = controller.settings
    manifest = sets.write_set(
        tmp_path / "mine.loopset", log_dir=settings.log_dir, samples_dir=settings.samples_dir,
        sample_rate=SR, pad_count=settings.pad_count, clock=clock)
    opened = tmp_path / "opened"
    assert sets.open_set(tmp_path / "mine.loopset", opened) == manifest
    restored = EventStore(opened / "data", settings.pad_count, clock=clock)
    try:
        assert restored.state.markers == controller.store.state.markers
        assert restored.state.markers[controller.pad(1).sample]["frames"] == [4320, 8480]
    finally:
        restored.close()


def test_markers_are_converted_when_the_engine_runs_at_another_rate(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    sample = controller.pad(0).sample
    controller.store.append(ev.MARKER_SET, 0, {"sample": sample, "rate": SR // 2, "frames": [1000, 2000]})
    assert controller.markers(0) == [2000, 4000]


# --- stretching between markers ------------------------------------------------------------------


def test_markers_snap_to_the_nearest_beat_line():
    assert marker_targets([4320, 8480], BEAT, GRID) == [4000, 8000]
    assert marker_targets([8480, 4320, 4320, 0, GRID], BEAT, GRID) == [4000, 8000]  # edges are no markers


def test_stretching_keeps_the_total_length_exactly_and_puts_the_hits_on_the_beats():
    data = clap_signal(GRID, SR, [0.54, 1.06])  # claps at 4320 and 8480
    result, targets = stretch_between_markers(data, [4320, 8480], BEAT)
    assert len(result) == GRID and result.dtype == np.float32 and targets == [4000, 8000]
    for target in targets:
        window = np.abs(result[target - 400 : target + 400])
        assert abs(int(np.argmax(window > 0.2)) - 400) <= 40  # the clap starts on its beat line
    assert np.abs(result[:3000]).max() < 0.05  # silence stays silence


@pytest.mark.parametrize("seed", range(12))
def test_the_length_never_changes_whatever_the_markers(seed):
    rng = np.random.default_rng(seed)
    frames = int(rng.integers(4, 9)) * BEAT
    data = rng.uniform(-0.5, 0.5, frames).astype(np.float32)
    beats = np.arange(1, frames // BEAT)
    chosen = rng.choice(beats, size=int(rng.integers(1, min(5, len(beats)) + 1)), replace=False)
    marks = [int(b * BEAT + rng.integers(-BEAT // 12, BEAT // 12 + 1)) for b in sorted(chosen)]
    result, targets = stretch_between_markers(data, marks, BEAT, max_deviation=0.25)
    assert len(result) == frames and targets == [int(b * BEAT) for b in sorted(chosen)]


def test_markers_on_a_stretched_loop_map_back_onto_the_original():
    anchors = [[4320, 4000], [8480, 8000]]  # the pieces of the original and where they went
    assert map_back([4000, 8000], anchors, GRID) == [4320, 8480]
    assert map_back([6000, 12000], anchors, GRID) == [6400, 12240]  # linear inside a piece
    assert map_back([5], [], GRID) == [5]


def test_given_beat_lines_are_used_as_they_are():
    data = clap_signal(GRID, SR, [0.54, 1.06])
    result, targets = stretch_between_markers(data, [4320, 8480], BEAT, targets=[4000, 8000])
    plain, _ = stretch_between_markers(data, [4320, 8480], BEAT)
    assert targets == [4000, 8000] and np.array_equal(result, plain)
    with pytest.raises(ValueError):
        stretch_between_markers(data, [4320, 4320], BEAT, targets=[4000, 8000])  # one marker, two lines


@pytest.mark.parametrize(("marks", "reason"), [
    ([], "no_markers"),
    ([GRID + 5, -3], "no_markers"),
    ([100], "edge"),  # snaps onto the start of the loop
    ([GRID - 100], "edge"),
    ([4100, 3900], "same_beat"),
    ([6000], "too_far"),  # a marker between two beats is more likely misplaced
])
def test_stretching_refuses_what_it_cannot_do_and_says_why(marks, reason):
    with pytest.raises(MarkerStretchError) as caught:
        stretch_between_markers(np.zeros(GRID, np.float32), marks, BEAT)
    assert caught.value.reason == reason
    assert reason in MARKER_STRETCH_REFUSALS


def test_the_controller_stretches_into_a_new_take_that_undo_takes_back(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    old = controller.pad(1).sample
    controller.add_marker(1, 4320)
    controller.add_marker(1, 8480)
    assert controller.stretch_to_markers(1) is None
    new = controller.pad(1).sample
    assert new != old and old in controller.pad(1).history and new in controller.pad(1).history
    data = controller.sample_audio(new)
    assert len(data) == GRID == len(controller.sample_audio(old))
    assert controller.markers(1) == [4000, 8000]  # the markers now sit on the beats
    stop = events_of(controller, "record_stop")[-1]
    assert stop["data"]["source"] == "markers" and stop["data"]["from"] == old
    assert stop["data"]["frames"] == GRID and events_of(controller, "marker_set")[-1]["data"]["sample"] == new
    # undo and redo bring the old take with its own markers and the stretched one back
    controller.undo(1)
    assert controller.pad(1).sample == old and controller.markers(1) == [4320, 8480]
    controller.redo(1)
    assert controller.pad(1).sample == new and controller.markers(1) == [4000, 8000]
    controller.shutdown()
    again = reopen(tmp_path, clock)  # and all of it is there after a restart
    assert again.pad(1).sample == new and again.markers(1) == [4000, 8000]
    assert len(again.sample_audio(new)) == GRID
    again.shutdown()


def test_the_stretched_file_on_disk_is_the_result(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    controller.add_marker(1, 4320)
    controller.add_marker(1, 8480)
    controller.stretch_to_markers(1)
    path = controller.settings.samples_dir / controller.pad(1).sample
    data, rate = soundfile.read(str(path), dtype="float32")
    assert rate == SR and len(data) == GRID
    window = np.abs(data[3600:4400])
    assert abs(int(np.argmax(window > 0.2)) - 400) <= 40


@pytest.mark.parametrize(("setup", "reason"), [
    ("no_pad", "no_pad"),
    ("none", "no_markers"),
    ("far", "too_far"),
    ("same", "same_beat"),
    ("exact", "already"),
])
def test_a_refused_stretch_changes_nothing(tmp_path, clock, setup, reason):
    controller, _ = on_grid(tmp_path, clock)
    pad = 2 if setup == "no_pad" else 1
    marks = {"far": [6000], "same": [4100, 3900], "exact": [4000, 8000]}.get(setup, [])
    if setup == "far":
        assert controller.set_parent_grid(120, "4/4")  # exact beat lines: only there a far marker is refused
    if marks:
        controller.set_markers(pad, marks)
    seq, sample = controller.store.last_seq, controller.pad(pad).sample
    assert controller.stretch_to_markers(pad) == MARKER_STRETCH_REFUSALS[reason]
    assert controller.store.last_seq == seq and controller.pad(pad).sample == sample


class SpyEngine:
    """A plain resampling stretch (every frame moves exactly in proportion), remembering its input."""

    def __init__(self) -> None:
        self.inputs: list[np.ndarray] = []

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray:
        self.inputs.append(np.array(data, dtype=np.float32, copy=True))
        where = np.linspace(0, len(data) - 1, target)
        return np.interp(where, np.arange(len(data)), data).astype(np.float32)


def is_slice_of(piece: np.ndarray, ref: np.ndarray) -> bool:
    """Is ``piece`` exactly a stretch of consecutive frames of ``ref``?"""
    loud = np.flatnonzero(piece)
    if len(loud) == 0:
        return bool(len(piece) <= len(ref))
    first = int(loud[0])
    for at in np.flatnonzero(ref == piece[first]):
        start = int(at) - first
        if start >= 0 and start + len(piece) <= len(ref) and np.array_equal(
            ref[start : start + len(piece)], piece
        ):
            return True
    return False


def onset(data: np.ndarray, after: int) -> int:
    """First frame from ``after`` on where a clap is loud."""
    return after + int(np.argmax(np.abs(data[after:]) > 0.2))


def spy_on(controller: Controller, monkeypatch) -> SpyEngine:
    spy = SpyEngine()
    monkeypatch.setattr(controller, "_stretch_engine", lambda: spy)
    return spy


def test_each_stretch_starts_from_the_original_take_not_from_the_last_result(tmp_path, clock, monkeypatch):
    # claps at 4320, 8480 and 12360: one marker more each time, stretched after each, as parents do it
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.54, 1.06, 1.545))
    original = controller.pad(1).sample
    source = controller.sample_audio(original)
    spy = spy_on(controller, monkeypatch)
    takes = [original]
    for search, beats in ((3000, [4000]), (6000, [4000, 8000]), (10000, [4000, 8000, 12000])):
        current = controller.sample_audio(controller.pad(1).sample)
        controller.add_marker(1, onset(current, search))
        spy.inputs.clear()
        assert controller.stretch_to_markers(1) is None
        # the engine only ever got pieces of the original take, never of an earlier result
        assert spy.inputs and all(is_slice_of(piece, source) for piece in spy.inputs)
        takes.append(controller.pad(1).sample)
        assert controller.markers(1) == beats  # the same beat lines as before
        result = controller.sample_audio(takes[-1])
        assert len(result) == GRID
        for beat in beats:
            assert abs(onset(result, beat - 400) - beat) <= 40  # every clap on its beat line
        stop = events_of(controller, "record_stop")[-1]["data"]
        assert stop["source"] == "markers" and stop["from"] == takes[-2]
    # every stretched take names the original take as the root of its chain
    assert [e["data"].get("root") for e in events_of(controller, "record_stop")[-3:]] == [original] * 3
    # Zurück and Wiederholen work as before: one step back is the take before, with its markers
    controller.undo(1)
    assert controller.pad(1).sample == takes[2] and len(controller.markers(1)) == 3
    controller.redo(1)
    assert controller.pad(1).sample == takes[3] and controller.markers(1) == [4000, 8000, 12000]
    assert takes[1] in controller.pad(1).history and original in controller.pad(1).history


needs_rubberband = pytest.mark.skipif(
    not rubberband_status()[0], reason=f"Rubber Band not usable here: {rubberband_status()[1]}"
)


@needs_rubberband
def test_a_stretched_take_without_its_chain_is_stretched_itself_as_before(tmp_path, clock, monkeypatch):
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.54, 1.06))
    original = controller.sample_audio(controller.pad(1).sample)
    controller.add_marker(1, 4320)
    assert controller.stretch_to_markers(1) is None
    first = controller.pad(1).sample
    controller.shutdown()
    # a log as written by 1.1.0: the stretched take does not say where it came from
    log_path = controller.store.log_path
    lines = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["type"] == "record_stop" and event["data"].get("source") == "markers":
            event["data"].pop("root", None)
            event["data"].pop("map", None)
            line = json.dumps(event, separators=(",", ":"))
        lines.append(line)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    again = reopen(tmp_path, clock)
    assert again.pad(1).sample == first
    current = again.sample_audio(first)
    spy = spy_on(again, monkeypatch)
    again.add_marker(1, onset(current, 6000))
    assert again.stretch_to_markers(1) is None
    assert spy.inputs and all(is_slice_of(piece, current) for piece in spy.inputs)
    assert not all(is_slice_of(piece, original) for piece in spy.inputs)
    assert again.markers(1) == [4000, 8000]
    again.shutdown()


def test_a_piece_too_far_on_the_original_falls_back_to_stretching_the_take_as_before(
    tmp_path, clock, monkeypatch
):
    # clap 2 at 12440: from the original its last piece would change by 11 %, from the take by under 10 %
    # the limit only holds for the parents' own tempo (a grid from the recording never overrules a marker)
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    assert controller.set_parent_grid(120, "4/4") is True
    audio.clap_times = [0.54, 1.555]
    record(controller, clock, 1, 2.0)
    assert controller.grid_frames() == GRID
    original = controller.sample_audio(controller.pad(1).sample)
    # a plain resampling engine for the first stretch too: the claps then move exactly in proportion, so
    # the margin does not depend on how far a real engine shifts a clap (it differs between platforms)
    spy = spy_on(controller, monkeypatch)
    controller.add_marker(1, 4320)
    assert controller.stretch_to_markers(1) is None
    current = controller.sample_audio(controller.pad(1).sample)
    spy.inputs.clear()
    controller.add_marker(1, onset(current, 10000))
    assert controller.stretch_to_markers(1) is None
    assert spy.inputs and all(is_slice_of(piece, current) for piece in spy.inputs)
    assert not all(is_slice_of(piece, original) for piece in spy.inputs)
    assert controller.markers(1) == [4000, 12000]


def test_after_undo_the_earlier_take_still_stretches_from_the_original(tmp_path, clock, monkeypatch):
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.54, 1.06, 1.545))
    original = controller.pad(1).sample
    source = controller.sample_audio(original)
    spy = spy_on(controller, monkeypatch)
    controller.add_marker(1, 4320)
    controller.stretch_to_markers(1)
    first = controller.pad(1).sample
    controller.add_marker(1, onset(controller.sample_audio(first), 6000))
    controller.stretch_to_markers(1)
    controller.undo(1)  # back to the first stretched take, with its two markers
    assert controller.pad(1).sample == first and len(controller.markers(1)) == 2
    controller.add_marker(1, onset(controller.sample_audio(first), 10000))
    spy.inputs.clear()
    assert controller.stretch_to_markers(1) is None
    assert spy.inputs and all(is_slice_of(piece, source) for piece in spy.inputs)
    stop = events_of(controller, "record_stop")[-1]["data"]
    assert stop["from"] == first and stop["root"] == original
    assert controller.markers(1) == [4000, 8000, 12000]


@needs_rubberband
def test_a_loop_shortened_after_a_stretch_is_stretched_itself(tmp_path, clock, monkeypatch):
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.54, 1.06))
    source = controller.sample_audio(controller.pad(1).sample)
    controller.add_marker(1, 4320)
    controller.stretch_to_markers(1)
    assert controller.trim_loop(1, 100, 100 + GRID) is None  # one bar from frame 100, markers move along
    trimmed = controller.sample_audio(controller.pad(1).sample)
    spy = spy_on(controller, monkeypatch)
    controller.add_marker(1, onset(trimmed, 6000))
    assert controller.stretch_to_markers(1) is None
    assert spy.inputs and all(is_slice_of(piece, trimmed) for piece in spy.inputs)
    assert not all(is_slice_of(piece, source) for piece in spy.inputs)
    assert controller.markers(1) == [4000, 8000]


@needs_rubberband
def test_a_stretch_whose_event_is_archived_is_stretched_itself(tmp_path, clock, monkeypatch):
    settings = make_settings(tmp_path, auto_grid=True)
    store = EventStore(
        settings.log_dir, settings.pad_count, snapshot_interval=2, max_active_events=6, clock=clock
    )
    audio = FakeAudio(clock)
    audio.clap_times = [0.5, 1.0]
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    record(controller, clock, 0, 3.0)
    audio.clap_times = [0.54, 1.06]
    record(controller, clock, 1, 2.0)
    source = controller.sample_audio(controller.pad(1).sample)
    controller.add_marker(1, 4320)
    assert controller.stretch_to_markers(1) is None
    first = controller.pad(1).sample
    for _ in range(4):  # more events of the parents push the stretch into the archive
        controller.add_marker(1, 15000)
        controller.remove_marker(1, 15000)
    assert not any(e.data.get("sample") == first and e.type == ev.RECORD_STOP
                   for e in store.active_events().values())
    current = controller.sample_audio(first)
    spy = spy_on(controller, monkeypatch)
    controller.add_marker(1, onset(current, 6000))
    assert controller.stretch_to_markers(1) is None
    assert spy.inputs and all(is_slice_of(piece, current) for piece in spy.inputs)
    assert not all(is_slice_of(piece, source) for piece in spy.inputs)
    assert controller.markers(1) == [4000, 8000]
    controller.shutdown()


def test_a_free_pad_is_not_stretched_to_beat_lines(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    controller.add_marker(1, 4320)
    controller.set_free(1, True)
    assert controller.stretch_to_markers(1) == MARKER_STRETCH_REFUSALS["free"]


def test_stretching_needs_a_grid_and_waits_for_a_running_recording(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    controller.add_marker(1, 4320)
    controller.press(2)  # recording
    assert controller.stretch_to_markers(1) == MARKER_STRETCH_REFUSALS["recording"]
    controller.press(2)
    free, _ = build(tmp_path / "free", clock, loop_sync=False)
    record(free, clock, 0, 2.0)
    free.add_marker(0, 4000)
    assert free.stretch_to_markers(0) == MARKER_STRETCH_REFUSALS["no_grid"]


# --- cue points in the export --------------------------------------------------------------------


def loop(frames: int = 8000) -> np.ndarray:
    return (0.3 * np.sin(2 * np.pi * 220 * np.arange(frames) / SR)).astype(np.float32)


def test_the_exported_loop_carries_its_markers_as_cue_points_and_stays_the_same_audio(tmp_path):
    plain, marked = tmp_path / "plain.wav", tmp_path / "marked.wav"
    data = loop()
    assert ex.export_loop(plain, data, SR) is None
    assert ex.export_loop(marked, data, SR, markers=[4000, 2000, 99999, 0]) == "cue"
    assert ex.read_cue_points(marked.read_bytes()) == [(2000, "Marker A"), (4000, "Marker B")]
    a, _ = soundfile.read(str(plain), dtype="float32")
    b, rate = soundfile.read(str(marked), dtype="float32")
    assert rate == SR and np.array_equal(a, b)  # not a sample changed
    assert not (tmp_path / "marked.markers.json").exists()
    raw = marked.read_bytes()
    assert int.from_bytes(raw[4:8], "little") == len(raw) - 8  # the RIFF size is still right


@pytest.mark.parametrize("frames", [999, 1000, 1001])
def test_cue_chunks_are_aligned_whatever_the_data_length(tmp_path, frames):
    path = tmp_path / "odd.wav"
    assert ex.export_loop(path, loop(frames), SR, markers=[10]) == "cue"
    assert [f for f, _ in ex.read_cue_points(path.read_bytes())] == [10]
    assert len(path.read_bytes()) % 2 == 0 and soundfile.info(str(path)).frames == frames


def test_no_markers_means_no_cue_and_no_sidecar(tmp_path):
    path = tmp_path / "x.wav"
    assert ex.export_loop(path, loop(), SR, markers=[]) is None
    assert ex.export_loop(path, loop(), SR, markers=[-5, 20000]) is None
    assert ex.read_cue_points(path.read_bytes()) == [] and not (tmp_path / "x.markers.json").exists()


def test_the_export_does_not_fail_when_cue_chunks_cannot_be_written(tmp_path, monkeypatch):
    path = tmp_path / "x.wav"

    def broken(*_args, **_kwargs):
        raise ValueError("cue chunks are not read the same everywhere")

    monkeypatch.setattr(ex, "_add_cue_chunks", broken)
    assert ex.export_loop(path, loop(), SR, markers=[2000, 4000]) == "sidecar"
    assert soundfile.info(str(path)).frames == 8000 and ex.read_cue_points(path.read_bytes()) == []
    side = json.loads((tmp_path / "x.markers.json").read_text(encoding="utf-8"))
    assert side["sample_rate"] == SR and side["file"] == "x.wav"
    assert [(m["label"], m["frame"]) for m in side["markers"]] == [("Marker A", 2000), ("Marker B", 4000)]


def test_the_export_does_not_fail_even_when_neither_cue_nor_sidecar_can_be_written(tmp_path, monkeypatch):
    path = tmp_path / "x.wav"
    monkeypatch.setattr(ex, "_add_cue_chunks", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    monkeypatch.setattr(ex, "sidecar_path", lambda p: (_ for _ in ()).throw(OSError("read-only")))
    assert ex.export_loop(path, loop(), SR, markers=[2000]) is None
    assert soundfile.info(str(path)).frames == 8000


def test_a_cue_chunk_that_does_not_check_out_leaves_the_plain_wav(tmp_path, monkeypatch):
    path = tmp_path / "x.wav"
    monkeypatch.setattr(ex, "cue_chunks", lambda frames: b"cue \x04\x00\x00\x00\x00\x00\x00\x00")  # wrong
    assert ex.export_loop(path, loop(), SR, markers=[2000]) == "sidecar"
    assert soundfile.info(str(path)).frames == 8000
    assert not list(tmp_path.glob("*.tmp"))


def test_an_existing_file_without_a_wave_header_does_not_break_the_export(tmp_path, monkeypatch):
    path = tmp_path / "x.wav"
    real = ex.write_wav

    def junk(p, data, rate, comment=""):
        p.write_bytes(b"not a wav at all")

    monkeypatch.setattr(ex, "write_wav", junk)
    assert ex.export_loop(path, loop(), SR, markers=[2000]) == "sidecar"
    monkeypatch.setattr(ex, "write_wav", real)


def test_the_dialog_writes_cue_points_when_the_switch_is_on(qapp, tmp_path, clock):
    from test_export import session

    controller, _ = session(tmp_path, clock)
    controller.add_marker(1, 4000)
    dialog = ExportDialog(controller, None, export_dir=tmp_path / "out", clock=clock)
    dialog.pad_chips[1].click()
    assert dialog.cue_switch.isChecked()
    dialog.loop_button.click()
    assert [f for f, _ in ex.read_cue_points(dialog.last_path.read_bytes())] == [4000]
    assert "Cue-Punkten" in dialog.loop_message.text()
    dialog.cue_switch.setChecked(False)
    assert controller.settings.export_cue_points is False
    dialog.loop_button.click()
    assert ex.read_cue_points(dialog.last_path.read_bytes()) == []
    assert not dialog.last_path.with_suffix(".markers.json").exists()
    dialog.close()


def test_the_dialog_still_saves_when_the_cue_chunks_fail(qapp, tmp_path, clock, monkeypatch):
    from test_export import session

    controller, _ = session(tmp_path, clock)
    controller.add_marker(1, 4000)
    monkeypatch.setattr(ex, "_add_cue_chunks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    dialog = ExportDialog(controller, None, export_dir=tmp_path / "out", clock=clock)
    dialog.pad_chips[1].click()
    dialog.loop_button.click()
    assert dialog.last_path is not None and dialog.last_path.is_file()
    assert "Begleitdatei" in dialog.loop_message.text()
    dialog.close()


# --- the setting ---------------------------------------------------------------------------------


def test_the_cue_setting_is_on_by_default_live_and_validated():
    assert Settings().export_cue_points is True and "export_cue_points" in LIVE_SETTINGS
    assert parse_settings({"export_cue_points": False}).export_cue_points is False
    with pytest.raises(ConfigError):
        parse_settings({"export_cue_points": "ja"})


# --- the waveform and the page -------------------------------------------------------------------


def orange_pixels(widget: WaveformWidget) -> int:
    image = widget.grab().toImage()
    orange = QColor(MARKER_COLOR)
    return sum(
        1 for x in range(0, image.width(), 2) for y in range(0, image.height(), 2)
        if image.pixelColor(x, y) == orange)


def test_the_waveform_draws_marker_flags_and_names_them_in_order(qapp):
    widget = WaveformWidget()
    widget.resize(900, 220)
    widget.set_loop(loop(), 2000, 4)
    assert orange_pixels(widget) == 0
    widget.set_markers([6000, 2000])
    assert widget.markers == [2000, 6000] and orange_pixels(widget) > 40
    assert [marker_name(i) for i in (0, 1, 25, 26)] == ["Marker A", "Marker B", "Marker Z", "Marker A"]


def test_a_click_puts_the_cursor_or_selects_the_marker_it_hits(qapp):
    widget = WaveformWidget()
    widget.resize(900, 220)
    widget.set_loop(loop(), 2000, 4)
    widget.set_markers([4000])
    seen = []
    widget.selection_changed.connect(lambda: seen.append((widget.cursor_frame, widget.selected_marker)))
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(225, 120))  # a quarter in
    assert widget.cursor_frame == pytest.approx(2000, abs=20) and widget.selected_marker is None
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(452, 120))  # on the flag's line
    assert widget.selected_marker == 0 and widget.cursor_frame is None
    assert len(seen) == 2
    widget.set_markers([1000, 4000])  # the selection moves with its marker
    assert widget.selected_marker == 1
    widget.set_markers([1000])
    assert widget.selected_marker is None
    empty = WaveformWidget()
    empty.resize(900, 220)
    QTest.mouseClick(empty, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert empty.cursor_frame is None


@pytest.fixture
def page(qapp, tmp_path, clock):
    """The tab "Loop" of the detail panel on pad 2."""
    controller, _ = on_grid(tmp_path, clock, snap_markers=False)  # exact clicks; snapping has its own tests
    panel = DetailPanel(controller)
    panel.resize(1200, 400)
    panel.set_open(True)
    panel.show_pad(1)
    yield panel.loop_tab, controller
    panel.close()
    controller.store.close()


def click_frame(loop: LoopTab, frame: int) -> None:
    wave = loop.waveform
    wave.pick(wave._x_of(frame), frame)


def test_the_page_sets_and_deletes_markers_with_the_buttons(page):
    loop, controller = page
    assert not loop.marker_button.isEnabled() and "Erst in die Welle tippen" in loop.marker_button.toolTip()
    assert not loop.stretch_button.isEnabled() and loop.listen_button.isEnabled()
    assert "Marker" in loop.stretch_button.toolTip()  # a locked button says why
    click_frame(loop, 4320)
    assert loop.marker_button.isEnabled() and loop.marker_button.text() == "Marker"
    loop.marker_button.click()
    assert controller.markers(1) == [4320]
    assert loop.waveform.markers == [4320] and loop.stretch_button.isEnabled()
    click_frame(loop, 4320)
    assert loop.marker_button.isEnabled() and loop.marker_button.text() == "Marker löschen"
    loop.marker_button.click()
    assert controller.markers(1) == []
    assert not loop.place_marker() and not loop.delete_marker()  # nothing chosen: nothing happens


def test_the_page_stretches_between_markers_and_says_what_happened(page):
    loop, controller = page
    for frame in (4320, 8480):
        click_frame(loop, frame)
        loop.place_marker()
    old = controller.pad(1).sample
    loop.stretch_button.click()
    assert controller.pad(1).sample != old and controller.markers(1) == [4000, 8000]
    assert loop.waveform.markers == [4000, 8000]
    assert "Zurück" in loop.trim.message.text()
    assert not loop.stretch_markers()  # on the beats already
    assert loop.trim.message.text() == MARKER_STRETCH_REFUSALS["already"]
    controller.undo(1)
    loop.refresh()
    assert loop.waveform.markers == [4320, 8480]


def test_the_page_says_why_a_stretch_does_not_happen(page):
    loop, controller = page
    assert controller.set_parent_grid(120, "4/4")  # the parents' own tempo: exact lines, the limit holds
    click_frame(loop, 6000)
    loop.place_marker()
    assert not loop.stretch_markers() and "zu weit" in loop.trim.message.text()
    loop.show_pad(1)  # showing a pad again forgets the message and the selection
    assert loop.trim.message.isHidden() and loop.waveform.cursor_frame is None
    assert "Strecken" in loop.trim.note.text()  # the line under the wave says what to do again
    loop.listen()
    assert controller.audio.voices  # the loop plays once


def test_markers_exist_only_on_the_parents_page(page):
    loop, _ = page
    from loopstation.gui.main_window import MainWindow

    assert "Marker" in loop.marker_button.text()
    assert not hasattr(MainWindow, "place_marker")
