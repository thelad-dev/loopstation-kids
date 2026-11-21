"""Onset grid: the first recording starts at its first onset and may set the grid.

Controller on FakeAudio in clap mode (``clap_times``): Regeln 1-5 aus dem
Plan (2.2) end to end, ``master_set.source``, old logs, auto grid off, and
undo, redo, restore and replay of a shifted recording. No audio device.
"""

from __future__ import annotations

import json

import numpy as np
import soundfile
from conftest import FakeAudio, FakeClock, clap_signal, make_settings

from loopstation.audio.samples import load_wav
from loopstation.config import Settings
from loopstation.controller import Controller, Mode
from loopstation.state import master_source, parse_master
from loopstation.store import EventStore

SR = 8000


def build(tmp_path, clock: FakeClock, claps=None, **overrides):
    overrides.setdefault("auto_grid", True)
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    audio.clap_times = claps
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def events(controller: Controller) -> list[dict]:
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def of_type(controller: Controller, type_: str) -> list[dict]:
    return [e for e in events(controller) if e["type"] == type_]


def saved(tmp_path, controller: Controller, pad: int) -> np.ndarray:
    return load_wav(tmp_path / "samples" / controller.pad(pad).sample, SR)


def first_hit(data: np.ndarray) -> int:
    """Frame of the first sample that is clearly loud."""
    return int(np.argmax(np.abs(data) > 0.1))


# --- Regeln 1 und 4: der Abstand der Schlaege ist ein Schlag, vier Schlaege ein Takt -----------


def test_two_claps_in_the_window_set_a_four_beat_bar_and_start_the_loop_at_the_first_clap(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    master = controller.store.state.master
    assert master["frames"] == 4 * 4000 and master["source"] == "onset"
    assert master["signature"] == "4/4" and master["pad"] == 0 and master["rate"] == SR
    assert audio.grid == master["frames"]
    data = saved(tmp_path, controller, 0)
    assert len(data) == master["frames"]  # one bar, nothing longer than the grid
    assert first_hit(data) <= 1  # the loop begins at the attack of the first clap, to the sample
    stop = of_type(controller, "record_stop")[0]["data"]
    # clap_signal starts with sin(0) = 0: the first loud sample of the clap is frame 0.5 s + 1.
    assert stop["grid"] == "onset" and 0.5 * SR <= stop["shift"] <= 0.5 * SR + 1


def test_more_claps_use_the_median_distance_and_drop_outliers(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 0.6, 1.1, 1.6])  # 0.1 s is a double hit
    record(controller, clock, 0, 3.0)
    assert controller.store.state.master["frames"] == 4 * 4000
    assert master_source(controller.store.state.master) == "onset"


def attacks(data: np.ndarray, quiet: int = 400) -> list[int]:
    """Frames where a clap begins: clearly loud after ``quiet`` frames of silence."""
    loud = np.nonzero(np.abs(data) > 0.1)[0]
    out: list[int] = []
    for frame in loud:
        if not out or frame - out[-1] > quiet:
            out.append(int(frame))
    return out


def test_a_child_getting_slower_gives_a_loop_that_is_tight_over_the_seam(tmp_path, clock):
    # The claps of the recording (44.1 kHz frames, here as seconds): intervals 20680, 20856,
    # 21120, then a pause of 23000 and 21296, 21296, 21500. The median beat (21296) as the bar
    # would leave the fourth clap 1600 frames short of the seam.
    gaps = [20680, 20856, 21120, 23000, 21296, 21296, 21500]
    frames = [15840]
    for gap in gaps:
        frames.append(frames[-1] + gap)
    controller, _ = build(tmp_path, clock, claps=[f / 44100 for f in frames])
    record(controller, clock, 0, 169_168 / 44100)
    master = controller.store.state.master
    data = saved(tmp_path, controller, 0)
    assert master["source"] == "onset" and len(data) == master["frames"]
    assert of_type(controller, "master_set")[0]["data"]["frames"] == master["frames"]
    beat = master["frames"] / 4
    hits = attacks(data)
    assert len(hits) == 4  # the four claps of the loop window, nothing cut at the seam
    assert hits[0] <= 0.25 * beat  # the loop starts at (or just before) the first attack
    for k, hit in enumerate(hits):
        assert abs(hit - k * beat) <= 0.003 * SR  # every clap within 3 ms of its line
    inside = [b - a for a, b in zip(hits, hits[1:], strict=False)]
    seam = master["frames"] - hits[3] + hits[0]
    assert min(inside) <= seam <= max(inside)  # no limp over the seam


def test_master_set_event_carries_source_signature_and_pad(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0], time_signature="3/4")
    record(controller, clock, 2, 3.0)
    data = of_type(controller, "master_set")[0]["data"]
    assert data == {"frames": 3 * 4000, "rate": SR, "source": "onset", "signature": "3/4", "pad": 2}


