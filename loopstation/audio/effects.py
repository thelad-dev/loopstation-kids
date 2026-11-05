"""Short synthetic beeps that mark the start and the end of a recording."""

from __future__ import annotations

import numpy as np


def beep(frequency: float, seconds: float, sample_rate: int, volume: float = 0.3) -> np.ndarray:
    """A sine beep with short fades so it does not click."""
    count = max(1, int(seconds * sample_rate))
    t = np.arange(count, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * frequency * t).astype(np.float32) * volume
    fade = min(count // 2, int(0.01 * sample_rate))
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        tone[:fade] *= ramp
        tone[-fade:] *= ramp[::-1]
    return tone


def start_beep(sample_rate: int) -> np.ndarray:
    """Higher beep: recording starts."""
    return beep(880.0, 0.12, sample_rate)


def stop_beep(sample_rate: int) -> np.ndarray:
    """Lower beep: recording stops."""
    return beep(523.25, 0.15, sample_rate)
