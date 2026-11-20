"""Gentle time stretching for recordings that are almost a whole number of loops long.

``stretch_to_grid`` takes the recorded ``data`` and the loop ``grid`` (frames)
and returns data stretched to exactly ``n * grid`` frames, but only when the
recording is already close to that length (default: within 10 %). Anything
further off returns ``None`` and the caller keeps the hard grid behaviour of
``fit_to_grid`` (pad with silence, cut to a multiple). A single clap in a
standing grid must stay a clap, not become a smeared stretch.

The stretching itself sits behind the ``StretchEngine`` protocol so a better
engine (Rubber Band) can replace the fallback without touching callers.

``WsolaEngine`` is the built-in fallback: a simple pitch-preserving WSOLA
(waveform similarity overlap-add) in plain numpy, no native dependency. It is
an honest simple stretch, not Rubber-Band quality: voices can sound slightly
metallic or phasey, which is exactly why the application limit is narrow.
Meant to run once when a recording stops, not inside the audio callback.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

# Plan section 1.1: apply only for a deviation below 8-10 % of the target.
DEFAULT_MAX_DEVIATION = 0.10


class StretchEngine(Protocol):
    """Anything that can stretch mono float32 ``data`` to exactly ``target`` frames."""

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray: ...


class WsolaEngine:
    """Pitch-preserving WSOLA stretch (fallback engine, simple quality)."""

    def __init__(self, frame_size: int = 2048, search: int = 512) -> None:
        if frame_size < 8 or frame_size % 2:
            raise ValueError("frame_size must be an even number of at least 8")
        self.frame_size = frame_size
        self.search = search

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray:
        if target <= 0:
            raise ValueError("target must be positive")
        data = np.asarray(data, dtype=np.float32)
        count = len(data)
        if count == target:
            return data
        if count == 0:
            return np.zeros(target, dtype=np.float32)
        frame = min(self.frame_size, max(8, (count // 4) // 2 * 2))
        if count < frame * 2:
            return _resample_tail(data, target)
        search = min(self.search, frame // 2)
        out = self._ola(data, target, frame, search)
        return _exact_length(out, target)

    @staticmethod
    def _ola(data: np.ndarray, target: int, frame: int, search: int) -> np.ndarray:
        hop = frame // 2
        ratio = target / len(data)
        window = np.hanning(frame + 1)[:frame].astype(np.float32)  # periodic: halves sum to 1
        first_window = window.copy()
        first_window[:hop] = 1.0  # nothing overlaps the start, so no fade-in
        # pad so every analysis window (plus search margin) stays inside the signal
        lead = np.zeros(search, np.float32)
        tail = np.zeros(frame + 2 * search, np.float32)
        padded = np.concatenate([lead, data, tail])
        frames = -(-target // hop) + 1
        out = np.zeros(frames * hop + frame, dtype=np.float32)
        previous_end = 0  # where the natural continuation of the last chosen segment starts
        for k in range(frames):
            ideal = int(round(k * hop / ratio))
            if k == 0:
                start = ideal
            else:
                template = padded[previous_end + search : previous_end + search + frame]
                lo = max(0, ideal - search)
                hi = min(len(padded) - frame, ideal + search)
                if hi <= lo:
                    start = min(lo, len(padded) - frame)
                else:
                    segment = padded[lo + search : hi + search + frame]
                    scores = np.correlate(segment, template, mode="valid")
                    start = lo + int(np.argmax(scores))
            chunk = padded[start + search : start + search + frame]
            out[k * hop : k * hop + frame] += chunk * (first_window if k == 0 else window)
            previous_end = start + hop
        return out


def _resample_tail(data: np.ndarray, target: int) -> np.ndarray:
    """Inputs too short for overlap-add: plain interpolation (pitch changes, but nothing shorter exists)."""
    positions = np.linspace(0, len(data) - 1, target)
    return np.interp(positions, np.arange(len(data)), data).astype(np.float32)


def _exact_length(data: np.ndarray, target: int) -> np.ndarray:
    if len(data) >= target:
        return np.ascontiguousarray(data[:target], dtype=np.float32)
    out = np.zeros(target, dtype=np.float32)
    out[: len(data)] = data
    return out


def stretch_target(frames: int, grid: int) -> int:
    """Nearest whole number of loops for ``frames`` recorded frames (at least one loop)."""
    if grid <= 0:
        raise ValueError("grid must be positive")
    return max(1, round(frames / grid)) * grid


def stretch_to_grid(
    data: np.ndarray,
    grid: int,
    *,
    max_deviation: float = DEFAULT_MAX_DEVIATION,
    engine: StretchEngine | None = None,
) -> np.ndarray | None:
    """``data`` stretched to the nearest multiple of ``grid``, or ``None`` when it is too far off.

    The deviation is ``abs(len(data) - target) / target``; it must not exceed
    ``max_deviation``. ``None`` means "do not stretch": use ``fit_to_grid``.
    Data that already has the target length is returned as is.
    """
    if len(data) == 0:
        return None
    target = stretch_target(len(data), grid)
    if abs(len(data) - target) / target > max_deviation:
        return None
    if len(data) == target:
        return data
    result = (engine or WsolaEngine()).stretch(data, target)
    if len(result) != target:
        raise ValueError(f"engine returned {len(result)} frames, expected {target}")
    return result
