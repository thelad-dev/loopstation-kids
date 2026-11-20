"""Onset analysis for the first recording (pure numpy, no audio device, no state).

Three independent steps, each a pure function so the caller can feed every
threshold from ``settings.toml``:

* :func:`detect_onsets` finds reliable onsets (sharp energy rises above a
  threshold relative to the recording's peak).
* :func:`rotate_to_onset` shifts the recording circularly so that an onset
  becomes frame 0 (same length, same content).
* :func:`derive_grid` turns the onsets into one bar of grid, or explicitly into
  "no grid", following the fallback rules below. It never guesses silently.

Terms: a *beat* is one quarter note, a *bar* is ``beats_per_bar`` beats. The
session grid (``master.frames``) is one bar. ``bpm = beats_per_bar * 60 * rate /
bar_frames``.

Fallback rules (plan section 2.2), implemented by :func:`derive_grid`:

1. Two onsets, distance inside the beat window (default 0.30-1.50 s, i.e.
   200-40 BPM): the distance is one beat, the bar is ``beats_per_bar`` beats
   (4/4 by default), the source is ``"onset"`` and the recording starts at the
   first onset (rotate with :func:`rotate_to_onset`). The bar must also fit
   into the recording (``bar <= length``) and into ``min_frames`` ..
   ``max_frames``; otherwise rules 3 and 5 apply (the recording length as one
   bar if sensible, else no grid), never a grid longer than the material.
2. Two onsets, distance too small (< window): a double hit or bounce, no grid
   from this pair. Further onsets are searched (rule 4), otherwise rule 5.
3. Two onsets, distance too large (e.g. 3 s): never a silent 3 s bar. The
   recording length becomes one bar (source ``"duration"``) only if that length
   is musically sensible: its tempo as one bar lies in the BPM window and it is
   within ``min_frames`` .. ``max_frames``. Otherwise there is no grid
   (source ``"none"``, free mode, hint to the parents).
4. More than two onsets: the median of the inter-onset intervals that lie in
   the window (outliers outside are dropped). With fewer than two plausible
   intervals the rules for two onsets apply (2, 3 or 5).
5. One onset or none: no onset grid. The recording length until the stop is
   one bar (source ``"duration"``) if ``min_frames <= length <= max_frames``;
   shorter than ``min_frames`` the recording is discarded (source ``"none"``,
   reason ``"too_short"``), longer than ``max_frames`` there is no grid either.
6. Timeout: if no second plausible onset arrives within
   ``timeout_seconds`` after the first one, nothing is estimated in the
   background; the caller waits for the stop and rule 5 applies.
   :func:`second_onset_timed_out` only reports that condition.

Rules 7 (visibility) and 8 (parent BPM wins) belong to the caller: with a
parent BPM set, ignore ``bar_frames`` from here but still use ``start_frame``
for the circular alignment.

``start_frame`` in the result is the first reliable onset (0 without onsets).
A hum without sharp attacks has no onset, so nothing is shifted.

The thresholds are starting values; they have not been tested with real
children's material (clapping, shouting, humming) yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

GridSource = Literal["onset", "duration", "none"]

# Start values, all overridable per call.
MIN_START_SECONDS = 0.15  # start beep is 0.12 s long: ignore onsets before this
REL_THRESHOLD = 0.25  # onset level relative to the peak of the analysed region
MIN_PEAK = 0.01  # quieter than this (about -40 dBFS) is silence, no onsets
MIN_GAP_SECONDS = 0.05  # refractory time between two onsets
RISE_RATIO = 3.0  # envelope must be this many times louder than 30 ms before
RISE_LOOKBACK_SECONDS = 0.03
HOP_SECONDS = 0.002
WINDOW_SECONDS = 0.008
BPM_MIN = 40.0
BPM_MAX = 200.0
BEATS_PER_BAR = 4
MIN_LOOP_SECONDS = 0.30
TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class GridResult:
    """Outcome of :func:`derive_grid`.

    ``source`` is ``"onset"`` (bar from the onset distance), ``"duration"``
    (the recording length is the bar) or ``"none"`` (no grid, see ``reason``).
    ``bar_frames`` and ``beat_frames`` are 0 for ``"none"``. ``start_frame`` is
    the first onset for the circular alignment, 0 without onsets.
    """

    source: GridSource
    bar_frames: int
    beat_frames: int
    start_frame: int
    reason: str

    @property
    def has_grid(self) -> bool:
        return self.source != "none"

    def bpm(self, rate: int, beats_per_bar: int = BEATS_PER_BAR) -> float | None:
        """Tempo of the bar, or ``None`` without a grid."""
        if not self.has_grid:
            return None
        return beats_per_bar * 60.0 * rate / self.bar_frames


def _envelope(samples: np.ndarray, hop: int, window: int) -> np.ndarray:
    """RMS envelope; entry ``i`` covers frames ``i * hop .. i * hop + window``."""
    count = (len(samples) - window) // hop + 1
    if count <= 0:
        return np.zeros(0)
    power = np.concatenate(([0.0], np.cumsum(samples.astype(np.float64) ** 2)))
    starts = np.arange(count) * hop
    return np.sqrt(np.maximum(power[starts + window] - power[starts], 0.0) / window)


def detect_onsets(
    samples: np.ndarray,
    rate: int,
    *,
    min_start_seconds: float = MIN_START_SECONDS,
    rel_threshold: float = REL_THRESHOLD,
    min_peak: float = MIN_PEAK,
    min_gap_seconds: float = MIN_GAP_SECONDS,
    rise_ratio: float = RISE_RATIO,
    rise_lookback_seconds: float = RISE_LOOKBACK_SECONDS,
    hop_seconds: float = HOP_SECONDS,
    window_seconds: float = WINDOW_SECONDS,
) -> list[int]:
    """Frames of the reliable onsets, ascending.

    An onset is an envelope crossing of ``rel_threshold * peak`` from below that
    is also a sharp rise (``rise_ratio`` times louder than ``rise_lookback_seconds``
    earlier). Slow swells such as a hummed tone therefore produce no onset. The
    peak is taken only after ``min_start_seconds``, so the start beep leaking
    into the microphone neither sets the threshold nor counts as an onset.
    ``min_gap_seconds`` is the refractory time after an onset; the envelope must
    also fall below half the threshold before the next one can arm.
    """
    mono = np.asarray(samples, dtype=np.float64)
    if mono.ndim != 1:
        raise ValueError("samples must be mono (1-D)")
    hop = max(1, round(hop_seconds * rate))
    window = max(hop, round(window_seconds * rate))
    env = _envelope(mono, hop, window)
    first = int(np.ceil(min_start_seconds * rate / hop))
    if len(env) <= first:
        return []
    peak = float(env[first:].max())
    if peak < min_peak:
        return []
    threshold = rel_threshold * peak
    lookback = max(1, round(rise_lookback_seconds * rate / hop))
    gap = max(1, round(min_gap_seconds * rate / hop))

    onsets: list[int] = []
    armed = True
    blocked_until = first
    for i in range(first, len(env)):
        level = env[i]
        if level < threshold * 0.5:
            armed = True
        if not armed or i < blocked_until or level < threshold:
            continue
        before = env[max(0, i - lookback) : i]
        floor = float(before.min()) if len(before) else 0.0
        # The small constant keeps a start from digital silence a valid rise.
        if level >= rise_ratio * max(floor, 0.02 * threshold):
            # Walk back to where the rise began so the onset sits at the attack.
            start = i
            low = 0.2 * threshold
            while start > first and env[start - 1] >= low and env[start - 1] < env[start]:
                start -= 1
            onsets.append(start * hop)
            armed = False
            blocked_until = i + gap
    return onsets


def rotate_to_onset(samples: np.ndarray, onset: int) -> np.ndarray:
    """Shift circularly so that frame ``onset`` becomes frame 0.

    The length and the content (sum, energy) stay as they are; the material
    before the onset moves to the end, so the seam lies behind the attack.
    """
    if len(samples) == 0:
        return np.array(samples, copy=True)
    return np.roll(samples, -(int(onset) % len(samples)), axis=0)


def second_onset_timed_out(
    onsets: list[int], now: int, rate: int, *, timeout_seconds: float = TIMEOUT_SECONDS
) -> bool:
    """Rule 6: exactly one onset so far and ``timeout_seconds`` passed since it.

    Only reports the condition; the caller keeps recording and applies rule 5
    at the stop. Nothing is estimated in the background.
    """
    return len(onsets) == 1 and now - onsets[0] > timeout_seconds * rate


def _window_frames(rate: int, bpm_min: float, bpm_max: float) -> tuple[int, int]:
    """Shortest and longest beat in frames for the BPM window."""
    return round(60.0 / bpm_max * rate), round(60.0 / bpm_min * rate)


def _median_beat(onsets: list[int], shortest: int, longest: int) -> int | None:
    """Median of the inter-onset intervals inside the window, ``None`` if fewer than one."""
    intervals = [b - a for a, b in zip(onsets, onsets[1:], strict=False) if shortest <= b - a <= longest]
    if not intervals:
        return None
    return int(round(float(np.median(intervals))))


def derive_grid(
    onsets: list[int],
    total_frames: int,
    rate: int,
    *,
    bpm_min: float = BPM_MIN,
    bpm_max: float = BPM_MAX,
    beats_per_bar: int = BEATS_PER_BAR,
    min_frames: int | None = None,
    max_frames: int | None = None,
) -> GridResult:
    """One bar of grid from the onsets of a recording of ``total_frames``, or no grid.

    Applies the fallback rules 1-5 from the module docstring. ``min_frames``
    defaults to ``MIN_LOOP_SECONDS`` and should be
    ``max(0.30 s, 2 * crossfade + 50 ms)`` from the caller; ``max_frames`` is
    ``max_record_seconds * rate`` (default: unlimited). ``bpm_min`` and
    ``bpm_max`` give the beat window (40-200 BPM is 0.30-1.50 s).

    A bar derived from onsets never exceeds ``total_frames``: if it would be
    longer than the recording, the onset grid is rejected and rules 3 and 5
    apply (the recording length as one bar if plausible, otherwise no grid).
    """
    if beats_per_bar < 1:
        raise ValueError("beats_per_bar must be at least 1")
    if not 0 < bpm_min <= bpm_max:
        raise ValueError("need 0 < bpm_min <= bpm_max")
    minimum = round(MIN_LOOP_SECONDS * rate) if min_frames is None else min_frames
    maximum = total_frames if max_frames is None else max_frames
    shortest, longest = _window_frames(rate, bpm_min, bpm_max)
    start = min(onsets) if onsets else 0

    def none(reason: str) -> GridResult:
        return GridResult("none", 0, 0, start, reason)

    # Rules 1, 2, 4: a beat from the plausible onset distances.
    beat = _median_beat(sorted(onsets), shortest, longest)
    if beat is not None:
        bar = beat * beats_per_bar
        if minimum <= bar <= min(maximum, total_frames):
            return GridResult("onset", bar, beat, start, "beat_from_onsets")

    # Rules 3 and 5: the recording length is the bar, if it makes sense.
    if total_frames < minimum:
        return none("too_short")
    if total_frames > maximum:
        return none("too_long")
    if len(onsets) >= 2:
        # Rule 3 (and 2 without further onsets): onsets exist but give no beat,
        # so the length must also fit the tempo window as one bar.
        bar_bpm = beats_per_bar * 60.0 * rate / total_frames
        if not bpm_min <= bar_bpm <= bpm_max:
            return none("onsets_without_beat_and_length_implausible")
    return GridResult("duration", total_frames, total_frames // beats_per_bar, start, "length_as_bar")
