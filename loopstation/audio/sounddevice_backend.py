"""Real audio engine on top of sounddevice (PortAudio).

``sounddevice`` is imported inside the constructor, so the rest of the app
works on machines without PortAudio (the factory then falls back to
``NullAudio``).

Threading: the PortAudio callbacks run on audio threads. They only touch the
voice table and the recording buffer, both guarded by one lock, and never
call into Qt.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class _Voice:
    data: np.ndarray
    loop: bool
    pos: int = 0


class SoundDeviceAudio:
    def __init__(self, sample_rate: int, max_record_seconds: float) -> None:
        import sounddevice  # deferred on purpose, see module docstring

        self._sd = sounddevice
        self.sample_rate = sample_rate
        self._max_frames = int((max_record_seconds + 1) * sample_rate)
        self._lock = threading.Lock()
        self._voices: dict[int, _Voice] = {}
        self._effects: list[_Voice] = []
        self._chunks: list[np.ndarray] = []
        self._recorded_frames = 0
        self._input: Any = None

        # One output stream runs for the lifetime of the app and mixes all
        # voices; starting a sound is then just adding it to the table.
        self._output = sounddevice.OutputStream(
            samplerate=sample_rate, channels=1, dtype="float32", callback=self._output_callback
        )
        self._output.start()

        try:
            sounddevice.check_input_settings(samplerate=sample_rate, channels=1, dtype="float32")
            self.available_input = True
        except Exception as exc:  # no input device or unsupported format
            log.info("no usable microphone: %s", exc)
            self.available_input = False

    # ------------------------------------------------------------ callbacks

    @staticmethod
    def _mix_voice(out: np.ndarray, voice: _Voice) -> bool:
        """Add ``voice`` into ``out``; return False when it has finished."""
        length = len(voice.data)
        if length == 0:
            return False
        filled = 0
        frames = len(out)
        while filled < frames:
            count = min(frames - filled, length - voice.pos)
            out[filled:filled + count] += voice.data[voice.pos:voice.pos + count]
            filled += count
            voice.pos += count
            if voice.pos >= length:
                if not voice.loop:
                    return False
                voice.pos = 0
        return True

    def _output_callback(self, outdata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        mix = np.zeros(frames, dtype=np.float32)
        with self._lock:
            finished = [p for p, v in self._voices.items() if not self._mix_voice(mix, v)]
            for pad in finished:
                del self._voices[pad]
            self._effects = [e for e in self._effects if self._mix_voice(mix, e)]
        np.clip(mix, -1.0, 1.0, out=mix)
        outdata[:, 0] = mix

    def _input_callback(self, indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        with self._lock:
            room = self._max_frames - self._recorded_frames
            if room <= 0:
                return
            chunk = indata[:room, 0].copy()
            self._chunks.append(chunk)
            self._recorded_frames += len(chunk)

    # ------------------------------------------------------------ recording

    def start_recording(self) -> bool:
        if not self.available_input:
            return False
        self._discard_input()
        with self._lock:
            self._chunks = []
            self._recorded_frames = 0
        try:
            self._input = self._sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                callback=self._input_callback,
            )
            self._input.start()
        except Exception as exc:
            log.warning("cannot open microphone: %s", exc)
            self._input = None
            return False
        return True

    def stop_recording(self) -> np.ndarray | None:
        self._discard_input()
        with self._lock:
            chunks, self._chunks = self._chunks, []
            self._recorded_frames = 0
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.float32)

    def recording_seconds(self) -> float:
        with self._lock:
            return self._recorded_frames / self.sample_rate

    def _discard_input(self) -> None:
        if self._input is not None:
            try:
                self._input.stop()
                self._input.close()
            except Exception as exc:
                log.warning("closing microphone failed: %s", exc)
            self._input = None

    # ------------------------------------------------------------- playback

    def play(self, pad: int, data: np.ndarray, loop: bool) -> None:
        with self._lock:
            self._voices[pad] = _Voice(np.asarray(data, dtype=np.float32), loop)

    def stop(self, pad: int) -> None:
        with self._lock:
            self._voices.pop(pad, None)

    def stop_all(self) -> None:
        with self._lock:
            self._voices.clear()

    def playing_pads(self) -> set[int]:
        with self._lock:
            return set(self._voices)

    def play_effect(self, data: np.ndarray) -> None:
        with self._lock:
            self._effects.append(_Voice(np.asarray(data, dtype=np.float32), loop=False))

    def close(self) -> None:
        self._discard_input()
        try:
            self._output.stop()
            self._output.close()
        except Exception as exc:
            log.warning("closing audio output failed: %s", exc)
