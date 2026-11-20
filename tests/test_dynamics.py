"""Pure level functions: ceiling and limiter, soft clip, auto gain."""

from __future__ import annotations

import numpy as np
import pytest

from loopstation.audio.dynamics import (
    AUTO_GAIN_RANGE_DB,
    PeakLimiter,
    auto_gain_step,
    block_peak,
    db_to_gain,
    gain_to_db,
    ramp_gain,
    soft_clip,
)

SR = 8000
TOLERANCE = 1e-6


def sine(frames: int, amplitude: float = 1.0, hz: float = 220.0, phase: float = 0.0) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / SR
    return (amplitude * np.sin(2 * np.pi * hz * t + phase)).astype(np.float32)


def limit(
    signal: np.ndarray, ceiling: float, block: int = 100, limiter: PeakLimiter | None = None
) -> np.ndarray:
    limiter = limiter or PeakLimiter(SR)
    out = signal.copy()
    for start in range(0, len(out), block):
        limiter.process(out[start:start + block], ceiling)
    return out


def test_db_conversions_round_trip():
    assert db_to_gain(0) == pytest.approx(1.0)
    assert db_to_gain(-6) == pytest.approx(0.501187, rel=1e-5)
    assert gain_to_db(db_to_gain(-12.5)) == pytest.approx(-12.5)
    assert gain_to_db(0.0) == float("-inf")
    assert block_peak(np.array([0.2, -0.7, 0.4], dtype=np.float32)) == pytest.approx(0.7)
    assert block_peak(np.zeros(0, dtype=np.float32)) == 0.0


@pytest.mark.parametrize("loops", [1, 2, 3, 5, 8, 12])
@pytest.mark.parametrize("block", [1, 37, 128, 480, 4096])
def test_ceiling_holds_for_n_full_scale_loops(loops, block):
    ceiling = db_to_gain(-6)
    # N loops at full scale with different pitch and phase, summed.
    mix = sum(sine(SR, 1.0, hz=110.0 * (i + 1), phase=i) for i in range(loops))
    out = limit(mix.astype(np.float32), ceiling, block)
    assert block_peak(out) <= ceiling + TOLERANCE


def test_ceiling_holds_for_a_square_wave_burst_and_dc():
    ceiling = 0.25
    burst = np.zeros(2000, dtype=np.float32)
    burst[500:1500] = np.where(np.arange(1000) % 20 < 10, 3.0, -3.0)
    assert block_peak(limit(burst, ceiling, 64)) <= ceiling + TOLERANCE
    assert block_peak(limit(np.full(3000, 5.0, dtype=np.float32), ceiling, 50)) <= ceiling + TOLERANCE


def test_quiet_signal_passes_unchanged():
    quiet = sine(2000, 0.2)
    assert np.array_equal(limit(quiet, 0.5), quiet)


def test_limiter_has_no_hard_edges():
    """A swell that grows through the ceiling is bent, not cut: no sample step much
    larger than the biggest step of the untouched swell."""
    ceiling = 0.5
    frames = 4000
    swell = (sine(frames, 1.0, hz=180.0) * np.linspace(0.2, 2.0, frames, dtype=np.float32)).astype(np.float32)
    out = limit(swell, ceiling, block=4000)  # one block: look-ahead sees the whole swell
    assert block_peak(out) <= ceiling + TOLERANCE
    free = np.abs(np.diff(swell)).max()
    assert np.abs(np.diff(out)).max() <= free * 1.05
    # The same in small blocks stays well below what a hard clip does at the knee.
    small = limit(swell, ceiling, block=64)
    hard = np.clip(swell, -ceiling, ceiling)
    assert np.abs(np.diff(small)).max() <= free * 1.5
    assert np.abs(np.diff(small, n=2)).max() <= np.abs(np.diff(hard, n=2)).max()


