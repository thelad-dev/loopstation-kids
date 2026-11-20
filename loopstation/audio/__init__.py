"""Audio engine: recording, mixing playback, WAV files and sound effects."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, MutableMapping
from typing import Any

from loopstation.audio.base import PREVIEW_VOICE, AudioBackend
from loopstation.audio.dynamics import db_to_gain
from loopstation.audio.null_backend import NullAudio
from loopstation.config import Settings

log = logging.getLogger(__name__)

__all__ = ["PREVIEW_VOICE", "AudioBackend", "NullAudio", "create_audio", "enable_asio"]

# Short German status texts for the small status line in the window.
NO_AUDIO_TEXT = "Kein Audiogerät gefunden"
NO_MIC_TEXT = "Kein Mikrofon gefunden"


def enable_asio(
    enabled: bool, platform: str = sys.platform, environ: MutableMapping[str, str] = os.environ
) -> None:
    """Ask sounddevice for its PortAudio build with ASIO (Windows only).

    sounddevice picks the DLL while it is imported, so this has to run before
    the first ``import sounddevice``: a change in the settings acts after a restart.
    """
    if enabled and platform.startswith("win32"):
        environ["SD_ENABLE_ASIO"] = "1"


def _import_sounddevice() -> Any:
    import sounddevice

    return sounddevice


def create_audio(
    settings: Settings,
    importer: Callable[[], Any] = _import_sounddevice,
    platform: str = sys.platform,
    environ: MutableMapping[str, str] = os.environ,
) -> tuple[AudioBackend, str | None]:
    """Create the best available audio backend.

    Returns the backend and a short status text if something is missing
    (``None`` if everything is available). Never raises. ``importer``,
    ``platform`` and ``environ`` are injected by tests.
    """
    try:
        from loopstation.audio.sounddevice_backend import SoundDeviceAudio

        enable_asio(settings.asio, platform, environ)
        sd = importer()
        latency = None if settings.latency_ms is None else settings.latency_ms / 1000
        audio = SoundDeviceAudio(
            settings.sample_rate,
            settings.max_record_seconds,
            latency,
            volume=min(settings.volume, db_to_gain(settings.max_level_db)),
            ceiling_db=settings.max_level_db,
            input_gain_db=settings.input_gain_db,
            auto_gain=settings.auto_gain,
            soft_seam=settings.soft_seam,
            sd=sd,
            input_device=settings.input_device,
            output_device=settings.output_device,
            hostapi=settings.audio_hostapi,
            platform=platform,
        )
    except Exception as exc:  # no PortAudio, no device, unsupported rate, ...
        log.warning("audio not available, continuing silently: %s", exc)
        return NullAudio(settings.sample_rate), NO_AUDIO_TEXT
    if not audio.available_input:
        return audio, NO_MIC_TEXT
    return audio, None
