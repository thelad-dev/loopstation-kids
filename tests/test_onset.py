"""Onset analysis: synthetic signals and the fallback rules, no audio device."""

from __future__ import annotations

import numpy as np
import pytest

from loopstation.audio.onset import (
    GridResult,
    derive_grid,
    detect_onsets,
    rotate_to_onset,
    second_onset_timed_out,
)

RATE = 48000


def _clap(length: int = 1200, seed: int = 0) -> np.ndarray:
    """Short noise burst with a fast decay."""
    rng = np.random.default_rng(seed)
    return rng.uniform(-1, 1, length) * np.exp(-np.arange(length) / (length / 5)) * 0.8


def _claps(times: list[float], seconds: float = 4.0, noise: float = 0.002) -> np.ndarray:
    rng = np.random.default_rng(1)
    out = rng.normal(0, noise, int(seconds * RATE))
    for k, t in enumerate(times):
        start = int(t * RATE)
        burst = _clap(seed=k)
        out[start : start + len(burst)] += burst
    return out


def _hum(seconds: float = 4.0, attack: float = 0.6) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    envelope = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / attack)
    return 0.5 * envelope * np.sin(2 * np.pi * 220 * t)


# --- detection -----------------------------------------------------------------


def test_claps_are_found_at_their_positions():
    times = [0.5, 1.1, 1.7, 2.3]
    found = detect_onsets(_claps(times), RATE)
    assert len(found) == len(times)
    for frame, expected in zip(found, times, strict=True):
        assert abs(frame - expected * RATE) < 0.015 * RATE


def test_hum_gives_no_onsets():
    assert detect_onsets(_hum(), RATE) == []


def test_silence_and_faint_noise_give_no_onsets():
    assert detect_onsets(np.zeros(RATE), RATE) == []
    assert detect_onsets(np.random.default_rng(2).normal(0, 0.001, RATE), RATE) == []


def test_early_spurious_onsets_are_ignored():
    # Start beep leaking into the microphone: loud, but before the minimum start.
    signal = _claps([0.05, 0.8, 1.4])
    found = detect_onsets(signal, RATE)
    assert len(found) == 2
    assert all(frame > 0.7 * RATE for frame in found)


def test_threshold_is_relative_to_the_peak():
    # A quiet bump next to a loud clap stays below a quarter of the peak.
    signal = _claps([0.5, 1.2])
    start = int(1.8 * RATE)
    signal[start : start + 1200] += 0.1 * _clap(seed=9)
    assert len(detect_onsets(signal, RATE)) == 2


def test_close_claps_are_separate_onsets_but_not_inside_the_gap():
    assert len(detect_onsets(_claps([0.5, 0.79]), RATE)) == 2
    assert len(detect_onsets(_claps([0.5, 0.52]), RATE)) == 1


def test_mono_only():
    with pytest.raises(ValueError):
        detect_onsets(np.zeros((100, 2)), RATE)


# --- circular shift ------------------------------------------------------------


def test_rotation_keeps_length_and_content():
    signal = _claps([0.5, 1.1])
    shifted = rotate_to_onset(signal, int(0.5 * RATE))
    assert len(shifted) == len(signal)
    assert np.isclose(shifted.sum(), signal.sum())
    assert np.isclose((shifted**2).sum(), (signal**2).sum())
    # The onset is now at the start, the material before it moved to the end.
    assert np.array_equal(shifted[:100], signal[int(0.5 * RATE) : int(0.5 * RATE) + 100])
    assert np.array_equal(shifted[-int(0.5 * RATE) :], signal[: int(0.5 * RATE)])


def test_rotation_edge_cases():
    signal = np.arange(10.0)
    assert np.array_equal(rotate_to_onset(signal, 0), signal)
    assert np.array_equal(rotate_to_onset(signal, 10), signal)
    assert rotate_to_onset(np.zeros(0), 5).size == 0
    stereo = np.arange(20.0).reshape(10, 2)
    assert np.array_equal(rotate_to_onset(stereo, 3), np.roll(stereo, -3, axis=0))


# --- grid rules ----------------------------------------------------------------


def _grid(onsets_s: list[float], total_s: float = 5.0, **kwargs) -> GridResult:
    return derive_grid(
        [round(t * RATE) for t in onsets_s], round(total_s * RATE), RATE, max_frames=10 * RATE, **kwargs
    )


def test_rule_1_two_onsets_inside_the_window_make_a_beat():
    result = _grid([1.0, 1.5])
    assert result.source == "onset"
    assert result.beat_frames == round(0.5 * RATE)
    assert result.bar_frames == 4 * result.beat_frames  # 4/4: one bar is four beats
    assert result.start_frame == RATE
    assert result.bpm(RATE) == pytest.approx(120.0)


def test_rule_1_window_edges():
    assert _grid([1.0, 1.30]).source == "onset"  # 0.30 s = 200 BPM, still inside
    assert _grid([1.0, 2.50]).source == "onset"  # 1.50 s = 40 BPM, still inside
    assert _grid([1.0, 1.29], total_s=0.2).source == "none"  # 0.29 s is too small
    assert _grid([1.0, 2.51], total_s=0.2).source == "none"  # 1.51 s is too large


def test_rule_2_too_small_distance_is_no_grid_from_the_pair():
    result = _grid([1.0, 1.29], total_s=3.0)
    assert result.source == "duration"  # falls back to rule 5, not to a 0.29 s beat
    assert result.beat_frames != round(0.29 * RATE)


