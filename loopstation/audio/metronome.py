"""Metronome maths: where the beats of the session grid are, and the tick itself.

The session grid is one bar (``frames`` long); a bar holds ``beats`` beats
(see ``config.SIGNATURES``). Everything here is pure, so the controller, the
parents' page and the tests share one definition of "the beat".
"""

from __future__ import annotations

import math

import numpy as np

from loopstation.audio.dynamics import db_to_gain
from loopstation.audio.effects import beep

TICK_SECONDS = 0.03
TICK_HZ = 1000.0
ACCENT_HZ = 1500.0  # the first beat of a bar sounds a little higher
# A beat that falls this close to "now" counts as now (rounding of the clock).
EPSILON = 1e-6


def beat_seconds(bar_seconds: float, beats: int) -> float:
    """Length of one beat: a bar divided into its beats."""
    return bar_seconds / beats


def beat_index(position: float, beats: int) -> int:
    """Index (0-based, 0 = first beat of the bar) of the beat nearest to ``position`` (in beats)."""
    return round(position) % beats


def seconds_to_next_beat(position: float, period: float) -> float:
    """Time until the next beat boundary from ``position`` (in beats); 0 when exactly on one."""
    ahead = math.ceil(position - EPSILON) - position
    return max(0.0, ahead) * period


def tick(sample_rate: int, level_db: float, accent: bool = False) -> np.ndarray:
    """One quiet tick at ``level_db`` (dB(FS), before master volume and ceiling)."""
    return beep(ACCENT_HZ if accent else TICK_HZ, TICK_SECONDS, sample_rate, volume=db_to_gain(level_db))


def delayed(data: np.ndarray, frames: int) -> np.ndarray:
    """``data`` after ``frames`` of silence: an effect that starts now and sounds on the beat."""
    if frames <= 0:
        return data
    out = np.zeros(frames + len(data), dtype=np.float32)
    out[frames:] = data
    return out
