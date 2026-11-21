"""Shortening a loop (Erweitert, parents only): the arithmetic, free of audio devices and state.

A loop is cut to ``source[start:end]``. Where the session has a loop grid and the parents
want it, the length snaps to a whole number of bars (at least one), so the trimmed loop
stays on the grid; the result is cut or padded with silence to that length. Without the
snap the length is exactly ``end - start`` and playback pads it to whole bars as it does
for any sample (``sync.fit_to_grid``), so the loop period never changes by accident.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from loopstation.audio.sync import fit_length, grace_frames

# Why a trim cannot be made (``TrimPlan.problem``).
ORDER = "order"  # the start is not before the end
SHORT = "short"  # the result would be shorter than the minimum
SAME = "same"  # nothing would change


@dataclass(frozen=True)
class TrimPlan:
    """What a trim of ``source[start:end]`` would make of a loop of ``length`` frames."""

    start: int
    end: int  # of the part taken from the source, after clamping (and after snapping down)
    frames: int  # length of the result
    snapped: bool  # the length was set to a whole number of bars
    bars: float | None  # frames / grid, None without a grid
    played: int | None  # frames the loop plays per round (whole bars), None without a grid
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def plan_trim(
    length: int,
    start: int,
    end: int,
    *,
    grid: int | None,
    min_frames: int,
    snap: bool,
    rate: int,
) -> TrimPlan:
    """Plan a trim of a loop of ``length`` frames to ``start`` .. ``end`` (frames, clamped to the loop).

    ``grid`` is the bar in frames (None: no grid, nothing to snap to). With ``snap`` the
    length becomes the nearest whole number of bars, at least one; it keeps the start, so
    a result longer than the rest of the loop is padded with silence. ``problem`` says why
    the trim is refused: the start is not before the end, the result is shorter than
    ``min_frames``, or nothing would change.
    """
    start = min(max(0, int(start)), max(0, length))
    end = min(max(0, int(end)), max(0, length))
    if end <= start:
        return TrimPlan(start, end, 0, False, None, None, ORDER)
    frames = end - start
    snapped = False
    if grid is not None and snap:
        frames = max(1, round(frames / grid)) * grid
        snapped = True
        end = min(length, start + frames)
    bars = None if grid is None else frames / grid
    played = None if grid is None else fit_length(frames, grid, grace_frames(grid, rate))
    problem = None
    if frames < min_frames:
        problem = SHORT
    elif start == 0 and frames == length and end == length:
        problem = SAME
    return TrimPlan(start, end, frames, snapped, bars, played, problem)


def trim_audio(source: np.ndarray, plan: TrimPlan) -> np.ndarray:
    """The part of ``source`` the plan takes, padded with silence to ``plan.frames``."""
    part = np.asarray(source[plan.start:plan.end], dtype=np.float32)
    if len(part) >= plan.frames:
        return np.ascontiguousarray(part[: plan.frames])
    out = np.zeros(plan.frames, dtype=np.float32)
    out[: len(part)] = part
    return out


def shift_markers(frames: list[int], marker_rate: int, rate: int, start: int, length: int) -> list[int]:
    """Marker positions of a loop after it was cut at ``start`` and is ``length`` frames long.

    ``frames`` are at ``marker_rate``; a marker moves by ``start`` and disappears when it
    lies outside the part that is left (a marker needs a position after the first frame).
    """
    moved = {round(f * rate / marker_rate) - start for f in frames}
    return sorted(f for f in moved if 0 < f < length)
