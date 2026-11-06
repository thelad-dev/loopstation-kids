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
