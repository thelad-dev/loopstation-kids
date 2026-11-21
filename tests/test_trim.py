"""Shortening a loop (Erweitert): arithmetic, event, undo/redo, grid cases, replay, set, export."""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import FakeAudio, FakeClock, make_settings

from loopstation import events as ev
from loopstation import export as ex
from loopstation import sets
from loopstation.audio.samples import load_wav
from loopstation.controller import TRIM_REFUSALS, Controller
from loopstation.session import SetSession
from loopstation.state import AppState, apply, replay
from loopstation.store import EventStore
from loopstation.trim import ORDER, SAME, SHORT, plan_trim, shift_markers, trim_audio

SR = 8000
GRID = 2 * SR  # the first take: claps at 0.5 s and 1.0 s -> one bar of 2 s
MIN = round(0.3 * SR)


def build(tmp_path, clock: FakeClock, claps=None, snapshot_interval: int = 200, **overrides):
    overrides.setdefault("auto_grid", True)
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, snapshot_interval=snapshot_interval, clock=clock)
    audio = FakeAudio(clock)
    audio.clap_times = claps
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def reopen(tmp_path, clock: FakeClock, **overrides) -> Controller:
    overrides.setdefault("auto_grid", True)
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    return controller


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def events_of(controller: Controller, type_: str) -> list[dict]:
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["type"] == type_]


def two_pads(tmp_path, clock, **overrides):
    """Pad 0 sets the bar (2 s, from its two claps); pad 1 is a second take of one bar."""
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0], **overrides)
    record(controller, clock, 0, 3.0)
    record(controller, clock, 1, 2.0)
    assert controller.grid_frames() == GRID
    return controller, audio


# --- the arithmetic ------------------------------------------------------------------------------


def plan(length=2 * GRID, start=0, end=GRID, grid=GRID, snap=True, minimum=MIN):
    return plan_trim(length, start, end, grid=grid, min_frames=minimum, snap=snap, rate=SR)


