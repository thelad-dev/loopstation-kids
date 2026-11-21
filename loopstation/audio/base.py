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

    def start_recording(self, align: bool = True) -> bool:
        """Start capturing from the microphone; False if that is not possible.

        With a grid and loops running a recording begins on the next loop start;
        ``align=False`` (a free pad) starts it at once instead.
        """
        ...

    def stop_recording(self) -> np.ndarray | None:
        """Stop capturing and return the recorded samples (None if nothing)."""
        ...

    def recording_seconds(self) -> float:
        """Length of the current recording in seconds."""
        ...

    def recording_wait(self) -> float:
        """Seconds until a recording that waits for the next loop start begins (0 if not waiting)."""
        ...

    def recording_aligned(self) -> bool:
        """True if the running recording was started so that it begins on the next loop start.

        That is: a grid is set and loops ran on it when ``start_recording`` was
        called with ``align``. False without a recording, for a free pad and
        for a recording that began at once.
        """
        ...

    def set_grid(self, frames: int | None) -> None:
        """Loop length in frames that loops and recordings snap to (None = free, as without sync).

        With a grid, a loop starts on the next loop start of the loops that
        are already playing (at once if none is), and a recording started
        while loops play begins exactly on the next loop start.
        """
        ...

    def next_boundary_in(self) -> float | None:
        """Seconds until the next loop start, or None while no loop runs on the grid."""
        ...

    def pending_pads(self) -> set[int]:
        """Pads whose loop waits for the next loop start to begin or to end."""
        ...

    def play(
        self, pad: int, data: np.ndarray, loop: bool, free: bool = False, align: bool = False
    ) -> None:
        """Play ``data`` on ``pad`` once (at once) or as a loop (on the grid, if one is set).

        ``free``: a loop of a free pad. It keeps its own length, never defines
        or keeps up the grid and stops at once. It begins at once, or, with
        ``align`` and loops already running on the grid, on their next loop start.
        """
        ...

    def stop(self, pad: int, at_boundary: bool = False) -> None:
        """Stop the voice of ``pad`` (no-op if silent).

        ``at_boundary``: a loop on the grid keeps playing up to the next loop
        start; everything else stops at once.
        """
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

    def set_volume(self, volume: float) -> None:
        """Master volume as a linear gain from 0 (silent) to 1; the engine moves there in a ramp."""
        ...

    def set_ceiling_db(self, db: float) -> None:
        """Peak ceiling of the output in dB(FS) (0 or below); the output never gets louder."""
        ...

    def set_input_gain_db(self, db: float) -> None:
        """Trim of the microphone in dB, applied to what is recorded."""
        ...

    def set_auto_gain(self, enabled: bool) -> None:
        """Slowly even out the recording level (never raises the gain while the input clips)."""
        ...

    def poll_input_level(self) -> tuple[float, int]:
        """``(peak, clips)``: peak of the microphone since the last call (linear, after the
        trim, can exceed 1) and how many input blocks clipped in total since the start."""
        ...

    def close(self) -> None:
        """Release the audio device."""
        ...
