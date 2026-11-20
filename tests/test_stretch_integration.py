"""Stretch into the grid (W3-STRETCH-INT): controller stop on the grid, FakeAudio, no device."""

from __future__ import annotations

import time

import numpy as np
from conftest import FakeAudio, FakeClock, make_settings

from loopstation.audio.samples import load_wav
from loopstation.config import Settings, parse_settings
from loopstation.controller import LIVE_SETTINGS, Controller
from loopstation.store import EventStore

SR = 8000
GRID = 4 * SR  # first recording: 4 s


def build(tmp_path, clock: FakeClock, **overrides):
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def saved(tmp_path, controller: Controller, pad: int) -> np.ndarray:
    return load_wav(tmp_path / "samples" / controller.pad(pad).sample, SR)


def tail_level(data: np.ndarray) -> float:
    return float(np.abs(data[-GRID // 20 :]).max())


def test_five_percent_short_is_stretched_to_exactly_one_loop(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 3.8)
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID
    assert tail_level(data) > 0.01  # content reaches the end, not padded with silence


def test_five_percent_too_long_is_stretched_back_to_one_loop(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 4.2)  # 0.2 s over: past the 0.15 s grace
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID
    assert tail_level(data) > 0.01


def test_a_whole_number_of_loops_is_the_nearest_target(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 7.7)  # 4 % short of two loops
    data = saved(tmp_path, controller, 1)
    assert len(data) == 2 * GRID
    assert tail_level(data) > 0.01


def test_thirty_percent_short_is_padded_like_before(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 2.8)
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID
    assert np.abs(data[int(2.8 * SR) :]).max() == 0.0  # silence after the take
    assert tail_level(data) == 0.0


def test_the_file_on_disk_is_the_stretched_result(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 3.8)
    on_disk = saved(tmp_path, controller, 1)
    played = controller.loop_audio(controller.pad(1).sample)
    assert len(on_disk) == GRID
    assert np.allclose(on_disk, played, atol=1e-4)  # playback does not fit it again


def test_switch_off_is_todays_behaviour(tmp_path, clock):
    controller, _ = build(tmp_path, clock, stretch_to_grid=False)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 3.8)
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID
    assert tail_level(data) == 0.0  # padded with silence


def test_switch_is_live_and_on_by_default(tmp_path, clock):
    assert Settings().stretch_to_grid is True
    assert "stretch_to_grid" in LIVE_SETTINGS
    controller, _ = build(tmp_path, clock)
    controller.apply_settings(Settings(**{**controller.settings.__dict__, "stretch_to_grid": False}))
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 3.8)
    assert tail_level(saved(tmp_path, controller, 1)) == 0.0


def test_the_first_recording_is_never_stretched(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    assert len(saved(tmp_path, controller, 0)) == GRID  # it sets the grid


def test_result_over_the_record_limit_falls_back_to_the_hard_grid(tmp_path, clock):
    controller, _ = build(tmp_path, clock, max_record_seconds=5)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 7.7)  # would stretch to 8 s, the limit allows one loop
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID  # cut to the limit, as before


def test_stretching_ten_seconds_at_stop_is_short(tmp_path, clock):
    controller, _ = build(tmp_path, clock, sample_rate=48000, max_record_seconds=20)
    controller.audio.sample_rate = 48000
    grid = 10 * 48000
    data = (np.random.default_rng(1).standard_normal(int(grid * 0.95)) * 0.1).astype(np.float32)
    start = time.perf_counter()
    result = controller._fit_recording(data, grid, 48000, 20 * 48000)
    assert len(result) == grid
    assert time.perf_counter() - start < 2.0  # about 0.1 s measured; generous for slow CI


def test_settings_file_key(tmp_path):
    assert parse_settings({"stretch_to_grid": False}).stretch_to_grid is False


def test_stop_just_after_a_boundary_is_cut_not_squeezed(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 4.0)
    record(controller, clock, 1, 4.1)  # inside the 0.15 s grace
    raw = FakeAudio(clock)
    raw.start_recording()
    clock.advance(4.1)
    expected = raw.stop_recording()
    data = saved(tmp_path, controller, 1)
    assert len(data) == GRID
    assert np.allclose(data, expected[:GRID], atol=1e-4)  # a cut keeps the take, a squeeze would not