def test_tempo_window_is_a_setting(tmp_path, clock):
    # 0.5 s per beat is 120 BPM: outside a window up to 100 BPM, so the length is the bar (3 s = 80 BPM).
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0], grid_bpm_max=100.0)
    record(controller, clock, 0, 3.0)
    master = controller.store.state.master
    assert master["source"] == "duration" and master["frames"] == 3 * SR


# --- Regel 2 und 3: zu kleiner und zu grosser Abstand ----------------------------------------


def test_a_double_hit_gives_no_onset_grid(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 0.6])
    record(controller, clock, 0, 2.0)
    master = controller.store.state.master
    assert master["source"] == "duration" and master["frames"] == 2 * SR


def test_a_far_apart_pair_is_not_a_silent_long_bar_but_the_recording_length(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 3.5])  # 3 s apart, 20 BPM as a beat
    record(controller, clock, 0, 6.0)  # as one bar 40 BPM: still a sensible bar
    master = controller.store.state.master
    assert master["source"] == "duration" and master["frames"] == 6 * SR
    assert first_hit(saved(tmp_path, controller, 0)) < 0.02 * SR  # still shifted to the first clap


def test_no_grid_outside_the_tempo_window_even_for_the_length(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 3.5])
    record(controller, clock, 0, 9.0)  # 9 s as one bar is 27 BPM
    assert controller.store.state.master is None and audio.grid is None
    assert of_type(controller, "master_set") == []
    assert of_type(controller, "record_stop")[0]["data"]["grid"] == "none"
    assert controller.last_grid is not None and not controller.last_grid.has_grid
    data = saved(tmp_path, controller, 0)
    assert len(data) == 9 * SR and abs(first_hit(data) - int(0.5 * SR)) < 5  # kept as recorded, not shifted
    assert controller.grid_info() is None


def test_a_bar_longer_than_the_recording_is_never_made(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.5])  # 1 s beats: 4 s bar in a 3 s recording
    record(controller, clock, 0, 3.0)
    master = controller.store.state.master
    assert master["source"] == "duration" and master["frames"] == 3 * SR


# --- Regel 5: ein Schlag oder keiner ----------------------------------------------------------


def test_one_clap_shifts_the_recording_circularly_and_keeps_its_length(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.4])
    record(controller, clock, 0, 2.0)
    master = controller.store.state.master
    assert master["source"] == "duration" and master["frames"] == 2 * SR
    original = clap_signal(2 * SR, SR, [0.4])
    shift = of_type(controller, "record_stop")[0]["data"]["shift"]
    assert np.allclose(saved(tmp_path, controller, 0), np.roll(original, -shift), atol=1e-3)  # WAV is 16 bit


def test_silence_is_the_recording_length_unshifted(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[])
    record(controller, clock, 0, 2.0)
    assert controller.store.state.master["source"] == "duration"
    stop = of_type(controller, "record_stop")[0]["data"]
    assert stop["grid"] == "duration" and "shift" not in stop


def test_a_tap_shorter_than_the_minimum_is_still_discarded(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.05])
    record(controller, clock, 0, 0.2)
    assert controller.pad(0).sample is None and controller.notice() == "Zu kurz - nochmal!"
    assert controller.store.state.master is None


# --- Regel 6/8-Rand und C4: nur die grid-stiftende Aufnahme wird verschoben -------------------


def test_a_recording_on_an_existing_grid_is_not_shifted(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)  # grid: 16000 frames
    audio.clap_times = [0.3]
    controller.set_mode(Mode.PLAY)
    record(controller, clock, 1, 2.0)  # exactly one bar
    data = saved(tmp_path, controller, 1)
    assert np.allclose(data, clap_signal(4 * 4000, SR, [0.3]), atol=1e-3)  # no rotation, only fitted
    stop = of_type(controller, "record_stop")[1]["data"]
    assert "grid" not in stop and "shift" not in stop
    assert len(of_type(controller, "master_set")) == 1


def test_onset_runs_before_fit_to_grid(tmp_path, clock):
    # The first take on the pad again, after the grid exists: cut to whole bars, never shifted.
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    audio.clap_times = [0.7]
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 0, 3.0)  # grid is 2 s, so 3 s become 2 bars
    data = saved(tmp_path, controller, 0)
    assert len(data) == 2 * 4 * 4000
    assert np.allclose(data, clap_signal(len(data), SR, [0.7]), atol=1e-3)


# --- Auto-Grid aus: heutiges Verhalten ---------------------------------------------------------


def test_auto_grid_off_is_todays_behaviour_to_the_bit(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0], auto_grid=False)
    record(controller, clock, 0, 3.0)
    assert np.allclose(saved(tmp_path, controller, 0), clap_signal(3 * SR, SR, [0.5, 1.0]), atol=1e-3)
    assert controller.store.state.master == {"frames": 3 * SR, "rate": SR}
    assert of_type(controller, "master_set")[0]["data"] == {"frames": 3 * SR, "rate": SR}
    stop = of_type(controller, "record_stop")[0]["data"]
    assert set(stop) == {"sample", "duration", "frames"}
    assert audio.grid == 3 * SR