def test_a_snapped_trim_is_a_whole_number_of_bars():
    result = plan(start=1000, end=1000 + GRID + 700)
    assert result.ok and result.snapped and result.frames == GRID and result.bars == 1.0
    assert (result.start, result.end) == (1000, 1000 + GRID)
    assert plan(start=0, end=GRID + GRID // 2 + 10).frames == 2 * GRID  # nearest, half a bar up


def test_half_a_bar_snaps_to_one_bar_padded_with_silence():
    result = plan(length=GRID, start=GRID // 2, end=GRID)
    assert result.ok and result.frames == GRID
    audio = trim_audio(np.ones(GRID, dtype=np.float32), result)
    assert len(audio) == GRID and audio[: GRID // 2].all() and not audio[GRID // 2:].any()


def test_without_the_snap_the_length_is_exact_and_plays_as_whole_bars():
    result = plan(start=500, end=500 + 3000, snap=False)
    assert result.ok and not result.snapped and result.frames == 3000
    assert result.bars == pytest.approx(3000 / GRID) and result.played == GRID


def test_without_a_grid_nothing_snaps():
    result = plan(grid=None, start=0, end=5000)
    assert result.ok and result.frames == 5000 and result.bars is None and result.played is None


def test_limits_start_behind_end_too_short_nothing_changes_and_clamping():
    assert plan(start=900, end=900).problem == ORDER
    assert plan(start=900, end=100).problem == ORDER
    assert plan(start=0, end=MIN - 1, snap=False).problem == SHORT
    assert plan(start=0, end=MIN, snap=False).ok  # exactly the minimum is fine
    assert plan(length=GRID, start=0, end=GRID).problem == SAME
    clamped = plan(length=GRID, start=-50, end=GRID * 9, snap=False)
    assert (clamped.start, clamped.end) == (0, GRID) and clamped.problem == SAME


def test_markers_move_with_the_cut_and_leave_when_outside():
    assert shift_markers([100, 500, 900], SR, SR, 200, 600) == [300]  # 500 -> 300; 100 and 900 are out
    assert shift_markers([200], SR, SR, 200, 600) == []  # on the new start: no marker at frame 0
    assert shift_markers([1000], SR // 2, SR, 0, 5000) == [2000]  # other rate


# --- the event and the state ---------------------------------------------------------------------


def trim_event(seq, pad=0, origin="a.wav", sample="b.wav", start=0, frames=100, rate=SR, **extra):
    return ev.Event(seq, "t", ev.LOOP_TRIM, pad, {
        "sample": sample, "from": origin, "start_frames": start, "end_frames": start + frames,
        "frames": frames, "rate": rate, **extra})


def state_with() -> AppState:
    return apply(AppState.empty(2), ev.Event(1, "t", ev.RECORD_STOP, 0, {"sample": "a.wav"}))


def test_loop_trim_is_a_known_content_event():
    assert ev.LOOP_TRIM in ev.EVENT_TYPES and ev.LOOP_TRIM in ev.CONTENT_TYPES
    assert ev.Event.from_json(trim_event(2).to_json()).type == ev.LOOP_TRIM


def test_the_trimmed_sample_replaces_the_pad_and_the_original_stays_in_the_history():
    state = apply(state_with(), trim_event(2))
    pad = state.pads[0]
    assert pad.sample == "b.wav" and pad.history == ["a.wav", "b.wav"]
    assert [entry["pads"] for entry in state.undo_stack] == [{0: None}, {0: "a.wav"}]


def test_undo_and_redo_take_the_trim_back_and_bring_it_again():
    state = apply(state_with(), trim_event(2))
    undone = apply(state, ev.Event(3, "t", ev.UNDO, None, {"target": 2}))
    assert undone.pads[0].sample == "a.wav" and undone.pads[0].history == ["a.wav", "b.wav"]
    redone = apply(undone, ev.Event(4, "t", ev.REDO, None, {"target": 3}))
    assert redone.pads[0].sample == "b.wav"
    # pad-local, with another pad changing in between
    other = apply(state, ev.Event(3, "t", ev.RECORD_STOP, 1, {"sample": "c.wav"}))
    local = apply(other, ev.Event(4, "t", ev.UNDO, 0, {"target": 2}))
    assert local.pads[0].sample == "a.wav" and local.pads[1].sample == "c.wav"
    again = apply(local, ev.Event(5, "t", ev.REDO, 0, {"target": 4}))
    assert again.pads[0].sample == "b.wav" and again.pads[1].sample == "c.wav"


def test_markers_follow_the_cut_in_the_state():
    marked = apply(state_with(), ev.Event(2, "t", ev.MARKER_SET, 0,
                                          {"sample": "a.wav", "rate": SR, "frames": [100, 500, 900]}))
    state = apply(marked, trim_event(3, start=200, frames=600))
    assert state.markers["b.wav"] == {"rate": SR, "frames": [300]}
    assert state.markers["a.wav"]["frames"] == [100, 500, 900]  # the original keeps its own
    none_left = apply(marked, trim_event(3, start=600, frames=100))
    assert "b.wav" not in none_left.markers


def test_a_master_in_the_event_is_the_new_bar_and_undo_restores_the_old_one():
    base = apply(state_with(), ev.Event(2, "t", ev.MASTER_SET, None, {"frames": 1000, "rate": SR}))
    new = {"frames": 700, "rate": SR, "source": "duration", "pad": 0}
    state = apply(base, trim_event(3, frames=700, master=new))
    assert state.master == new
    undone = apply(state, ev.Event(4, "t", ev.UNDO, None, {"target": 3}))
    assert undone.master == {"frames": 1000, "rate": SR}
    redone = apply(undone, ev.Event(5, "t", ev.REDO, None, {"target": 4}))
    assert redone.master == new


def test_bad_trim_events_are_ignored():
    state = state_with()
    for bad in (
        trim_event(2, origin="other.wav"),  # the pad holds something else
        trim_event(2, frames=0),
        trim_event(2, start=-1),
        ev.Event(2, "t", ev.LOOP_TRIM, None, {"sample": "b.wav", "from": "a.wav", "start_frames": 0,
                                              "frames": 5, "rate": SR}),
        ev.Event(2, "t", ev.LOOP_TRIM, 0, {"from": "a.wav"}),
    ):
        after = apply(state, bad)
        assert after.pads[0].sample == "a.wav" and after.undo_stack == state.undo_stack


def test_a_snapshot_round_trip_keeps_trim_state():
    state = apply(state_with(), trim_event(2))
    assert AppState.from_dict(json.loads(json.dumps(state.to_dict()))).to_dict() == state.to_dict()


# --- the controller on a session ----------------------------------------------------------------


def test_trimming_makes_a_new_file_and_keeps_the_original(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    original = controller.pad(1).sample
    before = (tmp_path / "samples" / original).read_bytes()
    assert controller.trim_loop(1, 1000, 1000 + GRID) is None  # exactly one bar from frame 1000: snapped
    pad = controller.pad(1)
    assert pad.sample != original and pad.history[-2:] == [original, pad.sample]
    assert (tmp_path / "samples" / original).read_bytes() == before
    event = events_of(controller, "loop_trim")[-1]
    assert event["pad"] == 1
    data = event["data"]
    assert data["sample"] == pad.sample and data["from"] == original
    assert (data["start_frames"], data["end_frames"], data["frames"], data["rate"]) == (1000, GRID, GRID, SR)
    new = load_wav(tmp_path / "samples" / pad.sample, SR)
    old = load_wav(tmp_path / "samples" / original, SR)
    assert len(new) == GRID
    assert np.allclose(new[: GRID - 1000], old[1000:])  # the tail is padded silence
    assert not new[GRID - 1000:].any()


def test_a_trim_of_a_playing_loop_stops_it_and_it_can_be_taken_back(tmp_path, clock):
    controller, audio = two_pads(tmp_path, clock)
    original = controller.pad(1).sample
    assert controller.trim_loop(1, 0, GRID // 2, snap=False) is None
    assert controller.pad(1).looping is False
    assert controller.can_undo(1)
    controller.undo(1)
    assert controller.pad(1).sample == original
    controller.redo(1)
    assert controller.pad(1).sample != original
    controller.undo()
    assert controller.pad(1).sample == original


def test_a_loop_that_gives_the_bar_needs_a_decision_to_leave_the_grid(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    assert controller.store.state.master["pad"] == 0
    check = controller.check_trim(0, 0, GRID // 2 + 400, snap=False)
    assert check.decide and not check.ok and check.refusal == TRIM_REFUSALS["founder"]
    assert controller.trim_loop(0, 0, GRID // 2 + 400, snap=False) == TRIM_REFUSALS["founder"]
    assert controller.grid_frames() == GRID and events_of(controller, "loop_trim") == []
    # snapped: no question, the bar stays
    assert not controller.check_trim(0, 0, GRID // 2 + 400, snap=True).decide
    # other pads never ask
    assert not controller.check_trim(1, 0, GRID // 2 + 400, snap=False).decide


def test_setting_the_bar_anew_logs_it_in_the_trim_and_undo_brings_the_old_bar_back(tmp_path, clock):
    controller, audio = two_pads(tmp_path, clock)
    length = round(1.5 * SR)  # 1.5 s: 160 BPM, inside the tempo window
    other = controller.pad(1).sample
    assert controller.trim_loop(0, 0, length, snap=False, regrid=True) is None
    assert controller.grid_frames() == length and audio.grid == length
    assert controller.store.state.master["pad"] == 0 and controller.store.state.master["source"] == "duration"
    assert controller.pad(1).sample == other  # the other loop keeps its file and is fitted to the bar
    assert len(controller.loop_audio(other, 1)) % length == 0
    controller.undo()
    assert controller.grid_frames() == GRID and audio.grid == GRID
    controller.redo()
    assert controller.grid_frames() == length


def test_a_new_bar_outside_the_tempo_window_is_refused(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    result = controller.trim_loop(0, 0, round(0.4 * SR), snap=False, regrid=True)  # 600 BPM
    assert result == TRIM_REFUSALS["grid"] and events_of(controller, "loop_trim") == []


def test_multiples_of_the_bar_stay_aligned_and_other_pads_keep_their_period(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    record(controller, clock, 1, 4.0)  # two bars
    assert controller.pad(1).sample and len(controller.sample_audio(controller.pad(1).sample)) == 2 * GRID
    one_bar = controller.sample_audio(controller.pad(0).sample)
    assert controller.trim_loop(1, 0, GRID, snap=False) is None  # exactly one bar: no question
    assert len(controller.sample_audio(controller.pad(1).sample)) == GRID
    assert controller.grid_frames() == GRID
    assert np.array_equal(controller.sample_audio(controller.pad(0).sample), one_bar)


def test_half_a_bar_snaps_to_the_bar_or_plays_padded(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    half = controller.pad(1).sample
    assert controller.trim_loop(1, 0, GRID // 2) == TRIM_REFUSALS[SAME]  # snapped: the bar is all there is
    assert controller.trim_loop(1, GRID // 2, GRID) is None  # the first half off: one bar, silence after
    assert len(controller.sample_audio(controller.pad(1).sample)) == GRID
    controller.undo(1)
    assert controller.pad(1).sample == half
    assert controller.trim_loop(1, 0, GRID // 2, snap=False) is None  # not snapped: half a bar...
    sample = controller.pad(1).sample
    assert len(controller.sample_audio(sample)) == GRID // 2
    assert len(controller.loop_audio(sample, 1)) == GRID  # ...which plays as one bar, the period is the same


def test_the_parents_tempo_gives_the_bar_to_nobody(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    assert controller.set_parent_grid(120, "4/4")
    assert not controller.check_trim(0, 0, GRID // 2 + 400, snap=False).decide


def test_a_free_pad_keeps_its_own_length_without_a_question(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.set_free(1, True)
    assert controller.trim_loop(1, 0, 3000, snap=False) is None
    assert len(controller.sample_audio(controller.pad(1).sample)) == 3000


def test_refusals(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    assert controller.trim_loop(5, 0, 100) == TRIM_REFUSALS["no_pad"]
    assert controller.trim_loop(1, 900, 900) == TRIM_REFUSALS[ORDER]
    assert controller.trim_loop(1, 0, MIN - 1, snap=False) == TRIM_REFUSALS[SHORT]
    assert controller.trim_loop(1, 0, GRID) == TRIM_REFUSALS[SAME]
    assert controller.trim_preview(1, 900, 900) == TRIM_REFUSALS[ORDER]
    assert events_of(controller, "loop_trim") == []
    controller.press(5)  # a recording runs
    assert controller.trim_loop(1, 0, 3000, snap=False) == TRIM_REFUSALS["recording"]


def test_the_minimum_length_is_the_seam_fade_when_that_is_longer(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    assert controller._grid_limits(SR)["min_frames"] == round(0.3 * SR)


def test_the_preview_plays_the_short_version_once_without_changing_anything(tmp_path, clock):
    controller, audio = two_pads(tmp_path, clock)
    sample = controller.pad(1).sample
    assert controller.trim_preview(1, 0, 3000, snap=False) is None
    assert len(next(iter(audio.voices.values()))[0]) == 3000
    assert controller.pad(1).sample == sample and events_of(controller, "loop_trim") == []


def test_markers_move_with_the_trim_and_the_grid_origin_is_passed_on(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.add_marker(1, 5000)
    controller.add_marker(1, 12000)
    assert controller.trim_loop(1, 4000, 4000 + GRID, snap=True) is None
    assert controller.markers(1) == [1000, 8000]
    controller.undo(1)
    assert controller.markers(1) == [5000, 12000]


# --- replay, snapshot, archive, set, export -----------------------------------------------------


def test_a_trim_survives_a_restart_with_and_without_a_snapshot(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.add_marker(1, 5000)
    controller.trim_loop(1, 4000, 4000 + GRID)
    controller.trim_loop(0, 0, GRID // 2 + 400, snap=False, regrid=True)
    state = controller.store.state.to_dict()
    controller.store.close()
    again = reopen(tmp_path, clock)
    try:
        assert again.store.state.to_dict() == state
        assert again.grid_frames() == controller.grid_frames()
        assert again.markers(1) == [1000]
    finally:
        again.store.close()


def test_a_trim_works_through_snapshots_and_the_archive(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.store.snapshot_interval = 3
    controller.trim_loop(1, 4000, 4000 + GRID)
    for _ in range(8):
        controller.set_free(1, True)
        controller.set_free(1, False)
    assert events_of(controller, "snapshot")
    state = controller.store.state.to_dict()
    controller.store.close()
    again = reopen(tmp_path, clock)
    try:
        assert again.store.state.to_dict() == state
        # undo steps back through the trim even though its log line is long past
        while again.can_undo(1) and again.pad(1).sample == controller.pad(1).sample:
            again.undo(1)
        assert again.pad(1).sample != controller.pad(1).sample
    finally:
        again.store.close()


def test_replay_of_the_log_gives_the_same_state(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.trim_loop(1, 4000, 4000 + GRID)
    controller.undo(1)
    controller.redo(1)
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    folded = replay([ev.Event.from_json(line) for line in lines], controller.pad_count)
    assert folded.to_dict()["pads"] == controller.store.state.to_dict()["pads"]
    assert folded.undo_stack == controller.store.state.undo_stack


def test_a_trim_travels_in_a_set_and_the_original_with_it(tmp_path, clock):
    controller, _ = two_pads(tmp_path / "live", clock)
    original = controller.pad(1).sample
    controller.trim_loop(1, 4000, 4000 + GRID)
    trimmed = controller.pad(1).sample
    settings = controller.settings
    session = SetSession(controller, None, clock=clock, sets_folder=tmp_path / "sets")
    assert session.unsaved()
    session.save(tmp_path / "mine.loopset")
    assert not session.unsaved()
    opened = tmp_path / "opened"
    sets.open_set(tmp_path / "mine.loopset", opened)
    restored = EventStore(opened / "data", settings.pad_count, clock=clock)
    try:
        assert restored.state.pads[1].sample == trimmed
        assert {original, trimmed} <= set(restored.state.pads[1].history)
        assert (opened / "samples" / original).is_file() and (opened / "samples" / trimmed).is_file()
    finally:
        restored.close()
    controller.undo(1)  # undoing a trim is unsaved content again
    assert session.unsaved()


def test_the_exports_use_the_trimmed_loop(tmp_path, clock):
    controller, _ = two_pads(tmp_path, clock)
    controller.trim_loop(1, 0, 3000, snap=False)
    sample = controller.pad(1).sample
    spec = ex.build_spec(controller, bars=2, all_pads=True)
    one = next(entry for entry in spec.loops if entry.pad == 1)
    assert len(one.data) == GRID  # the trimmed 3000 frames play as one bar, here padded
    assert np.array_equal(one.data[:3000], controller.sample_audio(sample))
    assert not one.data[3000:].any()
    from loopstation.gui.export_dialog import save_loop
    path, _text, error = save_loop(controller, 1, tmp_path / "out", "stamp")
    assert not error and path is not None
    assert len(load_wav(path, SR)) == 3000


# --- the page: handles, readout, preview, apply, discard, the question --------------------------


@pytest.fixture
def page(qapp, tmp_path, clock):
    from loopstation.gui.advanced_page import AdvancedPage

    controller, audio = two_pads(tmp_path, clock)
    dialog = AdvancedPage(controller, export_dir=tmp_path / "out")
    dialog.choose_pad(1)
    dialog.resize(1200, 1100)
    yield dialog, controller, audio
    dialog.close()
    controller.store.close()


def drag(dialog, handle: str, frame: int) -> None:
    """Press on a handle, move it to ``frame``, let go (the mouse events the widget gets)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    wave = dialog.waveform
    start, end = wave.trim_range
    x0 = wave._x_of(start if handle == "start" else end)
    x1 = wave._x_of(frame)
    point = QPointF
    for kind, x, button, buttons in (
        (QEvent.Type.MouseButtonPress, x0, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, x1, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, x1, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(kind, point(x, 60), point(x, 60), button, buttons, Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress: wave.mousePressEvent, QEvent.Type.MouseMove: wave.mouseMoveEvent,
         QEvent.Type.MouseButtonRelease: wave.mouseReleaseEvent}[kind](event)


def test_the_handles_start_at_the_ends_and_move_by_dragging(page):
    dialog, _controller, _audio = page
    wave = dialog.waveform
    assert wave.trim_range == (0, GRID) and not wave.trimmed and not dialog.trim_card.apply_button.isEnabled()
    assert wave.handle_at(wave._x_of(0)) == "start" and wave.handle_at(wave._x_of(GRID)) == "end"
    assert wave.handle_at(wave._x_of(GRID // 2)) is None
    drag(dialog, "start", 3000)
    assert wave.trim_range[0] in range(2990, 3011) and wave.trimmed
    drag(dialog, "end", 9000)
    assert wave.trim_range[1] in range(8990, 9011)
    drag(dialog, "start", GRID)  # cannot pass the other handle
    assert wave.trim_range[0] < wave.trim_range[1]
    wave.reset_trim()
    assert wave.trim_range == (0, GRID) and not wave.trimmed


def test_the_card_reads_the_new_length_in_seconds_and_bars(page):
    dialog, _controller, _audio = page
    card = dialog.trim_card
    assert "2,00 s" in card.readout.text() and "1 Takt" in card.readout.text()
    dialog.waveform.set_trim_range(0, 3000)
    assert not card.snap_switch.isChecked() or "1 Takt" in card.readout.text()
    card.snap_switch.setChecked(False)
    assert "0,38 s" in card.readout.text() and "0,19 Takte" in card.readout.text()
    assert "Stille" in card.note.text()
    dialog.waveform.set_trim_range(0, 100)
    assert card.readout.text().startswith("Neu: 0,01 s") and not card.apply_button.isEnabled()
    assert "zu kurz" in card.note.text()


def test_listening_plays_the_short_version_and_changes_nothing(page):
    dialog, controller, audio = page
    sample = controller.pad(1).sample
    dialog.trim_card.snap_switch.setChecked(False)
    dialog.waveform.set_trim_range(1000, 5000)
    dialog.trim_card.listen()
    assert len(next(iter(audio.voices.values()))[0]) == 4000
    assert controller.pad(1).sample == sample and events_of(controller, "loop_trim") == []


def test_apply_shortens_the_loop_and_the_page_follows(page):
    dialog, controller, _audio = page
    original = controller.pad(1).sample
    dialog.trim_card.snap_switch.setChecked(False)
    dialog.waveform.set_trim_range(1000, 5000)
    assert dialog.trim_card.apply_button.isEnabled() and dialog.trim_card.discard_button.isEnabled()
    assert dialog.trim_card.apply() is True
    sample = controller.pad(1).sample
    assert sample != original and len(controller.sample_audio(sample)) == 4000
    assert "Zurück" in dialog.trim_card.message.text()
    assert not dialog.waveform.trimmed  # the handles are on the ends of the new loop
    assert dialog.waveform.trim_range == (0, dialog.waveform.loop_frames)
    controller.undo(1)
    assert controller.pad(1).sample == original


def test_discard_puts_the_handles_back_and_changes_nothing(page):
    dialog, controller, _audio = page
    dialog.waveform.set_trim_range(1000, 5000)
    dialog.trim_card.discard()
    assert not dialog.waveform.trimmed and events_of(controller, "loop_trim") == []
    assert not dialog.trim_card.discard_button.isEnabled()


def test_the_loop_that_gives_the_bar_asks_before_it_leaves_the_grid(page):
    from loopstation.gui.trim_card import REGRID, SNAP

    dialog, controller, _audio = page
    dialog.choose_pad(0)
    card = dialog.trim_card
    card.snap_switch.setChecked(False)
    dialog.waveform.set_trim_range(0, round(1.5 * SR))
    assert "Takt vor" in card.note.text() and card.apply_button.isEnabled()
    asked = []
    card.ask_grid = lambda check: asked.append(check) or None
    assert card.apply() is False and len(asked) == 1 and events_of(controller, "loop_trim") == []
    assert controller.grid_frames() == GRID  # cancelled: nothing changed
    card.ask_grid = lambda check: SNAP
    assert card.apply() is False  # snapping 1.5 s gives the bar: nothing to cut
    assert controller.grid_frames() == GRID and events_of(controller, "loop_trim") == []
    card.ask_grid = lambda check: REGRID
    assert card.apply() is True
    assert controller.grid_frames() == round(1.5 * SR)


def test_the_choice_dialog_has_its_three_buttons(qapp, page):
    from loopstation.gui.trim_card import REGRID, SNAP, GridChoiceDialog

    dialog, controller, _audio = page
    check = controller.check_trim(0, 0, round(1.5 * SR), snap=False)
    choice = GridChoiceDialog(check)
    choice.regrid_button.click()
    assert choice.choice == REGRID
    other = GridChoiceDialog(check)
    other.snap_button.click()
    assert other.choice == SNAP
    cancelled = GridChoiceDialog(check)
    cancelled.cancel_button.click()
    assert cancelled.choice is None


def test_the_changes_list_names_the_trim(tmp_path, clock):
    from loopstation.gui.changes_page import describe_change

    controller, _ = two_pads(tmp_path, clock)
    controller.trim_loop(1, 0, 3000, snap=False)
    assert describe_change(controller.changes()[0]) == "Pad 2 · Loop gekürzt (0,4 s)"
