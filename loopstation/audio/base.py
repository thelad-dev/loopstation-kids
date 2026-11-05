"""The narrow interface between the controller and any audio engine."""

from __future__ import annotations

from typing import Protocol

import numpy as np

# Voice key used for previewing a version in the history dialog; it never
# collides with a pad index.
PREVIEW_VOICE = -1


class AudioBackend(Protocol):
    """Mono float32 audio engine.

    Playback is keyed by pad: starting a pad replaces whatever that pad was
    playing. All methods are called from the GUI thread.
    """

    sample_rate: int
    available_input: bool

    def start_recording(self) -> bool:
        """Start capturing from the microphone; False if that is not possible."""
        ...

    def stop_recording(self) -> np.ndarray | None:
        """Stop capturing and return the recorded samples (None if nothing)."""
        ...

    def recording_seconds(self) -> float:
        """Length of the current recording in seconds."""
        ...

    def play(self, pad: int, data: np.ndarray, loop: bool) -> None:
        """Play ``data`` on ``pad`` once or as a loop."""
        ...

    def stop(self, pad: int) -> None:
        """Stop the voice of ``pad`` (no-op if silent)."""
        ...

    def stop_all(self) -> None:
        """Stop every voice."""
        ...

    def playing_pads(self) -> set[int]:
        """Keys of all voices that are currently audible."""
        ...

    def play_effect(self, data: np.ndarray) -> None:
        """Play a short sound effect on top of everything else."""
        ...

    def close(self) -> None:
        """Release the audio device."""
        ...
