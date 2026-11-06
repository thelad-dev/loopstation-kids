"""SoundDeviceAudio on a stand-in sound card: loop grid and recording, exact to the sample.

Nothing here needs PortAudio or a real device; the test drives the output and
input callbacks block by block (see ``FakeSoundDevice``).
"""

from __future__ import annotations

import numpy as np
from conftest import FakeSoundDevice

from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.audio.sync import fit_to_grid, grace_frames

SR = 8000
GRID = 1000


def make(grid: int | None = GRID, latency: float | None = 0.0, **device_args):
    device = FakeSoundDevice(**device_args)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=latency, sd=device, clock=lambda: 0.0)
    audio.set_grid(grid)
    return audio, device


def clicks(length: int, amp: float, at=(0,)) -> np.ndarray:
    data = np.zeros(length, dtype=np.float32)
    data[list(at)] = amp
    return data


def coded(frames: np.ndarray) -> np.ndarray:
    """A microphone signal that tells which frame it was heard at."""
    return (np.asarray(frames, dtype=np.float64) * 1e-5).astype(np.float32)


def nonzero(signal: np.ndarray) -> dict[int, float]:
    return {int(i): round(float(signal[i]), 4) for i in np.flatnonzero(signal)}


# --------------------------------------------------------------- playback


def test_first_loop_starts_at_once_and_the_next_one_on_the_grid():
    audio, device = make()
    device.run_to(300)
    audio.play(0, clicks(GRID, 0.25), loop=True)  # anchors the grid at frame 300
    assert audio.pending_pads() == set()
    device.run_to(1800)
    audio.play(1, clicks(GRID, 0.5), loop=True)
    assert audio.pending_pads() == {1}
    assert audio.next_boundary_in() == (2300 - 1800) / SR
    device.run_to(4500)
    assert audio.pending_pads() == set()
    assert nonzero(device.output_signal()) == {
        300: 0.25, 1300: 0.25, 2300: 0.75, 3300: 0.75, 4300: 0.75}


def test_a_double_length_loop_starts_from_its_beginning():
    audio, device = make()
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1500)
    audio.play(1, clicks(2 * GRID, 0.5, at=(0, 1000)) * np.float32(1), loop=True)
    device.run_to(5100)
    out = device.output_signal()
    assert nonzero(out) == {0: 0.25, 1000: 0.25, 2000: 0.75, 3000: 0.75, 4000: 0.75, 5000: 0.75}


def test_a_half_length_loop_stays_in_phase():
    audio, device = make()
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(700)
    audio.play(1, clicks(GRID // 2, 0.5), loop=True)
    device.run_to(3000)
    assert nonzero(device.output_signal()) == {
        0: 0.25, 1000: 0.75, 1500: 0.5, 2000: 0.75, 2500: 0.5}


def test_stopping_a_loop_waits_for_the_next_loop_start():
    audio, device = make()
    audio.play(0, np.full(GRID, 0.1, dtype=np.float32), loop=True)
    device.run_to(2500)
    audio.stop(0, at_boundary=True)
    assert audio.pending_pads() == {0} and audio.playing_pads() == {0}
    device.run_to(4000)
    out = device.output_signal()
    assert np.all(out[:3000] == np.float32(0.1)) and not out[3000:].any()
    assert audio.playing_pads() == set() and audio.pending_pads() == set()


def test_starting_the_loop_again_before_it_stops_keeps_it_going():
    audio, device = make()
    data = clicks(GRID, 0.25)
    audio.play(0, data, loop=True)
    device.run_to(2500)
    audio.stop(0, at_boundary=True)
    audio.play(0, data, loop=True)
    assert audio.pending_pads() == set()
    device.run_to(4100)
    assert nonzero(device.output_signal()) == {0: 0.25, 1000: 0.25, 2000: 0.25, 3000: 0.25, 4000: 0.25}


def test_a_loop_that_has_not_started_yet_stops_at_once():
    audio, device = make()
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1500)
    audio.play(1, clicks(GRID, 0.5), loop=True)
    audio.stop(1, at_boundary=True)
    assert audio.playing_pads() == {0}
    device.run_to(3000)
    assert nonzero(device.output_signal()) == {0: 0.25, 1000: 0.25, 2000: 0.25}


def test_plain_stop_one_shots_and_free_loops_are_immediate():
    audio, device = make()
    audio.play(0, np.full(GRID, 0.1, dtype=np.float32), loop=True)
    device.run_to(1500)
    audio.play(1, clicks(300, 0.5), loop=False)  # one-shot: right away
    audio.stop(0)  # not on the grid: right away
    device.run_to(2000)
    out = device.output_signal()
    assert np.all(out[:1500] == np.float32(0.1))
    assert nonzero(out[1500:]) == {0: 0.5}

    free, device = make(grid=None)
    device.run_to(1500)
    free.play(0, clicks(GRID, 0.25), loop=True)
    free.play(1, clicks(GRID, 0.5), loop=True)
    device.run_to(3000)
    assert nonzero(device.output_signal()) == {1500: 0.75, 2500: 0.75}
    assert free.next_boundary_in() is None


def test_clearing_the_grid_lets_new_loops_start_at_once():
    audio, device = make()
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1500)
    audio.set_grid(None)
    audio.play(1, clicks(GRID, 0.5), loop=True)
    device.run_to(2600)
    assert nonzero(device.output_signal()) == {0: 0.25, 1000: 0.25, 1500: 0.5, 2000: 0.25, 2500: 0.5}