def test_rule_2_further_onsets_are_searched():
    result = _grid([1.0, 1.29, 1.89])  # pair too small, next distance 0.60 s is a beat
    assert result.source == "onset"
    assert result.beat_frames == round(0.6 * RATE)


def test_rule_3_too_large_distance_uses_the_recording_length_when_sensible():
    result = _grid([1.0, 4.0], total_s=5.0)  # 3 s apart is not a beat; 5 s as one bar is 48 BPM
    assert result.source == "duration"
    assert result.bar_frames == 5 * RATE
    assert result.reason == "length_as_bar"


def test_rule_3_too_large_distance_and_implausible_length_is_no_grid():
    result = _grid([1.0, 4.0], total_s=9.5)  # 9.5 s as one bar is 25 BPM
    assert result.source == "none"
    assert result.bar_frames == 0
    assert result.bpm(RATE) is None
    assert result.start_frame == RATE  # still reported for a circular alignment


def test_rule_4_median_ignores_outliers():
    # Beats of 0.5 s, plus one 3 s gap and one 0.1 s bounce, both outside the window.
    onsets = [1.0, 1.5, 2.0, 2.1, 2.6, 5.6, 6.1]
    result = _grid(onsets, total_s=7.0)
    assert result.source == "onset"
    assert result.beat_frames == round(0.5 * RATE)


def test_rule_4_median_of_uneven_intervals():
    result = _grid([0.5, 1.0, 1.52, 2.1, 2.6], total_s=4.0)  # 0.50, 0.52, 0.58, 0.50
    assert result.beat_frames == round(0.51 * RATE)


def test_rule_4_with_fewer_than_two_plausible_intervals_falls_back():
    # One plausible interval is enough for a beat; none sends it to rule 3.
    assert _grid([1.0, 1.5, 5.0], total_s=6.0).source == "onset"
    assert _grid([1.0, 4.0, 7.0], total_s=6.0).source == "duration"  # 6 s bar is 40 BPM


def test_rule_5_one_onset_or_none_uses_the_recording_length():
    one = _grid([1.0], total_s=3.0)
    assert (one.source, one.bar_frames, one.start_frame) == ("duration", 3 * RATE, RATE)
    none = _grid([], total_s=3.0)
    assert (none.source, none.bar_frames, none.start_frame) == ("duration", 3 * RATE, 0)


def test_rule_5_too_short_is_discarded_and_too_long_is_no_grid():
    short = _grid([], total_s=0.29)
    assert (short.source, short.reason) == ("none", "too_short")
    assert _grid([], total_s=0.30).source == "duration"
    assert _grid([], total_s=10.0).source == "duration"
    assert _grid([], total_s=10.01).source == "none"


def test_rule_5_applies_to_a_hum():
    signal = _hum(3.0)
    onsets = detect_onsets(signal, RATE)
    result = derive_grid(onsets, len(signal), RATE, max_frames=10 * RATE)
    assert onsets == []
    assert result.source == "duration"  # the recording length, not an onset guess
    assert result.start_frame == 0  # nothing is shifted


def test_rule_6_timeout():
    assert not second_onset_timed_out([RATE], now=RATE + 2 * RATE, rate=RATE)
    assert second_onset_timed_out([RATE], now=RATE + 2 * RATE + 1, rate=RATE)
    assert not second_onset_timed_out([], now=10 * RATE, rate=RATE)
    assert not second_onset_timed_out([RATE, 2 * RATE], now=10 * RATE, rate=RATE)
    assert second_onset_timed_out([RATE], now=RATE + RATE, rate=RATE, timeout_seconds=0.5)


def test_time_signature_and_window_are_parameters():
    three = _grid([1.0, 1.5], beats_per_bar=3)
    assert three.bar_frames == 3 * round(0.5 * RATE)
    assert three.bpm(RATE, 3) == pytest.approx(120.0)
    # Narrower window from the settings: 0.5 s is 120 BPM, outside 40-100 BPM.
    assert _grid([1.0, 1.5], total_s=0.2, bpm_max=100.0).source == "none"


def test_minimum_loop_length_is_a_parameter():
    # One beat of 0.3 s in 4/4 is a 1.2 s bar; a longer minimum (crossfade) rejects it.
    assert _grid([1.0, 1.3]).source == "onset"
    refused = _grid([1.0, 1.3], total_s=1.0, min_frames=round(1.5 * RATE))
    assert refused.source == "none"


def test_bar_longer_than_the_maximum_is_no_onset_grid():
    # 1.5 s beats in 4/4 would be a 6 s bar; with a 5 s maximum that is not allowed.
    result = derive_grid([RATE, round(2.5 * RATE)], 4 * RATE, RATE, max_frames=5 * RATE)
    assert result.source == "duration"
    assert result.bar_frames == 4 * RATE


def test_invalid_parameters():
    with pytest.raises(ValueError):
        derive_grid([], RATE, RATE, beats_per_bar=0)
    with pytest.raises(ValueError):
        derive_grid([], RATE, RATE, bpm_min=100, bpm_max=50)


def test_end_to_end_claps_to_grid_and_rotation():
    signal = _claps([0.7, 1.2, 1.7, 2.2], seconds=3.0)
    onsets = detect_onsets(signal, RATE)
    result = derive_grid(onsets, len(signal), RATE, max_frames=10 * RATE)
    assert result.source == "onset"
    assert result.bpm(RATE) == pytest.approx(120.0, rel=0.02)
    shifted = rotate_to_onset(signal, result.start_frame)
    assert len(shifted) == len(signal)
    assert np.abs(shifted[:600]).max() > 0.1  # the first clap sits at the start
