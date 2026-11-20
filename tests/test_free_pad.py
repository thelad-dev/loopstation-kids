"""Free pad mode: a long hold switches it, the sample keeps its own length (plan 2.3 and 5.2)."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
import soundfile
from conftest import (
    FakeAudio,
    FakeClock,
    FakeMessage,
    FakeMidiPorts,
    FakeSoundDevice,
    fake_message,
    make_settings,
)
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_controller import build, record
from test_state import Log

from loopstation import events as ev
from loopstation import export as ex
from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import FREE_HOLD_SECONDS, LIVE_SETTINGS, Controller, Mode
from loopstation.midi.launchpad import LaunchpadController
from loopstation.state import AppState, apply, master_source
from loopstation.store import EventStore

SR = 8000


def events(controller: Controller) -> list[dict]:
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def wav_frames(tmp_path, controller: Controller, pad: int) -> int:
    return soundfile.info(str(tmp_path / "samples" / controller.pad(pad).sample)).frames


def hold(
    controller: Controller, clock: FakeClock, pad: int, seconds: float = FREE_HOLD_SECONDS + 0.1
) -> bool:
    """Press a pad, keep it down for ``seconds`` (ticking like the GUI), let go; True if that was a tap."""
    controller.press_down(pad)
    for _ in range(round(seconds / 0.03)):
        clock.advance(0.03)
        controller.tick()
    return controller.press_up(pad)


# ----------------------------------------------------------------- state


def test_pad_free_event_sets_the_flag_and_undo_and_redo_take_it_back():
    log = Log()
    log.record(3, "a.wav")
    log.add(ev.PAD_FREE, 3, free=True)
    assert log.state.pads[3].free and log.state.pads[3].sample == "a.wav"
    log.add(ev.UNDO, 3, target=log.state.undo_stack[-1]["seq"])
    assert not log.state.pads[3].free and log.state.pads[3].sample == "a.wav"
    log.add(ev.REDO, 3, target=log.state.redo_stack[-1]["seq"])
    assert log.state.pads[3].free
    # Global undo takes the latest change, which is the switch.
    log.undo()
    assert not log.state.pads[3].free and log.state.pads[3].sample == "a.wav"


def test_switching_to_the_state_a_pad_is_in_changes_nothing():
    log = Log()
    log.add(ev.PAD_FREE, 2, free=False)
    assert log.state.undo_stack == []
    log.add(ev.PAD_FREE, 2, free=True)
    log.add(ev.PAD_FREE, 2, free=True)
    assert len(log.state.undo_stack) == 1


def test_a_pad_that_is_undone_per_pad_leaves_other_pads_alone():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.PAD_FREE, 0, free=True)
    log.record(1, "b.wav")
    log.add(ev.UNDO, 0, target=log.state.undo_stack[1]["seq"])  # the switch of pad 0, not the newer take
    assert not log.state.pads[0].free and log.state.pads[1].sample == "b.wav"


def test_free_pad_stops_looping_when_switched():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.LOOP_ON, 0)
    log.add(ev.PAD_FREE, 0, free=True)
    assert not log.state.pads[0].looping
    log.add(ev.LOOP_ON, 0)
    log.add(ev.UNDO, 0, target=log.state.undo_stack[-1]["seq"])
    assert not log.state.pads[0].looping


def test_emptying_a_pad_ends_its_free_mode_and_undo_brings_both_back():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.PAD_FREE, 0, free=True)
    log.add(ev.DELETE_PAD, 0)
    assert log.state.pads[0].sample is None and not log.state.pads[0].free
    log.undo()
    assert log.state.pads[0].sample == "a.wav" and log.state.pads[0].free


def test_delete_all_and_its_undo_keep_the_free_pads():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.PAD_FREE, 1, free=True)
    log.add(ev.PAD_FREE, 4, free=True)  # an empty free pad
    log.add(ev.DELETE_ALL)
    assert not any(pad.free for pad in log.state.pads.values())
    log.undo()
    assert [p for p, pad in log.state.pads.items() if pad.free] == [1, 4]
    assert log.state.pads[0].sample == "a.wav" and not log.state.pads[0].free


def test_per_pad_undo_of_delete_all_gives_back_just_that_pads_mode():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.PAD_FREE, 1, free=True)
    log.add(ev.DELETE_ALL)
    log.add(ev.UNDO, 1, target=log.state.undo_stack[-1]["seq"])
    assert log.state.pads[1].free and log.state.pads[1].sample == "b.wav"
    assert log.state.pads[0].sample is None
    log.undo()  # what is left of the entry: pad 0
    assert log.state.pads[0].sample == "a.wav" and not log.state.pads[0].free
    assert log.state.pads[1].free


def test_snapshot_keeps_the_free_flag_and_undo_entries_survive_it():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.PAD_FREE, 0, free=True)
    raw = json.loads(json.dumps(log.state.to_dict()))
    assert raw["pads"]["0"]["free"] is True
    assert "free" not in raw["pads"]["1"]  # sessions without free pads look as before
    again = AppState.from_dict(raw)
    assert again.to_dict() == log.state.to_dict()
    log.snapshot()
    log.undo()
    assert not log.state.pads[0].free and log.state.pads[0].sample == "a.wav"


def test_snapshots_and_logs_from_before_the_free_mode_read_as_not_free():
    raw = {"pads": {"0": {"sample": "a.wav", "looping": False, "history": ["a.wav"]}},
           "undo_stack": [{"seq": 2, "pads": {"0": None}}], "last_seq": 2, "master": None}
    state = AppState.from_dict(raw)
    assert state.pads[0].free is False
    state = apply(state, ev.Event(3, "2026-11-05T12:00:00.000Z", ev.UNDO, None, {"target": 2}))
    assert state.pads[0].sample is None


def test_pad_free_is_an_event_with_a_pad_and_a_flag():
    line = ev.Event(5, "2026-11-05T12:00:00.000Z", ev.PAD_FREE, 6, {"free": True}).to_json()
    assert ev.Event.from_json(line).type == "pad_free"
    assert ev.PAD_FREE in ev.CONTENT_TYPES


# ------------------------------------------------------------ the hold


def test_holding_a_pad_switches_the_free_mode_and_letting_go_does_nothing_more(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    controller.press_down(5)
    assert controller.hold_progress(5) == 0.0
    clock.advance(FREE_HOLD_SECONDS / 2)
    controller.tick()
    assert controller.hold_progress(5) == pytest.approx(0.5)
    assert not controller.is_free(5)
    clock.advance(FREE_HOLD_SECONDS / 2)
    controller.tick()
    assert controller.is_free(5) and controller.hold_progress(5) is None
    assert events(controller)[-1] == {**events(controller)[-1], "type": "pad_free", "pad": 5,
                                      "data": {"free": True}}
    assert controller.press_up(5) is False  # not a tap: no recording starts
    assert controller.recording_pad is None and ("start_recording",) not in audio.calls


def test_a_tap_is_still_a_press(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    controller.press_down(0)
    clock.advance(0.2)
    controller.tick()
    assert controller.press_up(0) is True
    assert not controller.is_free(0)
    # A release without a press before it (a Launchpad key down before it connected) is no tap.
    assert controller.press_up(7) is False


def test_holding_again_switches_back_and_a_hold_works_on_a_pad_with_a_sample(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 2, 1.0)
    assert hold(controller, clock, 2) is False and controller.is_free(2)
    assert controller.pad(2).sample is not None
    assert hold(controller, clock, 2) is False and not controller.is_free(2)
    assert [e["type"] for e in events(controller)].count("pad_free") == 2


def test_the_switch_can_be_undone_and_redone_per_pad_and_with_the_big_button(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    hold(controller, clock, 4)
    assert controller.is_free(4) and controller.can_undo(4) and controller.last_change_pad() == 4
    controller.undo(4)  # the badge on the pad
    assert not controller.is_free(4)
    controller.redo(4)
    assert controller.is_free(4)
    controller.undo()  # the big "Zurück"
    assert not controller.is_free(4)
    assert [e["type"] for e in events(controller)][-3:] == ["undo", "redo", "undo"]


def test_switching_a_playing_pad_stops_it_because_it_plays_differently_now(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    assert controller.pad(0).looping and 0 in audio.playing_pads()
    hold(controller, clock, 0)
    assert controller.is_free(0) and not controller.pad(0).looping and 0 not in audio.playing_pads()
    controller.press(0)
    assert audio.play_modes[0] == (True, False)
    controller.undo(0)  # back to a grid pad: the free loop stops again
    assert 0 not in audio.playing_pads() and not controller.pad(0).looping


@pytest.mark.parametrize("mode", [Mode.DELETE, Mode.HISTORY])
def test_the_hold_only_counts_where_a_press_would_not_mean_something_else(tmp_path, clock, mode):
    controller, _ = build(tmp_path, clock)
    controller.set_mode(mode)
    assert hold(controller, clock, 3) is True  # a plain press in the end
    assert not controller.is_free(3)


@pytest.mark.parametrize("mode", [Mode.PLAY, Mode.RECORD, Mode.LOOP])
def test_the_hold_counts_in_play_record_and_loop_mode(tmp_path, clock, mode):
    controller, _ = build(tmp_path, clock)
    controller.set_mode(mode)
    assert hold(controller, clock, 3) is False and controller.is_free(3)


def test_no_switch_while_recording_and_a_hold_that_began_before_it_is_called_off(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    controller.press(0)  # recording on pad 0
    assert hold(controller, clock, 1) is True and not controller.is_free(1)
    controller.set_free(1, True)
    assert not controller.is_free(1)
    controller.press(0)

    controller.press_down(2)  # held ...
    clock.advance(0.3)
    controller.press(3)  # ... while another pad starts a recording
    clock.advance(1.0)
    controller.tick()
    assert not controller.is_free(2)
    assert controller.press_up(2) is False  # letting go must not stop that recording
    assert controller.recording_pad == 3


# ------------------------------------------------- recording and playing


def test_a_free_recording_keeps_its_length_on_an_existing_grid(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)  # the grid: 8000 frames
    hold(controller, clock, 1)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 1.3)
    assert wav_frames(tmp_path, controller, 1) == 10400  # not cut to 16000 and not stretched
    assert audio.record_align is False  # free recordings start at once
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    assert [e["type"] for e in events(controller)].count("master_set") == 1
    # The same take on a normal pad is fitted to whole loops.
    record(controller, clock, 2, 1.3)
    assert wav_frames(tmp_path, controller, 2) == 16000 and audio.record_align is True


def test_a_free_pad_recording_does_not_wait_for_the_next_loop_start(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    audio.wait = 0.5  # what a normal recording would be told
    controller.set_mode(Mode.RECORD)
    controller.press(1)
    assert controller.recording_limit() == controller.settings.max_record_seconds
    controller.press(1)


def test_a_free_pad_without_a_grid_gives_the_session_its_bar_unchanged(tmp_path, clock):
    controller, audio = build(tmp_path, clock, auto_grid=True)
    audio.clap_times = [0.4, 0.9]  # claps that the onset grid would turn into a grid of its own
    hold(controller, clock, 6)
    record(controller, clock, 6, 1.7)
    assert wav_frames(tmp_path, controller, 6) == 13600  # neither shifted nor cut
    master = [e for e in events(controller) if e["type"] == "master_set"]
    assert len(master) == 1 and master[0]["data"] == {
        "frames": 13600, "rate": SR, "source": "free_pad", "signature": "4/4", "pad": 6}
    assert master_source(controller.store.state.master) == "free_pad"
    assert audio.grid == 13600
    stop = [e for e in events(controller) if e["type"] == "record_stop"][-1]
    assert stop["data"]["grid"] == "free_pad" and "shift" not in stop["data"]
    # The next pad is a normal one and is fitted to the grid the free pad made.
    audio.clap_times = None
    record(controller, clock, 7, 0.5)
    assert wav_frames(tmp_path, controller, 7) == 13600


def test_a_too_short_free_pad_recording_is_dropped_and_sets_no_bar(tmp_path, clock):
    controller, _ = build(tmp_path, clock, auto_grid=True)
    hold(controller, clock, 6)
    record(controller, clock, 6, 0.2)
    assert controller.pad(6).sample is None and controller.store.state.master is None


def test_a_free_pad_sound_that_is_no_plausible_bar_leaves_the_session_without_a_grid(tmp_path, clock):
    controller, audio = build(tmp_path, clock, auto_grid=True)
    hold(controller, clock, 6)
    record(controller, clock, 6, 15.0)
    assert controller.pad(6).sample is not None and controller.is_free(6)
    assert controller.store.state.master is None
    assert not [e for e in events(controller) if e["type"] == "master_set"]
    stop = [e for e in events(controller) if e["type"] == "record_stop"][-1]
    assert stop["data"]["grid"] == "none" and stop["data"]["sample"] == controller.pad(6).sample
    assert controller.last_grid is not None and controller.last_grid.reason == "too_long"
    assert controller.grid_info() is None and audio.grid is None
    # Putting it back (undo, redo) does not turn it into a bar either.
    controller.undo()
    controller.redo()
    assert controller.store.state.master is None


def test_a_free_pad_gives_the_bar_even_with_the_onset_grid_off(tmp_path, clock):
    controller, _ = build(tmp_path, clock, auto_grid=False)
    hold(controller, clock, 0)
    record(controller, clock, 0, 1.0)
    assert controller.store.state.master["source"] == "free_pad"


def test_a_free_pad_with_a_grid_sets_no_tempo(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    record(controller, clock, 1, 1.3)
    assert [e["type"] for e in events(controller)].count("master_set") == 1
    assert controller.store.state.master == {"frames": 8000, "rate": SR}


def test_a_free_pad_sets_no_tempo_when_loops_are_not_held_to_a_grid(tmp_path, clock):
    controller, audio = build(tmp_path, clock, loop_sync=False)
    hold(controller, clock, 1)
    record(controller, clock, 1, 1.3)
    assert controller.store.state.master is None and audio.grid is None


def test_a_free_pad_sample_keeps_its_length_in_the_loop(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 1.3)
    record(controller, clock, 2, 1.3)
    controller.set_mode(Mode.LOOP)
    controller.press(1)
    data, loop = audio.voices[1]
    assert loop and len(data) == 10400
    assert np.array_equal(data, controller.sample_audio(controller.pad(1).sample))  # as recorded
    assert audio.play_modes[1] == (True, False)
    controller.press(2)  # a normal pad: the same sound is made two bars long and plays on the grid
    assert len(audio.voices[2][0]) == 16000 and audio.play_modes[2] == (False, False)


def test_the_grid_start_switch_asks_the_engine_to_begin_on_the_next_loop_start(tmp_path, clock):
    controller, audio = build(tmp_path, clock, free_pad_on_grid=True)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 1.3)
    controller.set_mode(Mode.LOOP)
    controller.press(1)
    assert audio.play_modes[1] == (True, True)
    assert len(audio.voices[1][0]) == 10400  # the length is not given up for the alignment


def test_the_grid_start_switch_is_off_by_default_and_live(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    assert Settings().free_pad_on_grid is False and "free_pad_on_grid" in LIVE_SETTINGS
    assert controller.apply_settings(replace(controller.settings, free_pad_on_grid=True)) == []
    assert controller.settings.free_pad_on_grid is True


def test_one_shot_play_of_a_free_pad_is_the_sample_as_recorded(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    record(controller, clock, 1, 1.3)
    controller.press(1)
    assert len(audio.voices[1][0]) == 10400 and audio.voices[1][1] is False


def test_redo_into_an_empty_session_makes_the_free_pad_give_the_bar_again(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    hold(controller, clock, 0)
    record(controller, clock, 0, 1.3)
    controller.undo(0)  # the take: the session is empty again
    assert controller.store.state.master is None
    controller.redo(0)
    last = events(controller)[-1]
    assert last["type"] == "master_set" and last["data"]["source"] == "free_pad"
    assert last["data"]["frames"] == 10400


def test_the_origin_of_the_bar_survives_a_restart(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    hold(controller, clock, 0)
    record(controller, clock, 0, 1.3)
    controller.shutdown()
    controller, _ = build(tmp_path, clock)
    assert controller.is_free(0)
    assert controller.store.state.master["source"] == "free_pad"
    assert controller._sample_grid[controller.pad(0).sample] == "free_pad"


# ---------------------------------------------------------------- export


def test_the_export_holds_a_free_pad_unchanged_and_cuts_it_hard_at_the_end(tmp_path, clock):
    controller, _ = build(tmp_path, clock, soft_seam=False, volume=0.5, max_level_db=0.0)
    record(controller, clock, 0, 1.0)  # bar: 8000 frames
    hold(controller, clock, 1)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 1.3)  # free: 10400 frames
    controller.set_mode(Mode.LOOP)
    controller.press(1)
    free_data = controller.sample_audio(controller.pad(1).sample)
    spec = ex.build_spec(controller, bars=2, fade_out=False)
    assert [len(p.data) for p in spec.loops] == [10400]  # not fitted to the bar
    out = ex.render_sum(spec)
    assert len(out) == 16000
    gain = np.float32(controller.volume)
    assert np.allclose(out[:10400], free_data * gain, atol=1e-6)
    # It repeats unchanged from its first frame and the render ends in the middle of the repeat.
    assert np.allclose(out[10400:], free_data[:5600] * gain, atol=1e-6)


def test_the_export_fits_a_normal_pad_but_not_a_free_one(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    hold(controller, clock, 1)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 1.3)
    record(controller, clock, 2, 1.3)
    controller.set_mode(Mode.LOOP)
    controller.press(1)
    controller.press(2)
    lengths = {p.pad: len(p.data) for p in ex.build_spec(controller, bars=2).loops}
    assert lengths == {1: 10400, 2: 16000}
    # "All pads as loop" takes the same lengths.
    lengths = {p.pad: len(p.data) for p in ex.build_spec(controller, bars=2, all_pads=True).loops}
    assert lengths[1] == 10400


# ------------------------------------------------------------ the audio engine


def make_engine(grid=1000, **device_args):
    device = FakeSoundDevice(**device_args)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=0.0, sd=device, clock=lambda: 0.0)
    audio.set_grid(grid)
    return audio, device


def clicks(length: int, amp: float, at=(0,)) -> np.ndarray:
    data = np.zeros(length, dtype=np.float32)
    data[list(at)] = amp
    return data


def nonzero(signal: np.ndarray) -> dict[int, float]:
    return {int(i): round(float(signal[i]), 4) for i in np.flatnonzero(signal)}


def test_a_free_loop_plays_in_its_own_length_and_starts_at_once():
    audio, device = make_engine()
    audio.play(0, clicks(1000, 0.25), loop=True)
    device.run_to(1300)
    audio.play(1, clicks(1500, 0.5), loop=True, free=True)
    assert audio.pending_pads() == set()
    device.run_to(5000)
    out = nonzero(device.output_signal())
    assert {k: v for k, v in out.items() if v == 0.5} == {1300: 0.5, 2800: 0.5, 4300: 0.5}


def test_a_free_loop_on_the_grid_waits_for_the_next_loop_start_and_keeps_its_length():
    audio, device = make_engine()
    audio.play(0, clicks(1000, 0.25), loop=True)
    device.run_to(1300)
    audio.play(1, clicks(1500, 0.5), loop=True, free=True, align=True)
    assert audio.pending_pads() == {1}
    device.run_to(5000)
    # The grid loop clicks every 1000 frames; the free one begins on the boundary at 2000 and
    # then comes every 1500 frames (its own length), so it drifts against the grid.
    assert nonzero(device.output_signal()) == {
        0: 0.25, 1000: 0.25, 2000: 0.75, 3000: 0.25, 3500: 0.5, 4000: 0.25}
    assert audio.pending_pads() == set()


def test_a_free_loop_is_never_part_of_the_grid():
    audio, device = make_engine()
    audio.play(0, clicks(1500, 0.5), loop=True, free=True)
    device.run_to(200)
    assert audio.next_boundary_in() is None  # nothing runs on the grid
    audio.play(1, clicks(1000, 0.25), loop=True)  # a grid loop starts at once and anchors the grid itself
    assert audio.pending_pads() == set()
    device.run_to(300)
    audio.stop(0, at_boundary=True)  # a free loop stops at once
    assert audio.playing_pads() == {1}


def test_a_free_loop_alone_starts_at_once_even_with_the_alignment_switch():
    audio, device = make_engine()
    device.run_to(300)
    audio.play(0, clicks(1500, 0.5), loop=True, free=True, align=True)
    assert audio.pending_pads() == set()
    device.run_to(2000)
    assert 300 in nonzero(device.output_signal())


def test_a_free_recording_starts_at_once_while_loops_play():
    audio, device = make_engine(loopback=False)
    audio.play(0, clicks(1000, 0.25), loop=True)
    device.run_to(300)
    assert audio.start_recording(align=False) is True
    assert audio.recording_wait() == 0.0
    audio.stop_recording()
    assert audio.start_recording() is True  # the normal one waits for the loop start
    assert audio.recording_wait() > 0.0
    audio.stop_recording()


# ---------------------------------------------------------------- settings


def test_the_grid_start_switch_is_a_boolean_setting():
    assert parse_settings({}).free_pad_on_grid is False
    assert parse_settings({"free_pad_on_grid": True}).free_pad_on_grid is True
    with pytest.raises(ConfigError, match="free_pad_on_grid"):
        parse_settings({"free_pad_on_grid": "ja"}, "settings.toml")


def test_the_parents_page_offers_the_grid_start_switch():
    from loopstation.gui.settings_page import FIELDS

    assert any(f.key == "free_pad_on_grid" and f.kind == "bool" for f in FIELDS)


# --------------------------------------------------------------- the screen


@pytest.fixture
def window(qapp, tmp_path, clock):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    win = MainWindow(controller, None, [])
    win.resize(1280, 800)
    win.show()
    QTest.qWaitForWindowExposed(win)
    yield win
    win.timer.stop()
    win.close()
    store.close()


def center(widget) -> QPoint:
    return QPoint(widget.width() // 2, widget.height() // 2)


def test_holding_a_pad_on_the_screen_fills_a_ring_then_turns_it_into_a_circle(window, clock):
    pad = window.grid.pads[6]
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    clock.advance(FREE_HOLD_SECONDS / 2)
    window._tick()
    assert pad.hold == pytest.approx(0.5, abs=0.01) and not pad.free
    clock.advance(FREE_HOLD_SECONDS)
    window._tick()
    assert pad.free and pad.hold is None
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    assert window.controller.recording_pad is None  # the hold did not start a recording
    assert window.controller.is_free(6)
    # The badge of the latest change sits on the pad and takes the switch back (the other gesture).
    assert pad.badge_button is not None
    pad.badge_button.click()
    assert not window.controller.is_free(6) and not pad.free


def test_a_tap_on_the_screen_still_starts_a_recording(window, clock):
    pad = window.grid.pads[0]
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    assert window.controller.recording_pad == 0 and pad.color == "red"


def test_a_press_that_slides_off_the_pad_is_not_a_tap(window, clock):
    pad = window.grid.pads[1]
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    QTest.mouseMove(pad, QPoint(-40, -40))
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(-40, -40))
    assert window.controller.recording_pad is None


def test_the_pads_are_rendered_round_with_a_wave_when_free(window, clock):
    for pad in (2, 3):
        window.controller.press(pad)
        clock.advance(1.0)
        window.controller.press(pad)
    window.controller.set_free(2, True)
    window.refresh()
    free, plain = window.grid.pads[2], window.grid.pads[3]
    assert free.free and not plain.free
    shot_free, shot_plain = free.grab().toImage(), plain.grab().toImage()
    corner = (int(free.width() * 0.09), int(free.height() * 0.09))
    middle = (free.width() // 2, free.height() // 2)
    # Yellow pad: the corner of the visible square is yellow, on the circle it is background.
    top = (middle[0], int(free.height() * 0.2))

    def yellow(color) -> bool:
        return color.red() > 200 and color.green() > 170 and color.blue() < 160

    assert yellow(shot_plain.pixelColor(*corner)) and not yellow(shot_free.pixelColor(*corner))
    assert yellow(shot_free.pixelColor(*top))
    # The wave symbol is drawn: the free pad differs from a plain one in its middle row.
    row = free.height() // 2
    assert {shot_free.pixel(x, row) for x in range(middle[0] - 25, middle[0] + 25)} != {
        shot_plain.pixel(x, row) for x in range(middle[0] - 25, middle[0] + 25)}


def test_the_hold_ring_and_its_words_are_drawn_while_held(window, clock):
    pad = window.grid.pads[4]
    plain = pad.grab().toImage()
    window.controller.press_down(4)
    clock.advance(FREE_HOLD_SECONDS * 0.6)
    window.controller.tick()
    window.refresh()
    assert pad.hold == pytest.approx(0.6, abs=0.01)
    ringed = pad.grab().toImage()
    assert ringed != plain
    window.controller.press_up(4)


def test_a_dialog_blocks_the_hold_like_it_blocks_a_press(window, clock):
    window._dialog_open = True
    pad = window.grid.pads[5]
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    clock.advance(FREE_HOLD_SECONDS + 0.1)
    window._tick()
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(pad))
    assert not window.controller.is_free(5) and window.controller.recording_pad is None
    window._dialog_open = False


# ---------------------------------------------------------------- Launchpad

MINI_LINUX = [
    "Launchpad Mini MK3:Launchpad Mini MK3 LPMiniMK3 DA 20:0",
    "Launchpad Mini MK3:Launchpad Mini MK3 LPMiniMK3 MI 20:1",
]


def connect_launchpad():
    ports = FakeMidiPorts(MINI_LINUX)
    pad_clock = FakeClock(0.0)
    launchpad = LaunchpadController(lambda: ports, 3, 4, clock=pad_clock, message_factory=fake_message)
    launchpad.poll_events()
    return launchpad, ports.opened["in:" + MINI_LINUX[1]]


def test_a_hold_whose_key_up_is_lost_with_the_launchpad_does_not_switch_the_free_mode(
    qapp, tmp_path, clock
):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    ports = FakeMidiPorts(MINI_LINUX)
    pad_clock = FakeClock(0.0)
    launchpad = LaunchpadController(lambda: ports, 3, 4, clock=pad_clock, message_factory=fake_message)
    launchpad.poll_events()
    inport = ports.opened["in:" + MINI_LINUX[1]]
    win = MainWindow(controller, launchpad, [])
    win.timer.stop()
    try:
        inport.pending += [FakeMessage("note_on", note=81, velocity=100)]
        win._tick()
        assert controller.hold_progress(0) is not None
        ports.outputs.clear()  # unplugged: the note off never comes
        pad_clock.advance(60.0)
        win._tick()
        assert not launchpad.connected and controller.hold_progress(0) is None
        clock.advance(FREE_HOLD_SECONDS + 0.5)
        win._tick()
        assert not controller.is_free(0)
        assert controller.press_up(0) is False
    finally:
        win.close()
        store.close()


def test_the_launchpad_reports_presses_and_releases_in_order():
    launchpad, inport = connect_launchpad()
    inport.pending += [
        FakeMessage("note_on", note=81, velocity=100),
        FakeMessage("note_on", note=64, velocity=90),
        FakeMessage("note_on", note=81, velocity=0),
        FakeMessage("note_off", note=64, velocity=0),
        FakeMessage("polytouch", note=64, velocity=50),
        FakeMessage("note_off", note=88, velocity=0),  # outside the grid
    ]
    assert launchpad.poll_events() == [(0, True), (11, True), (0, False), (11, False)]
    inport.pending += [FakeMessage("note_on", note=81, velocity=100), FakeMessage("note_off", note=81)]
    assert launchpad.poll() == [0]  # poll() still lists only the presses


def test_a_held_launchpad_key_switches_the_free_mode_and_a_tap_still_presses(qapp, tmp_path, clock):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    launchpad, inport = connect_launchpad()
    win = MainWindow(controller, launchpad, [])
    win.timer.stop()
    try:
        inport.pending += [FakeMessage("note_on", note=81, velocity=100)]
        win._tick()
        clock.advance(FREE_HOLD_SECONDS + 0.1)
        win._tick()
        assert controller.is_free(0)
        inport.pending += [FakeMessage("note_off", note=81)]
        win._tick()
        assert controller.recording_pad is None  # the release after the hold is no press

        inport.pending += [FakeMessage("note_on", note=72, velocity=100)]  # pad 5, a quick tap
        win._tick()
        clock.advance(0.1)
        inport.pending += [FakeMessage("note_on", note=72, velocity=0)]
        win._tick()
        assert controller.recording_pad == 5
    finally:
        win.close()
        store.close()
