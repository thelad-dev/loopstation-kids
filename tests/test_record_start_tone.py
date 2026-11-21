"""The start beep and the metronome tick never land on a recording.

The stand-in sound card puts the speaker next to the microphone (``loopback``),
so everything the engine plays reaches the take, as with real speakers. The
engine begins the take only after the sounds it still plays have ended; the
loop grid, the latency compensation and the first onset stay exact.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import soundfile
from conftest import FakeAudio, FakeClock, FakeSoundDevice, clap_signal, make_settings

from loopstation.audio.effects import start_beep
from loopstation.audio.sounddevice_backend import RECORD_GUARD_SECONDS, SoundDeviceAudio
from loopstation.config import SETTING_COMMENTS, Settings, parse_settings
from loopstation.controller import LIVE_SETTINGS, Controller
from loopstation.store import EventStore

SR = 8000
BLOCK = 100
DELAY = 80  # speaker to microphone: 10 ms
GUARD = int(round(RECORD_GUARD_SECONDS * SR))
BEEP = len(start_beep(SR))


def coded(frames: np.ndarray) -> np.ndarray:
    """A microphone signal that tells which frame it was heard at."""
    return (np.asarray(frames, dtype=np.float64) * 1e-5).astype(np.float32)


def engine(grid: int | None = None, delay: int = DELAY):
    device = FakeSoundDevice(block=BLOCK, delay=delay, loopback=True)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=delay / SR, sd=device, clock=lambda: 0.0)
    audio.set_grid(grid)
    return audio, device


class Rig:
    """Controller on the real engine with the speaker next to the microphone."""

    def __init__(self, tmp_path, **overrides) -> None:
        self.clock = FakeClock()
        self.device = FakeSoundDevice(block=BLOCK, delay=DELAY, loopback=True)
        self.audio = SoundDeviceAudio(
            SR, 10, latency_seconds=DELAY / SR, sd=self.device, clock=lambda: 0.0)
        values = {"volume": 1.0, "max_level_db": 0.0, "stretch_engine": "simple"}
        values.update(overrides)
        self.settings = make_settings(tmp_path, **values)
        self.store = EventStore(self.settings.log_dir, self.settings.pad_count, clock=self.clock)
        self.controller = Controller(self.store, self.audio, self.settings, clock=self.clock)
        self.controller.startup()
        self.tmp = tmp_path

    def say(self, signal: np.ndarray | None) -> None:
        """The child: ``signal`` begins at the frame the card has reached now."""
        if signal is None:
            self.device.voice = None
            return
        base = self.device.frame

        def voice(frames: np.ndarray) -> np.ndarray:
            idx = frames - base
            out = np.zeros(len(frames), dtype=np.float32)
            ok = (idx >= 0) & (idx < len(signal))
            out[ok] = signal[idx[ok]]
            return out

        self.device.voice = voice

    def wav(self, pad: int) -> np.ndarray:
        return soundfile.read(str(self.tmp / "samples" / self.controller.pad(pad).sample), dtype="float32")[0]

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def rig(tmp_path):
    made: list[Rig] = []

    def make(**overrides) -> Rig:
        r = Rig(tmp_path / f"r{len(made)}", **overrides)
        made.append(r)
        return r

    yield make
    for r in made:
        r.close()


# ---------------------------------------------------------------- the take is free of the beep


@pytest.mark.parametrize("tone", [True, False])
def test_a_silent_first_take_stays_silent_whatever_the_start_tone(rig, tone):
    r = rig(record_start_tone=tone)
    r.controller.press(0)
    r.device.step(40)
    heard = np.abs(r.device.output_signal()).max()
    r.controller.press(0)
    data = r.wav(0)
    assert len(data) > 0 and not data.any()
    # The beep sounds on the speaker (or not, when it is off), it just is not on the take.
    assert float(heard) == pytest.approx(0.3 if tone else 0.0, abs=0.01)


def test_the_first_kept_frame_is_the_first_one_after_the_beep_and_the_guard():
    audio, device = engine()
    device.voice = coded
    device.run_to(1200)
    assert audio.start_recording(cue=start_beep(SR))
    assert audio.recording_wait() == 0.0 and not audio.recording_aligned()
    device.run_to(4000)
    data = audio.stop_recording()
    # The beep sounds from frame 1200 to 1200 + BEEP; the take heard 1200 + BEEP + GUARD on.
    first = 1200 + BEEP + GUARD
    assert np.array_equal(data, coded(np.arange(first, first + len(data))))
    assert not np.abs(data - coded(np.arange(first, first + len(data)))).any()


def test_without_a_cue_the_take_begins_at_once_as_before():
    audio, device = engine()
    device.voice = coded
    device.run_to(1200)
    audio.start_recording()
    device.run_to(1500)
    data = audio.stop_recording()
    # The first block heard the frames just before the start, as it always did.
    assert np.array_equal(data, coded(np.arange(1020, 1020 + len(data))))


def test_a_loop_start_inside_the_beep_moves_the_take_to_the_next_loop_start():
    grid = 2000
    audio, device = engine(grid)
    device.voice = coded
    audio.play(0, np.zeros(grid, dtype=np.float32), loop=True)  # anchors the grid at frame 0
    device.run_to(1900)  # the loop start at 2000 is inside the beep
    audio.start_recording(cue=start_beep(SR))
    assert audio.recording_aligned()
    assert audio.recording_wait() == (4000 - 1900) / SR
    device.run_to(6000)
    data = audio.stop_recording()
    assert np.array_equal(data, coded(np.arange(4000, 4000 + len(data))))


def test_a_loop_start_after_the_beep_is_met_exactly():
    grid = 2000
    audio, device = engine(grid)
    device.voice = coded
    audio.play(0, np.zeros(grid, dtype=np.float32), loop=True)
    device.run_to(500)  # beep and guard are over before 2000
    audio.start_recording(cue=start_beep(SR))
    assert audio.recording_wait() == (2000 - 500) / SR
    device.run_to(4000)
    data = audio.stop_recording()
    assert np.array_equal(data, coded(np.arange(2000, 2000 + len(data))))


def test_the_stop_beep_of_the_take_before_is_not_on_the_next_take():
    audio, device = engine()
    device.voice = coded
    audio.play_effect(start_beep(SR))  # still sounding, like a stop beep a moment ago
    device.run_to(300)
    audio.start_recording()
    device.run_to(2000)
    data = audio.stop_recording()
    first = BEEP + GUARD
    assert np.array_equal(data, coded(np.arange(first, first + len(data))))


def test_the_beep_is_dropped_by_the_latency_setting_not_by_luck():
    # A card that reports 100 frames of delay and a setting of 100: still exact.
    audio, device = engine(delay=100)
    device.voice = coded
    device.run_to(1200)
    audio.start_recording(cue=start_beep(SR))
    device.run_to(4000)
    data = audio.stop_recording()
    first = 1200 + BEEP + GUARD
    assert np.array_equal(data, coded(np.arange(first, first + len(data))))


# ------------------------------------------------------------------------- the metronome tick


def ticking_rig(rig):
    """A session on a 120 BPM grid (a tick every 0.5 s) with the metronome on and no beeps."""
    r = rig(metronome_tone=True, metronome_level_db=-6.0, sound_effects=False)
    r.controller.press(0)
    run(r, 40)
    r.controller.press(0)  # the first take: one second, it makes the bar
    r.controller.set_parent_grid(120, "4/4")
    return r


def run(r: Rig, blocks: int) -> None:
    """Let the card and the controller's clock run together, with the GUI tick in between."""
    for _ in range(blocks):
        r.device.step()
        r.clock.advance(BLOCK / SR)
        r.controller.tick()


