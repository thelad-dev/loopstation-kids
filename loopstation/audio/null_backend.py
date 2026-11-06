"""Audio backend used when no audio device is available.

Nothing is audible and nothing can be recorded, but pads still light up
green for the length of their sample so the screen behaves consistently.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np


class NullAudio:
    available_input = False

    def __init__(self, sample_rate: int = 44100, clock: Callable[[], float] = time.monotonic) -> None:
        self.sample_rate = sample_rate
        self._clock = clock
        # pad -> end time (None = looping forever)
        self._voices: dict[int, float | None] = {}

    def start_recording(self) -> bool:
        return False

    def stop_recording(self) -> np.ndarray | None:
        return None

    def recording_seconds(self) -> float:
        return 0.0

    def recording_wait(self) -> float:
        return 0.0

    def set_grid(self, frames: int | None) -> None:
        pass  # nothing is audible, so there is nothing to keep in time

    def next_boundary_in(self) -> float | None:
        return None

    def pending_pads(self) -> set[int]:
        return set()

    def play(self, pad: int, data: np.ndarray, loop: bool) -> None:
        duration = len(data) / self.sample_rate
        self._voices[pad] = None if loop else self._clock() + duration

    def stop(self, pad: int, at_boundary: bool = False) -> None:
        self._voices.pop(pad, None)

    def stop_all(self) -> None:
        self._voices.clear()

    def playing_pads(self) -> set[int]:
        now = self._clock()
        self._voices = {p: end for p, end in self._voices.items() if end is None or end > now}
        return set(self._voices)

    def play_effect(self, data: np.ndarray) -> None:
        pass

    def close(self) -> None:
        self._voices.clear()
