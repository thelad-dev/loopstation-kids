"""Audio engine: recording, mixing playback, WAV files and sound effects."""

from __future__ import annotations

import logging

from loopstation.audio.base import PREVIEW_VOICE, AudioBackend
from loopstation.audio.null_backend import NullAudio
from loopstation.config import Settings

log = logging.getLogger(__name__)

__all__ = ["PREVIEW_VOICE", "AudioBackend", "NullAudio", "create_audio"]

# Short German status texts for the small status line in the window.
NO_AUDIO_TEXT = "Kein Audiogerät gefunden"
NO_MIC_TEXT = "Kein Mikrofon gefunden"


def create_audio(settings: Settings) -> tuple[AudioBackend, str | None]:
    """Create the best available audio backend.

    Returns the backend and a short status text if something is missing
    (``None`` if everything is available). Never raises.
    """
    try:
        from loopstation.audio.sounddevice_backend import SoundDeviceAudio

        audio = SoundDeviceAudio(settings.sample_rate, settings.max_record_seconds)
    except Exception as exc:  # no PortAudio, no device, unsupported rate, ...
        log.warning("audio not available, continuing silently: %s", exc)
        return NullAudio(settings.sample_rate), NO_AUDIO_TEXT
    if not audio.available_input:
        return audio, NO_MIC_TEXT
    return audio, None