def test_gain_comes_back_slowly_after_a_peak():
    limiter = PeakLimiter(SR, release=0.25)
    loud = np.full(100, 2.0, dtype=np.float32)
    limiter.process(loud, 1.0)
    low = limiter.gain
    assert low == pytest.approx(0.5, abs=0.01)
    quiet = np.full(100, 0.01, dtype=np.float32)
    limiter.process(quiet, 1.0)
    # 100 samples of 250 ms * 8 kHz = 2000: only a small step back up.
    assert low < limiter.gain < low + 0.1
    for _ in range(40):
        limiter.process(np.full(100, 0.01, dtype=np.float32), 1.0)
    assert limiter.gain == 1.0


def test_limiter_grows_its_buffers_for_a_larger_block():
    limiter = PeakLimiter(SR, capacity=16)
    out = limit(sine(1000, 1.5), 0.5, block=1000, limiter=limiter)
    assert block_peak(out) <= 0.5 + TOLERANCE


def test_limiter_works_on_a_slice_without_copy():
    buffer = np.full(64, 3.0, dtype=np.float32)
    PeakLimiter(SR).process(buffer[:32], 1.0)
    assert buffer[:32].max() <= 1.0 + TOLERANCE
    assert (buffer[32:] == 3.0).all()


def test_ramp_gain_moves_by_at_most_the_step():
    assert ramp_gain(0.0, 1.0, 100, 0.001) == pytest.approx(0.1)
    assert ramp_gain(1.0, 0.0, 100, 0.001) == pytest.approx(0.9)
    assert ramp_gain(0.5, 0.52, 100, 0.001) == pytest.approx(0.52)
    assert ramp_gain(0.5, 0.5, 100, 0.001) == 0.5


def test_soft_clip_is_monotonic_bounded_and_transparent_below_the_knee():
    x = np.linspace(-6, 6, 4001, dtype=np.float32)
    y = soft_clip(x.copy(), knee=0.7)
    assert (np.diff(y) >= 0).all()
    assert np.abs(y).max() <= 1.0
    assert np.abs(y[np.abs(x) <= 1.5]).max() < 1.0
    inside = np.abs(x) <= 0.7
    assert np.array_equal(y[inside], x[inside])
    # Odd symmetry and no jump at the knee.
    assert np.allclose(y, -y[::-1], atol=1e-6)
    assert np.abs(np.diff(y)).max() <= np.abs(np.diff(x)).max() * 1.001


def test_auto_gain_never_raises_the_gain_while_clipping():
    for current in (-12.0, -3.0, 0.0, 6.0, 12.0):
        for rms_db in (-60.0, -40.0, -30.0, -20.0, -10.0, -3.0):
            new = auto_gain_step(current, rms_db, peak=1.0, clipped=True, seconds=0.5)
            assert new <= current
    assert auto_gain_step(0.0, -30.0, 1.0, True, 0.5) < 0.0


def test_auto_gain_is_slow_bounded_and_ignores_silence():
    # Quiet take: rises, but only slowly (1.5 dB per second at most).
    new = auto_gain_step(0.0, -40.0, peak=0.02, clipped=False, seconds=0.1)
    assert 0.0 < new <= 0.15 + 1e-9
    # Silence (noise floor) changes nothing.
    assert auto_gain_step(3.0, -70.0, 0.001, False, 0.1) == 3.0
    # A loud take is pulled down, faster than it rises.
    assert auto_gain_step(0.0, -6.0, 0.5, False, 0.1) < 0.0
    # Never beyond the range, however long it runs.
    gain = 0.0
    for _ in range(10_000):
        gain = auto_gain_step(gain, -50.0, 0.005, False, 0.1)
    assert gain == pytest.approx(AUTO_GAIN_RANGE_DB)
    # It does not lift a block whose peak is already near the soft clipper.
    assert auto_gain_step(0.0, -30.0, peak=0.75, clipped=False, seconds=1.0) == 0.0