def test_the_metronome_ticks_on_the_speaker_between_takes(rig):
    r = ticking_rig(rig)
    start = r.device.frame
    run(r, 80)
    assert np.abs(r.device.output_signal()[start:]).max() > 0.4  # -6 dB(FS)


def test_the_metronome_tick_is_not_on_the_take(rig):
    r = ticking_rig(rig)
    run(r, 10)  # ticks are on their way when the child presses
    pressed = r.device.frame
    r.controller.press(1)
    run(r, 120)  # three beats' worth of ticks are due while recording
    r.controller.press(1)
    assert len(r.wav(1)) > 0 and not r.wav(1).any()
    # The speaker is quiet from the tick that was on its way until the take is over.
    assert not r.device.output_signal()[pressed + 2 * BLOCK:].any()


# ----------------------------------------------------------- the first onset and the grid stay exact


def test_the_first_onsets_are_the_same_with_and_without_the_start_tone(rig):
    claps = [0.5, 1.0, 1.5, 2.0]
    takes = []
    for tone in (True, False):
        r = rig(auto_grid=True, record_start_tone=tone)
        r.say(clap_signal(5 * SR, SR, claps))
        r.controller.press(0)
        r.device.step(round(2.6 * SR / BLOCK))
        r.controller.press(0)
        takes.append(r.wav(0))
    with_tone, without = takes
    assert len(with_tone) == len(without)
    assert np.array_equal(with_tone, without)
    assert np.abs(with_tone).max() > 0.5  # the claps are in the file


def test_claps_sit_sample_exact_where_they_were_made_after_the_beep(rig):
    r = rig(auto_grid=False, loop_sync=False, record_start_tone=True)
    r.say(clap_signal(4 * SR, SR, [0.6, 1.2]))  # the child claps 0.6 s and 1.2 s after the press
    r.controller.press(0)
    r.device.step(round(2.0 * SR / BLOCK))
    r.controller.press(0)
    data = r.wav(0)
    first = BEEP + GUARD  # the take begins this many frames after the press
    onsets = np.flatnonzero(data)
    # clap_signal's burst is silent in its first frame and loud from the second.
    assert onsets[0] == int(round(0.6 * SR)) + 1 - first
    assert onsets[onsets > SR][0] == int(round(1.2 * SR)) + 1 - first


# --------------------------------------------------------------------------------- the setting


def test_the_start_tone_is_on_by_default_and_switchable():
    assert Settings().record_start_tone is True
    assert parse_settings({}).record_start_tone is True
    assert parse_settings({"record_start_tone": False}).record_start_tone is False
    with pytest.raises(Exception, match="record_start_tone"):
        parse_settings({"record_start_tone": "ja"})
    assert "record_start_tone" in LIVE_SETTINGS and "record_start_tone" in SETTING_COMMENTS


def test_the_controller_hands_the_beep_to_the_engine_only_while_it_is_on(tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    controller.press(0)
    assert len(audio.effects) == 1  # the start beep, as the cue of the recording
    clock.advance(1)
    controller.press(0)
    assert len(audio.effects) == 2  # and the stop beep
    audio.effects.clear()
    controller.apply_settings(replace(controller.settings, record_start_tone=False))  # live
    controller.press(1)
    assert audio.effects == []
    clock.advance(1)
    controller.press(1)
    assert len(audio.effects) == 1  # the stop beep stays
    audio.effects.clear()
    controller.apply_settings(replace(controller.settings, record_start_tone=True, sound_effects=False))
    controller.press(2)
    clock.advance(1)
    controller.press(2)
    assert audio.effects == []  # sound_effects off silences both
    store.close()
