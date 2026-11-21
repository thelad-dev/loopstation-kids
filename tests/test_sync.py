"""Loop grid arithmetic: exact frame counts, no audio device."""

from __future__ import annotations

import numpy as np
import pytest

from loopstation.audio.sync import (
    fit_length,
    fit_to_grid,
    grace_frames,
    max_grid_frames,
    next_boundary,
    seam_fade_frames,
    soften_seam,
)


def test_next_boundary():
    assert next_boundary(0, 0, 1000) == 0
    assert next_boundary(1, 0, 1000) == 1000
    assert next_boundary(999, 0, 1000) == 1000
    assert next_boundary(1000, 0, 1000) == 1000
    assert next_boundary(1001, 0, 1000) == 2000
    # The grid is anchored where the first loop started.
    assert next_boundary(1300, 250, 1000) == 2250
    assert next_boundary(100, 250, 1000) == 250
    with pytest.raises(ValueError):
        next_boundary(5, 0, 0)


def test_shorter_than_a_loop_becomes_one_loop():
    assert fit_length(1, 1000) == 1000
    assert fit_length(999, 1000) == 1000
    assert fit_length(1000, 1000) == 1000


def test_longer_becomes_the_next_multiple():
    assert fit_length(1001, 1000) == 2000
    assert fit_length(2500, 1000) == 3000


def test_a_stop_just_after_a_boundary_counts_as_that_boundary():
    assert fit_length(1100, 1000, grace=125) == 1000
    assert fit_length(1125, 1000, grace=125) == 1000
    assert fit_length(1126, 1000, grace=125) == 2000
    # Never less than one loop.
    assert fit_length(50, 1000, grace=125) == 1000


def test_grace_is_short_and_bounded_by_the_loop():
    assert grace_frames(8000, 8000) == 1000  # 1/8 of a 1 s loop
    assert grace_frames(80000, 8000) == 1200  # at most 150 ms
    assert grace_frames(7, 8000) == 0


def test_limit_rounds_down_to_whole_loops():
    assert max_grid_frames(1000, 3500) == 3000
    assert max_grid_frames(1000, 500) == 1000  # at least one loop
    assert fit_length(9000, 1000, limit=3500) == 3000
    assert fit_length(900, 1000, limit=500) == 1000


def test_fit_to_grid_pads_with_silence_and_cuts():
    data = np.arange(1, 1201, dtype=np.float32)
    padded = fit_to_grid(data[:300], 1000)
    assert len(padded) == 1000 and padded.dtype == np.float32
    assert np.array_equal(padded[:300], data[:300]) and not padded[300:].any()

    cut = fit_to_grid(data, 1000, grace=250)
    assert len(cut) == 1000 and np.array_equal(cut, data[:1000])

    exact = data[:1000]
    assert fit_to_grid(exact, 1000) is exact


# ------------------------------------------------------------ seam fade


@pytest.mark.parametrize(
    ("length_s", "expected_ms"),
    [(8.0, 25.0), (1.0, 20.0), (0.5, 10.0), (0.15, 3.0), (0.05, 2.0), (0.01, 1.0)],
)
def test_seam_fade_length_is_proportional_with_hard_limits(length_s, expected_ms):
    sr = 44100
    frames = seam_fade_frames(round(length_s * sr), sr)
    assert abs(frames - expected_ms / 1000 * sr) <= 1
    assert frames <= round(length_s * sr) * 0.10  # never over 10 %


def test_seam_fade_of_a_tiny_loop_never_eats_it():
    assert seam_fade_frames(0, 8000) == 0
    assert seam_fade_frames(5, 8000) == 0
    assert seam_fade_frames(100, 8000) == 10


def test_softened_seam_keeps_length_and_the_middle_and_zeroes_the_ends():
    data = np.full(8000, 0.5, dtype=np.float32)
    out = soften_seam(data, 8000)
    n = seam_fade_frames(len(data), 8000)
    assert len(out) == len(data) and n > 2
    assert out[0] == 0.0 and out[-1] == 0.0
    assert np.array_equal(out[n:-n], data[n:-n])
    assert np.all(np.diff(out[:n]) >= 0) and np.all(np.diff(out[-n:]) <= 0)
    assert np.all(data == 0.5)  # the input is not touched


def clap_loop(length: int, sr: int, attack: int = 0) -> np.ndarray:
    """A loop whose first beat attacks on frame ``attack`` and whose end still rings on.

    The onset shift puts the first attack of the take on frame 0; a real clap
    starts a few ms later (frame 267 in a recorded set).
    """
    k = np.arange(length - attack)
    rng = np.random.default_rng(7)
    tone = 0.6 * np.sin(2 * np.pi * 1000 * k / sr) + 0.4 * rng.uniform(-1, 1, len(k))
    clap = np.exp(-k / (0.006 * sr)) * tone
    # Still sounding where the end meets the start.
    out = 0.3 * np.sin(2 * np.pi * 220 * np.arange(length) / sr)
    out[attack:] += 0.8 * clap
    return out.astype(np.float32)


def head_energy_kept(data: np.ndarray, out: np.ndarray, sr: int) -> float:
    head = round(0.010 * sr)
    return float(np.sum(out[:head] ** 2) / np.sum(data[:head] ** 2))


@pytest.mark.parametrize(
    ("attack", "minimum"),
    # Worst case on frame 0 (25 ms fade: 1.5 %, now 74.5 %);
    # as recorded (25 ms fade: 3.2 %, now 92.6 %).
    [(0, 0.60), (267, 0.90)],
)
def test_softened_seam_keeps_the_first_beat(attack, minimum):
    sr = 44100
    data = clap_loop(85_000, sr, attack)  # 1.93 s: the end fade is the full 25 ms
    out = soften_seam(data, sr)
    kept = head_energy_kept(data, out, sr)
    assert kept >= minimum, f"first 10 ms keep only {kept:.1%} of their energy"
    assert out[0] == 0.0 and out[-1] == 0.0  # still no step where the end meets the start
    assert len(out) == len(data)


def test_softened_seam_fades_the_end_as_before():
    sr = 44100
    data = clap_loop(85_000, sr)
    out = soften_seam(data, sr)
    n = seam_fade_frames(len(data), sr)
    assert n == round(0.025 * sr)
    ramp = (0.5 * (1.0 - np.cos(np.pi * np.arange(n) / n))).astype(np.float32)
    assert np.array_equal(out[-n:], data[-n:] * ramp[::-1])


def test_softened_seam_fade_in_is_short_but_never_longer_than_the_fade_out():
    sr = 44100
    for length in (85_000, 22_050, 441, 100):
        data = np.full(length, 0.5, dtype=np.float32)
        out = soften_seam(data, sr)
        n_out = seam_fade_frames(length, sr)
        n_in = min(round(0.002 * sr), n_out)  # 2 ms, never longer than the fade-out
        assert int(np.argmax(out == 0.5)) == n_in
        assert out[n_in - 1] < 0.5
        assert np.array_equal(out[n_in:length - n_out], data[n_in:length - n_out])


def test_softened_seam_leaves_a_silent_loop_silent():
    assert not soften_seam(np.zeros(4000, dtype=np.float32), 8000).any()
