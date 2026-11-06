"""Taktgenauer Schnitt: the first sound of a session sets the loop length.

Controller tests run on FakeAudio and check the cut in exact frames (WAV
length) and the events in the log; the last test runs the controller on the
real SoundDeviceAudio with a stand-in sound card, exact to the sample.
"""

from __future__ import annotations

import json

import numpy as np
import soundfile
from conftest import FakeAudio, FakeClock, FakeSoundDevice, make_settings

from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.controller import Controller, Mode
from loopstation.store import EventStore

SR = 8000


def build(tmp_path, clock: FakeClock, audio=None, **overrides):
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = audio or FakeAudio(clock)
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


def wav_frames(tmp_path, controller: Controller, pad: int) -> int:
    return soundfile.info(str(tmp_path / "samples" / controller.pad(pad).sample)).frames


def test_first_recording_sets_the_loop_length(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    last = events(controller)[-2:]
    assert [e["type"] for e in last] == ["record_stop", "master_set"]
    assert last[0]["data"]["frames"] == 8000
    assert last[1]["data"] == {"frames": 8000, "rate": SR}
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    assert audio.grid == 8000
    assert wav_frames(tmp_path, controller, 0) == 8000


def test_later_recordings_are_cut_to_whole_loops(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    record(controller, clock, 1, 0.4)  # shorter: filled with silence
    record(controller, clock, 2, 1.5)  # longer: next multiple
    record(controller, clock, 3, 1.1)  # just late: still one loop
    assert [wav_frames(tmp_path, controller, p) for p in (1, 2, 3)] == [8000, 16000, 8000]
    data, _ = soundfile.read(str(tmp_path / "samples" / controller.pad(1).sample), dtype="float32")
    assert np.any(data[:3200]) and not np.any(data[3200:])
    # Only the first one set a loop length.
    assert [e["type"] for e in events(controller)].count("master_set") == 1


def test_a_new_take_of_the_first_pad_keeps_the_loop_length(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 0, 2.5)
    assert wav_frames(tmp_path, controller, 0) == 24000
    assert controller.store.state.master == {"frames": 8000, "rate": SR}


def test_automatic_stop_after_whole_loops(tmp_path, clock):
    controller, _ = build(tmp_path, clock, max_record_seconds=3)
    record(controller, clock, 0, 1.4)  # 11200 frames: two loops fit into 3 s
    controller.press(1)
    assert controller.recording_limit() == 2.8
    clock.advance(2.7)
    controller.tick()
    assert controller.recording_pad == 1
    clock.advance(0.15)
    controller.tick()
    assert controller.recording_pad is None
    assert wav_frames(tmp_path, controller, 1) == 22400


def test_session_ends_only_when_the_last_pad_is_emptied(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    record(controller, clock, 1, 1.0)
    controller.set_mode(Mode.DELETE)
    controller.press(0)  # the first pad goes, the loop length stays
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    assert controller.session_shown() is None
    controller.set_mode(Mode.DELETE)
    controller.press(1)
    assert events(controller)[-1]["type"] == "session_start"
    assert controller.store.state.master is None and audio.grid is None
    assert controller.session_shown() == 0.0  # the pads show the new session
    clock.advance(2)
    controller.tick()
    assert controller.session_shown() is None

    record(controller, clock, 5, 0.6)  # new session, new loop length
    assert controller.store.state.master == {"frames": 4800, "rate": SR}
    assert wav_frames(tmp_path, controller, 5) == 4800


def test_undo_of_delete_all_brings_the_loop_length_back(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    controller.delete_all()
    assert [e["type"] for e in events(controller)[-2:]] == ["delete_all", "session_start"]
    assert audio.grid is None
    controller.undo()
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    assert audio.grid == 8000
    assert events(controller)[-1]["type"] == "undo"
    controller.undo()  # the first recording: empty again, a new session
    assert controller.store.state.master is None
    assert events(controller)[-1]["type"] == "session_start"
    assert controller.delete_all() is None and events(controller)[-1]["type"] == "delete_all"


def test_restore_into_an_empty_session_sets_the_loop_length_from_that_pad(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 0, 2.0)  # second version: two loops
    long_version = controller.pad(0).sample
    controller.delete_all()
    controller.restore(0, long_version)
    assert events(controller)[-1] == {**events(controller)[-1], "type": "master_set",
                                      "data": {"frames": 16000, "rate": SR}}
    assert controller.store.state.master == {"frames": 16000, "rate": SR}
    controller.undo()
    assert controller.store.state.master is None
    assert events(controller)[-1]["type"] == "session_start"


def test_older_versions_are_fitted_for_looping_without_touching_the_file(tmp_path, clock):
    controller, _ = build(tmp_path, clock, loop_sync=False)
    record(controller, clock, 0, 0.5)
    short_version = controller.pad(0).sample
    controller.shutdown()

    controller, audio = build(tmp_path, clock)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 0, 1.0)  # no loop length yet: this one sets it
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    controller.restore(0, short_version)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    played = audio.voices[0][0]
    assert len(played) == 8000 and not np.any(played[4000:])
    assert soundfile.info(str(tmp_path / "samples" / short_version)).frames == 4000


def test_loop_pads_stop_on_the_grid_but_delete_and_undo_stop_at_once(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.press(0)
    assert audio.calls[-1] == ("stop", 0, True)
    controller.press(0)
    controller.set_mode(Mode.DELETE)
    controller.press(0)
    assert ("stop", 0, False) in audio.calls[-3:]


def test_switched_off_everything_stays_free(tmp_path, clock):
    controller, audio = build(tmp_path, clock, loop_sync=False)
    record(controller, clock, 0, 1.0)
    record(controller, clock, 1, 0.4)
    assert wav_frames(tmp_path, controller, 1) == 3200
    assert controller.store.state.master is None and audio.grid is None
    assert "master_set" not in [e["type"] for e in events(controller)]


def test_waiting_pads_and_loop_progress(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 1.0)
    audio.wait = 0.5
    audio.boundary_in = 0.25
    audio.pending = {3}
    controller.press(1)
    assert controller.recording_waits()
    assert controller.waiting_pads() == {1, 3}
    assert controller.loop_progress() == 0.75
    audio.wait = 0.0
    assert not controller.recording_waits() and controller.waiting_pads() == {3}


def test_second_loop_lands_on_the_first_one_on_a_real_engine(tmp_path, clock):
    """Controller plus SoundDeviceAudio on a stand-in sound card.

    The speaker sits next to the microphone (10 ms there and back, set in
    ``latency_ms``). The child records a first loop, starts it, records a
    second pad while the first one plays and loops it too: the second loop
    must be the first one sample for sample, starting on its loop start.
    """
    device = FakeSoundDevice(block=100, delay=80, loopback=True)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=0.01, sd=device, clock=lambda: 0.0)
    controller, _ = build(tmp_path, clock, audio=audio, sound_effects=False)

    device.voice = lambda frames: (0.2 * np.sin(frames * 0.37)).astype(np.float32)
    controller.press(0)
    device.step(80)  # one second
    controller.press(0)
    assert controller.store.state.master == {"frames": 8000, "rate": SR}
    first = soundfile.read(str(tmp_path / "samples" / controller.pad(0).sample), dtype="float32")[0]

    device.voice = None  # from here on the microphone only hears the speaker
    controller.set_mode(Mode.LOOP)
    anchor = device.frame
    controller.press(0)
    device.step(30)
    controller.press(1)  # empty pad in loop mode: record, waits for the loop start
    assert controller.waiting_pads() == {1}
    device.step(50)
    assert controller.recording_waits() is False and controller.recording_pad == 1
    device.step(83)  # a little past the end of that loop
    controller.press(1)
    second = soundfile.read(str(tmp_path / "samples" / controller.pad(1).sample), dtype="float32")[0]
    assert len(second) == 8000
    assert np.array_equal(second, first)

    controller.press(1)  # loop it: starts on the next loop start
    start = anchor + 8000 * (-(-(device.frame - anchor) // 8000))
    assert controller.waiting_pads() == {1}
    device.run_to(start + 16000)
    assert controller.waiting_pads() == set()
    out = device.output_signal()
    loop = controller._loop_data(controller.pad(0).sample)
    assert np.array_equal(out[start:start + 16000], np.tile(2 * loop, 2))