# -------------------------------------------------------------- recording


def test_recording_waits_for_the_loop_start_and_begins_exactly_on_it():
    audio, device = make()
    device.voice = coded
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1200)
    assert audio.start_recording()
    assert audio.recording_wait() == (2000 - 1200) / SR
    assert audio.next_boundary_in() == (2000 - 1200) / SR
    device.run_to(2000)
    assert audio.recording_seconds() == 0.0  # nothing before the loop start
    device.run_to(4000)
    assert audio.recording_wait() == 0.0
    data = audio.stop_recording()
    # The last block heard frames 3800..3899.
    assert np.array_equal(data, coded(np.arange(2000, 3900)))


def test_latency_setting_moves_the_cut_by_exactly_that_many_frames():
    # Speaker plus microphone delay of 80 frames (10 ms), set correctly.
    audio, device = make(latency=0.01, delay=80)
    device.voice = coded
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1200)
    audio.start_recording()
    device.run_to(3200)
    data = audio.stop_recording()
    assert data[0] == coded(2000) and np.array_equal(data, coded(np.arange(2000, 2000 + len(data))))

    # The same device with the setting left at 0: the cut is 80 frames early.
    audio, device = make(latency=0.0, delay=80)
    device.voice = coded
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1200)
    audio.start_recording()
    device.run_to(3200)
    data = audio.stop_recording()
    assert np.array_equal(data, coded(np.arange(1920, 1920 + len(data))))


def test_auto_latency_uses_what_portaudio_reports():
    # 5 ms input + 7.5 ms output = 100 frames at 8 kHz.
    audio, device = make(latency=None, delay=100, input_latency=0.005, output_latency=0.0075)
    device.voice = coded
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1200)
    audio.start_recording()
    device.run_to(3300)
    data = audio.stop_recording()
    assert np.array_equal(data, coded(np.arange(2000, 2000 + len(data))))


def test_a_microphone_that_opens_late_gets_silence_in_front():
    audio, device = make()
    device.voice = coded
    device.mic_late_blocks = 3
    audio.play(0, clicks(GRID, 0.25), loop=True)
    device.run_to(1900)
    audio.start_recording()
    device.run_to(2600)
    data = audio.stop_recording()
    # First block that arrived heard 2100..2199; 2000..2099 are missing.
    assert not data[:100].any()
    assert np.array_equal(data[100:], coded(np.arange(2100, 2500)))


def test_without_running_loops_the_recording_starts_at_once():
    audio, device = make()
    device.voice = coded
    device.run_to(1200)
    audio.start_recording()
    assert audio.recording_wait() == 0.0
    device.run_to(1500)
    data = audio.stop_recording()
    assert np.array_equal(data, coded(np.arange(1100, 1400)))  # as without a grid


def test_a_loop_recorded_from_the_speaker_lands_exactly_on_the_original():
    """End to end on the stand-in card: record what the speaker plays, then loop it.

    The new loop must be the original loop sample for sample, and playing
    both must give exactly twice the signal, never a shifted copy.
    """
    rng = np.random.default_rng(7)
    original = (rng.uniform(-0.2, 0.2, GRID)).astype(np.float32)
    audio, device = make(latency=0.01, delay=80, loopback=True)
    audio.play(0, original, loop=True)
    device.run_to(1300)
    audio.start_recording()
    device.run_to(3300)  # a little past the loop end
    recorded = audio.stop_recording()
    loop = fit_to_grid(recorded, GRID, grace_frames(GRID, SR))
    assert len(loop) == GRID
    assert np.array_equal(loop, original)

    device.run_to(3500)
    audio.play(1, loop, loop=True)
    device.run_to(6000)
    out = device.output_signal()
    assert np.array_equal(out[4000:6000], np.tile(2 * original, 2))
