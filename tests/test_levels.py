"""Level chain on a stand-in sound card: ceiling, volume, input trim, clip memory, settings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import FakeAudio, FakeSoundDevice, make_settings

from loopstation.audio.dynamics import block_peak, db_to_gain
from loopstation.audio.effects import beep
from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.config import ConfigError, Settings, load_settings, parse_settings
from loopstation.controller import CLIP_HOLD_SECONDS, Controller
from loopstation.store import EventStore

SR = 8000
CEILING_DB = -6.0
CEILING = db_to_gain(CEILING_DB)


def make(**kwargs):
    device = FakeSoundDevice(block=100)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=0.0, sd=device, clock=lambda: 0.0, **kwargs)
    audio.set_grid(None)
    return audio, device


def tone(hz: float, amplitude: float = 1.0, frames: int = SR) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / SR
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def record(audio: SoundDeviceAudio, device: FakeSoundDevice, voice, blocks: int = 40) -> np.ndarray:
    device.voice = voice
    assert audio.start_recording()
    device.step(blocks)
    data = audio.stop_recording()
    assert data is not None
    return data


# ------------------------------------------------------------ output side


def test_output_never_passes_the_ceiling_with_many_loops_and_beeps():
    audio, device = make(volume=1.0, ceiling_db=CEILING_DB)
    for pad in range(9):
        audio.play(pad, tone(110.0 * (pad + 1), 1.0), loop=True)
    device.step(20)
    for _ in range(5):  # start and stop beeps on top of everything, at full scale
        audio.play_effect(beep(880.0, 0.12, SR, volume=1.0))
        device.step(4)
    device.step(20)
    out = device.output_signal()
    assert block_peak(out) <= CEILING + 1e-6
    assert block_peak(out) > CEILING * 0.9  # it limits, it does not mute


def test_ceiling_can_be_lowered_while_playing():
    audio, device = make(volume=1.0, ceiling_db=0.0)
    audio.play(0, tone(200.0, 1.0), loop=True)
    device.step(10)
    audio.set_ceiling_db(-12.0)
    device.step(10)
    after = device.output_signal()[100 * 10:]
    # The limiter lets the gain fall within a block; a short moment of
    # transition, then everything is under the new ceiling.
    assert block_peak(after) <= db_to_gain(-12.0) + 1e-6


def test_volume_zero_is_silence():
    audio, device = make(volume=0.0, ceiling_db=0.0)
    audio.play(0, tone(200.0, 1.0), loop=True)
    audio.play_effect(beep(880.0, 0.12, SR, volume=1.0))
    device.step(30)
    assert not device.output_signal().any()


def test_volume_change_is_a_ramp_not_a_jump():
    audio, device = make(volume=1.0, ceiling_db=0.0)
    audio.play(0, np.full(SR, 0.5, dtype=np.float32), loop=True)
    device.step(5)
    audio.set_volume(0.0)
    device.step(10)
    audio.set_volume(1.0)
    device.step(10)
    out = device.output_signal()
    steps = np.abs(np.diff(out))
    assert steps.max() < 0.01  # a jump would be 0.5
    assert out[100 * 5 + 1000 - 1] == 0.0  # arrived at silence after the ramp
    assert out[-1] == pytest.approx(0.5)  # and back to full


def test_volume_scales_the_output():
    audio, device = make(volume=0.5, ceiling_db=0.0)
    audio.play(0, np.full(300, 0.4, dtype=np.float32), loop=False)
    device.step(3)
    assert np.allclose(device.output_signal(), 0.2)


def test_pad_gain_scales_only_that_pad_and_ramps():
    audio, device = make(volume=1.0, ceiling_db=0.0)
    audio.play(0, np.full(SR, 0.5, dtype=np.float32), loop=True)
    audio.play(1, np.full(SR, 0.5, dtype=np.float32), loop=True)
    device.step(5)
    before = block_peak(device.output_signal()[-200:])
    audio.set_pad_gain(0, 0.0)
    device.step(20)
    # After the ramp, pad 0 is silent and pad 1 still contributes 0.5.
    settled = device.output_signal()[-500:]
    assert before == pytest.approx(1.0, abs=0.02)
    assert block_peak(settled) == pytest.approx(0.5, abs=0.02)
    assert settled[-1] == pytest.approx(0.5, abs=0.02)


def test_pad_boost_soft_limits_instead_of_hard_clip():
    audio, device = make(volume=1.0, ceiling_db=0.0)
    audio.set_pad_gain(0, db_to_gain(18.0))
    audio.play(0, np.full(SR, 0.8, dtype=np.float32), loop=True)
    device.step(30)
    out = device.output_signal()
    assert block_peak(out) <= 1.0 + 1e-5
    assert audio.poll_pad_clipping(0)


def test_output_default_is_neutral():
    audio, device = make()
    audio.play(0, np.full(300, 0.6, dtype=np.float32), loop=False)
    device.step(3)
    assert np.array_equal(device.output_signal(), np.full(300, 0.6, dtype=np.float32))


def test_output_path_does_not_allocate_new_buffers_per_block():
    audio, device = make(volume=0.7, ceiling_db=CEILING_DB)
    audio.play(0, tone(200.0, 1.0), loop=True)
    device.step(3)
    mix, gains, ramp = audio._mix, audio._gains, audio._ramp
    audio.set_volume(0.2)
    device.step(20)
    assert audio._mix is mix and audio._gains is gains and audio._ramp is ramp


def test_larger_block_than_the_work_buffers_still_works():
    device = FakeSoundDevice(block=10000)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=0.0, sd=device, clock=lambda: 0.0,
                             volume=1.0, ceiling_db=CEILING_DB)
    audio.play(0, tone(200.0, 1.0, 20000), loop=False)
    device.step(2)
    assert block_peak(device.output_signal()) <= CEILING + 1e-6


# ------------------------------------------------------------- input side


def test_input_trim_scales_the_recording():
    audio, device = make(input_gain_db=-6.0)
    data = record(audio, device, lambda frames: np.full(len(frames), 0.2, dtype=np.float32), blocks=5)
    assert np.allclose(data, 0.2 * db_to_gain(-6.0), atol=1e-6)
    audio.set_input_gain_db(6.0)
    data = record(audio, device, lambda frames: np.full(len(frames), 0.2, dtype=np.float32), blocks=5)
    assert np.allclose(data, 0.2 * db_to_gain(6.0), atol=1e-6)


def test_clip_detection_fires_at_full_scale_only():
    audio, device = make()
    record(audio, device, lambda frames: np.full(len(frames), 0.95, dtype=np.float32), blocks=5)
    assert audio.poll_input_level()[1] == 0
    record(audio, device, lambda frames: np.full(len(frames), 1.0, dtype=np.float32), blocks=3)
    peak, clips = audio.poll_input_level()
    assert clips == 3 and peak == pytest.approx(1.0)
    record(audio, device, lambda frames: np.full(len(frames), -1.0, dtype=np.float32), blocks=2)
    assert audio.poll_input_level()[1] == 5  # a running total, also for the negative side


def test_clip_detection_sees_a_clipping_converter_behind_a_negative_trim():
    audio, device = make(input_gain_db=-12.0)
    data = record(audio, device, lambda frames: np.full(len(frames), 1.0, dtype=np.float32), blocks=2)
    assert audio.poll_input_level()[1] == 2  # the converter clipped, the trim hides it only in the file
    assert data.max() == pytest.approx(db_to_gain(-12.0))


def test_trim_that_pushes_into_full_scale_counts_as_clipping_and_is_softened():
    audio, device = make(input_gain_db=12.0)
    data = record(audio, device, lambda frames: np.full(len(frames), 0.5, dtype=np.float32), blocks=3)
    assert audio.poll_input_level()[1] == 3
    assert block_peak(data) < 1.0  # soft clip instead of a hard knee at 1.0
    assert block_peak(data) > 0.7


def test_soft_clip_rounds_loud_peaks_of_the_recording():
    audio, device = make()
    data = record(audio, device, lambda frames: np.full(len(frames), 0.95, dtype=np.float32), blocks=3)
    assert 0.7 < data.max() < 0.95


def test_peak_is_reported_once_and_starts_over():
    audio, device = make()
    record(audio, device, lambda frames: np.full(len(frames), 0.3, dtype=np.float32), blocks=3)
    assert audio.poll_input_level()[0] == pytest.approx(0.3)
    assert audio.poll_input_level()[0] == 0.0


def test_auto_gain_is_off_by_default_and_lifts_a_quiet_take_slowly_when_on():
    quiet = lambda frames: (0.02 * np.sin(np.asarray(frames) * 0.2)).astype(np.float32)  # noqa: E731
    audio, device = make()
    data = record(audio, device, quiet, blocks=160)
    assert block_peak(data[-800:]) == pytest.approx(block_peak(data[:800]), rel=0.05)

    audio, device = make(auto_gain=True)
    data = record(audio, device, quiet, blocks=160)
    assert block_peak(data[:800]) == pytest.approx(0.02, rel=0.05)  # starts at the trim
    assert block_peak(data[-800:]) > block_peak(data[:800]) * 1.05  # creeps up
    assert block_peak(data[-800:]) < block_peak(data[:800]) * 4  # and only slowly


def test_auto_gain_lowers_instead_of_raising_when_the_input_clips():
    audio, device = make(auto_gain=True)
    loud = lambda frames: np.where(np.asarray(frames) % 2 == 0, 1.0, -1.0).astype(np.float32)  # noqa: E731
    data = record(audio, device, loud, blocks=60)
    assert block_peak(data[-100:]) <= block_peak(data[:100]) + 1e-6
    assert block_peak(data[-100:]) < block_peak(data[:100])


def test_auto_gain_starts_every_recording_at_zero():
    audio, device = make(auto_gain=True)
    quiet = lambda frames: np.full(len(frames), 0.02, dtype=np.float32)  # noqa: E731
    record(audio, device, quiet, blocks=100)
    again = record(audio, device, quiet, blocks=2)
    assert again[:100].max() == pytest.approx(0.02, rel=1e-3)


# ------------------------------------------------------------- controller


@pytest.fixture
def controller(tmp_path, clock):
    settings = make_settings(tmp_path, volume=0.4, max_level_db=-6.0, input_gain_db=3.0, auto_gain=True)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    ctl = Controller(store, audio, settings, clock=clock)
    yield ctl
    store.close()


def test_controller_hands_the_start_levels_to_the_engine(controller):
    audio = controller.audio
    assert audio.ceiling_db == -6.0 and audio.volume == 0.4
    assert audio.input_gain_db == 3.0 and audio.auto_gain is True
    assert controller.volume == 0.4 and controller.volume_limit == pytest.approx(CEILING)


def test_start_volume_above_the_ceiling_is_pulled_down(tmp_path, clock):
    settings = make_settings(tmp_path, volume=0.9, max_level_db=-6.0)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    ctl = Controller(store, FakeAudio(clock), settings, clock=clock)
    assert ctl.volume == pytest.approx(CEILING)
    assert ctl.audio.volume == pytest.approx(CEILING)
    store.close()


def test_volume_is_clamped_between_silence_and_the_ceiling(controller):
    assert controller.set_volume(0.0) == 0.0 and controller.audio.volume == 0.0
    assert controller.set_volume(7.0) == pytest.approx(CEILING)
    assert controller.audio.volume == pytest.approx(CEILING)
    assert controller.set_volume(-1.0) == 0.0


def test_lowering_the_ceiling_pulls_the_volume_down_with_it(controller):
    controller.set_volume(CEILING)
    seen = []
    controller.add_listener(lambda: seen.append(controller.volume))
    controller.set_max_level_db(-20.0)
    assert controller.volume == pytest.approx(db_to_gain(-20.0))
    assert controller.audio.volume == pytest.approx(db_to_gain(-20.0))
    assert controller.audio.ceiling_db == -20.0
    assert seen and all(v <= db_to_gain(-20.0) + 1e-9 for v in seen)
    # Raising it again does not push the volume up by itself.
    controller.set_max_level_db(0.0)
    assert controller.volume == pytest.approx(db_to_gain(-20.0))
    assert controller.set_volume(1.0) == 1.0


def test_ceiling_range_is_limited(controller):
    assert controller.set_max_level_db(-99) == -30.0
    assert controller.set_max_level_db(5) == 0.0


def test_trim_auto_gain_and_meter_switches_reach_the_engine(controller):
    controller.set_input_gain_db(-60)
    controller.set_auto_gain(False)
    controller.set_peak_meter(True)
    assert controller.audio.input_gain_db == -24.0 and controller.input_gain_db == -24.0
    assert controller.audio.auto_gain is False and controller.auto_gain is False
    assert controller.peak_meter is True


def test_clip_is_remembered_for_a_moment_while_recording(controller, clock):
    audio = controller.audio
    controller.press(0)  # start recording
    assert controller.recording_pad == 0 and not controller.input_clipping()
    audio.input_peak = 0.4
    controller.tick()
    assert controller.input_peak() == 0.4 and not controller.input_clipping()
    audio.clips = 2
    audio.input_peak = 1.3
    controller.tick()
    assert controller.input_clipping() and controller.clip_count == 2
    clock.advance(CLIP_HOLD_SECONDS - 0.1)
    assert controller.input_clipping()
    clock.advance(0.2)
    assert not controller.input_clipping()
    assert controller.clip_count == 2  # the parents still see that it happened
    audio.clips = 3
    controller.tick()
    assert controller.input_clipping() and controller.clip_count == 3


def test_clips_before_a_recording_do_not_count_for_it(controller, clock):
    controller.audio.clips = 5  # from an earlier take
    controller.press(1)
    controller.tick()
    assert not controller.input_clipping() and controller.clip_count == 0


def test_the_sign_goes_out_when_the_recording_stops(controller, clock):
    controller.press(0)
    controller.audio.clips = 1
    controller.tick()
    assert controller.input_clipping()
    clock.advance(1)
    controller.press(0)  # stop
    assert controller.recording_pad is None and not controller.input_clipping()


# ----------------------------------------------------------------- config


def test_level_settings_defaults_and_values():
    settings = Settings()
    assert (settings.volume, settings.max_level_db, settings.input_gain_db) == (0.5, -6.0, 0.0)
    assert settings.auto_gain is False and settings.peak_meter is True
    parsed = parse_settings({"volume": 1, "max_level_db": -12, "input_gain_db": 4.5,
                             "auto_gain": True, "peak_meter": True})
    assert (parsed.volume, parsed.max_level_db, parsed.input_gain_db) == (1.0, -12.0, 4.5)
    assert parsed.auto_gain is True and parsed.peak_meter is True


@pytest.mark.parametrize("raw", [{"volume": 1.5}, {"volume": -0.1}, {"max_level_db": 1},
                                 {"max_level_db": -31}, {"input_gain_db": 25}, {"input_gain_db": "laut"},
                                 {"auto_gain": "an"}, {"peak_meter": 1}])
def test_invalid_level_values_name_the_key(raw):
    with pytest.raises(ConfigError, match=next(iter(raw))):
        parse_settings(raw, "settings.toml")


def test_shipped_file_documents_every_level_key():
    path = Path(__file__).parent.parent / "settings.toml"
    shipped = load_settings(path)
    assert shipped == Settings()
    text = path.read_text(encoding="utf-8")
    for key in ("volume", "max_level_db", "input_gain_db", "auto_gain", "peak_meter"):
        assert f"\n{key} = " in text