def test_auto_grid_is_off_by_default():
    assert Settings().auto_grid is False


def test_loop_sync_off_leaves_the_recording_alone(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0], loop_sync=False)
    record(controller, clock, 0, 3.0)
    assert np.allclose(saved(tmp_path, controller, 0), clap_signal(3 * SR, SR, [0.5, 1.0]), atol=1e-3)
    assert controller.store.state.master is None


# --- Alte Logs, Replay, Zustand ----------------------------------------------------------------


def test_a_master_without_source_reads_as_duration():
    master = parse_master({"frames": 100, "rate": SR})
    assert master == {"frames": 100, "rate": SR} and master_source(master) == "duration"


def test_parse_master_keeps_only_well_formed_extras():
    raw = {"frames": 100, "rate": SR, "source": "onset", "signature": "6/8", "pad": 3}
    assert parse_master(raw) == raw
    assert parse_master({**raw, "source": 5, "signature": "", "pad": -1}) == {"frames": 100, "rate": SR}
    assert parse_master({**raw, "pad": True}) == {"frames": 100, "rate": SR, "source": "onset",
                                                  "signature": "6/8"}


def test_old_logs_without_source_replay_as_before(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=None, auto_grid=False)
    record(controller, clock, 0, 1.0)
    reopened, _ = build(tmp_path, clock, auto_grid=True)
    assert reopened.store.state.master == {"frames": SR, "rate": SR}
    info = reopened.grid_info()
    assert info.source == "duration" and info.pad is None and info.signature == "4/4"


def test_source_survives_replay_and_snapshot(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    controller.store.close()
    reopened, _ = build(tmp_path, clock)
    assert reopened.store.state.master == {"frames": 16000, "rate": SR, "source": "onset",
                                           "signature": "4/4", "pad": 0}
    assert reopened.store.state.to_dict()["master"]["source"] == "onset"


# --- Undo, Redo, Verlauf: Verschiebung und Quelle gehoeren zusammen -----------------------------


def test_undo_redo_and_restore_bring_the_shifted_recording_and_its_source_back(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    sample = controller.pad(0).sample
    before = saved(tmp_path, controller, 0).copy()
    controller.undo()
    assert controller.pad(0).sample is None and controller.store.state.master is None
    controller.redo()
    assert controller.pad(0).sample == sample
    assert controller.store.state.master == {"frames": 16000, "rate": SR, "source": "onset",
                                             "signature": "4/4", "pad": 0}
    assert np.array_equal(saved(tmp_path, controller, 0), before)  # the file is the shifted take
    controller.delete_all()
    controller.restore(0, sample)
    assert master_source(controller.store.state.master) == "onset"
    assert audio.grid == 16000


def test_a_sample_without_grid_stays_free_when_it_is_brought_back(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 3.5])
    record(controller, clock, 0, 9.0)
    sample = controller.pad(0).sample
    controller.undo()
    controller.redo()
    assert controller.store.state.master is None and audio.grid is None
    controller.delete_all()
    controller.restore(0, sample)
    assert controller.store.state.master is None
    # also after a restart: the decision is read back from the log
    controller.store.close()
    reopened, _ = build(tmp_path, clock)
    reopened.delete_all()
    reopened.restore(0, sample)
    assert reopened.store.state.master is None


def test_the_source_of_a_shifted_take_is_remembered_after_a_restart(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    sample = controller.pad(0).sample
    controller.delete_all()
    controller.store.close()
    reopened, _ = build(tmp_path, clock)
    reopened.restore(0, sample)
    assert master_source(reopened.store.state.master) == "onset"
    assert reopened.store.state.master["frames"] == 16000


def test_audio_of_the_restored_take_is_the_shifted_file_not_the_raw_recording(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.4])
    record(controller, clock, 0, 2.0)
    info = soundfile.info(str(tmp_path / "samples" / controller.pad(0).sample))
    assert info.frames == 2 * SR
    assert first_hit(saved(tmp_path, controller, 0)) < 0.02 * SR


# --- Elternansicht -------------------------------------------------------------------------------


def test_grid_info_gives_tempo_signature_bar_length_and_source(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    info = controller.grid_info()
    assert round(info.bpm) == 120 and info.signature == "4/4" and info.beats == 4
    assert info.seconds == 2.0 and info.source == "onset" and info.pad == 0


def test_bpm_of_a_length_grid_uses_the_time_signature(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[], time_signature="3/4")
    record(controller, clock, 0, 2.5)
    info = controller.grid_info()
    assert info.source == "duration" and round(info.bpm) == 72  # 3 beats in 2.5 s


def test_apply_settings_takes_the_auto_grid_switch_live(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0], auto_grid=False)
    controller.apply_settings(Settings(**{**controller.settings.__dict__, "auto_grid": True}))
    record(controller, clock, 0, 3.0)
    assert master_source(controller.store.state.master) == "onset"
