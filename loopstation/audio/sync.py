"""Pure arithmetic for the loop grid (no audio device, no state).

The first recording defines the loop length ``grid`` in frames. Loops start
and stop on the boundaries ``origin + k * grid`` and every later recording is
cut to a whole multiple of ``grid``.
"""

from __future__ import annotations

import numpy as np

# A stop pressed this long after a boundary still counts as that boundary, so
# a slightly late press does not append a whole loop of silence. Bounded by
# an eighth of the loop so short loops keep most of their tail.
STOP_GRACE_SECONDS = 0.15


def next_boundary(now: int, origin: int, grid: int) -> int:
    """First grid boundary at or after frame ``now``."""
    if grid <= 0:
        raise ValueError("grid must be positive")
    if now <= origin:
        return origin
    return origin + -(-(now - origin) // grid) * grid


def grace_frames(grid: int, sample_rate: int) -> int:
    """How far past a boundary a stop still counts as that boundary."""
    return min(grid // 8, int(STOP_GRACE_SECONDS * sample_rate))


def max_grid_frames(grid: int, max_frames: int) -> int:
    """Longest recording on the grid: ``max_frames`` rounded down to a multiple, at least one loop."""
    return max(grid, (max_frames // grid) * grid)


def fit_length(frames: int, grid: int, grace: int = 0, limit: int | None = None) -> int:
    """Target length for ``frames`` recorded frames on a grid of ``grid``.

    Shorter than one loop becomes one loop; longer becomes the next multiple,
    unless it ends at most ``grace`` frames after a boundary; ``limit`` caps
    the result (rounded down to a multiple, at least one loop).
    """
    if grid <= 0:
        raise ValueError("grid must be positive")
    loops = max(1, -(-(frames - grace) // grid))
    length = loops * grid
    if limit is not None:
        length = min(length, max_grid_frames(grid, limit))
    return length


def fit_to_grid(data: np.ndarray, grid: int, grace: int = 0, limit: int | None = None) -> np.ndarray:
    """``data`` cut or padded with silence to ``fit_length`` frames.

    Returns ``data`` itself when it already has the right length.
    """
    target = fit_length(len(data), grid, grace, limit)
    if len(data) == target:
        return data
    if len(data) > target:
        return np.ascontiguousarray(data[:target])
    out = np.zeros(target, dtype=np.float32)
    out[: len(data)] = data
    return out
