"""Real audio engine on top of sounddevice (PortAudio).

``sounddevice`` is imported inside the constructor, so the rest of the app
works on machines without PortAudio (the factory then falls back to
``NullAudio``). Tests pass a stand-in module instead.

Threading: the PortAudio callbacks run on audio threads. They only touch the
voice table and the recording buffer, both guarded by one lock, and never
call into Qt.

Loop grid: the output callback counts every frame it hands to the device
(``_frame``). With a grid set (``set_grid``), loops start and stop on the
boundaries ``_origin + k * grid`` of that counter, and a recording that is
started while loops play is cut to begin exactly on a boundary. Microphone
blocks are mapped to output frames ("which frame could be heard when the
microphone picked this up") with the input and output latency, so the new
loop lines up with what the child heard while recording.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from loopstation.audio.sync import next_boundary

log = logging.getLogger(__name__)


@dataclass
class _Voice:
    data: np.ndarray
    loop: bool
    pos: int = 0
    # First output frame of the voice and, for a loop told to stop on the
    # grid, the output frame where it ends.
    start: int = 0
    end: int | None = None
    # True for loops that run on the grid (they keep the grid going).
    synced: bool = False


class SoundDeviceAudio:
    def __init__(
        self,
        sample_rate: int,
        max_record_seconds: float,
        latency_seconds: float | None = None,
        sd: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if sd is None:
            import sounddevice as sd  # deferred on purpose, see module docstring

        self._sd = sd
        self._clock = clock
        self.sample_rate = sample_rate
        self._max_frames = int((max_record_seconds + 1) * sample_rate)
        # None = use the latencies PortAudio reports for the two streams.
        self._latency_seconds = latency_seconds
        self._lock = threading.Lock()
        self._voices: dict[int, _Voice] = {}
        self._effects: list[_Voice] = []

        # Output frame counter and the time the latest output block was
        # requested (used to place microphone blocks between two callbacks).
        self._frame = 0
        self._block_start = 0
        self._block_time: float | None = None

        self._grid: int | None = None
        self._origin = 0

        self._chunks: list[np.ndarray] = []
        self._recorded_frames = 0
        # Output frame where a recording on the grid begins (None = take the
        # microphone as it comes) and whether its first block was placed.
        self._rec_start: int | None = None
        self._rec_aligned = False
        self._latency_frames = 0
        self._input: Any = None

        # One output stream runs for the lifetime of the app and mixes all
        # voices; starting a sound is then just adding it to the table.
        self._output = sd.OutputStream(
            samplerate=sample_rate, channels=1, dtype="float32", callback=self._output_callback
        )
        self._output.start()

        try:
            sd.check_input_settings(samplerate=sample_rate, channels=1, dtype="float32")
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

    @classmethod
    def _render(cls, out: np.ndarray, voice: _Voice, block_start: int) -> bool:
        """Mix the part of ``voice`` that falls into this block; False when it is over."""
        frames = len(out)
        begin = voice.start - block_start
        if begin >= frames:
            return True  # starts in a later block
        begin = max(0, begin)
        stop = frames
        if voice.end is not None:
            stop = min(frames, voice.end - block_start)
            if stop <= begin:
                return False
        alive = cls._mix_voice(out[begin:stop], voice)
        if voice.end is not None and block_start + frames >= voice.end:
            return False
        return alive

    def _output_callback(self, outdata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        mix = np.zeros(frames, dtype=np.float32)
        with self._lock:
            start = self._frame
            self._block_start = start
            self._block_time = self._clock()
            finished = [p for p, v in self._voices.items() if not self._render(mix, v, start)]
            for pad in finished:
                del self._voices[pad]
            self._effects = [e for e in self._effects if self._render(mix, e, start)]
            self._frame = start + frames
        np.clip(mix, -1.0, 1.0, out=mix)
        outdata[:, 0] = mix

    def _now_frame(self) -> int:
        """Output frame position now, between two output callbacks (lock held)."""
        if self._block_time is None:
            return self._frame
        elapsed = self._clock() - self._block_time
        return self._block_start + max(0, int(round(elapsed * self.sample_rate)))

    def _input_callback(self, indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        with self._lock:
            block = indata[:, 0]
            if self._rec_start is not None and not self._rec_aligned:
                # Output frame that was audible when the first frame of this
                # block reached the microphone.
                first = self._now_frame() - self._latency_frames - frames
                skip = self._rec_start - first
                if skip >= frames:
                    return  # still before the loop start
                self._rec_aligned = True
                if skip > 0:
                    block = block[skip:]
                elif skip < 0:
                    # The microphone opened too late: fill the missing start
                    # with silence so that frame 0 stays on the boundary.
                    missing = min(-skip, self._max_frames)
                    self._chunks.append(np.zeros(missing, dtype=np.float32))
                    self._recorded_frames += missing
            room = self._max_frames - self._recorded_frames
            if room <= 0:
                return
            chunk = block[:room].copy()
            self._chunks.append(chunk)
            self._recorded_frames += len(chunk)

    # ------------------------------------------------------------ loop grid

    def _grid_running(self, exclude: int | None = None) -> bool:
        """True while loops (or a recording) keep the grid going (lock held)."""
        if self._rec_start is not None:
            return True
        return any(v.synced for p, v in self._voices.items() if p != exclude)

    def set_grid(self, frames: int | None) -> None:
        with self._lock:
            if frames == self._grid:
                return
            self._grid = frames
            # Loops that are already playing go on, but no longer define the grid.
            for voice in self._voices.values():
                voice.synced = False

    def next_boundary_in(self) -> float | None:
        with self._lock:
            if self._grid is None or not self._grid_running():
                return None
            now = self._frame
            return (next_boundary(now, self._origin, self._grid) - now) / self.sample_rate

    def pending_pads(self) -> set[int]:
        with self._lock:
            now = self._frame
            return {p for p, v in self._voices.items() if v.start > now or v.end is not None}

    # ------------------------------------------------------------ recording

    def start_recording(self) -> bool:
        if not self.available_input:
            return False
        self._discard_input()
        with self._lock:
            self._chunks = []
            self._recorded_frames = 0
            self._rec_start = None
            self._rec_aligned = False
            if self._grid is not None and self._grid_running():
                self._rec_start = next_boundary(self._frame, self._origin, self._grid)
        try:
            stream = self._sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                callback=self._input_callback,
            )
            self._input = stream
            if self._latency_seconds is not None:
                latency = self._latency_seconds
            else:
                latency = float(stream.latency) + float(self._output.latency)
            with self._lock:
                self._latency_frames = int(round(latency * self.sample_rate))
            stream.start()
        except Exception as exc:
            log.warning("cannot open microphone: %s", exc)
            self._discard_input()
            with self._lock:
                self._rec_start = None
            return False
        return True

    def stop_recording(self) -> np.ndarray | None:
        self._discard_input()
        with self._lock:
            chunks, self._chunks = self._chunks, []
            self._recorded_frames = 0
            self._rec_start = None
            self._rec_aligned = False
        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.float32)

    def recording_seconds(self) -> float:
        with self._lock:
            return self._recorded_frames / self.sample_rate

    def recording_wait(self) -> float:
        with self._lock:
            if self._rec_start is None or self._rec_aligned:
                return 0.0
            return max(0, self._rec_start - self._frame) / self.sample_rate

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
        data = np.asarray(data, dtype=np.float32)
        with self._lock:
            now = self._frame
            if not (loop and self._grid is not None):
                self._voices[pad] = _Voice(data, loop, start=now)
                return
            old = self._voices.get(pad)
            if old is not None and old.synced and old.end is not None and old.data is data:
                old.end = None  # pressed again before it stopped: keep it going
                return
            if self._grid_running(exclude=pad):
                start = next_boundary(now, self._origin, self._grid)
            else:
                # Nothing else on the grid: start right away and anchor it here.
                self._origin = now
                start = now
            self._voices[pad] = _Voice(data, True, start=start, synced=True)

    def stop(self, pad: int, at_boundary: bool = False) -> None:
        with self._lock:
            voice = self._voices.get(pad)
            if voice is None:
                return
            now = self._frame
            if at_boundary and voice.synced and self._grid is not None and voice.start <= now:
                end = next_boundary(now, self._origin, self._grid)
                if end > now:
                    voice.end = end
                    return
            del self._voices[pad]

    def stop_all(self) -> None:
        with self._lock:
            self._voices.clear()

    def playing_pads(self) -> set[int]:
        with self._lock:
            return set(self._voices)

    def play_effect(self, data: np.ndarray) -> None:
        with self._lock:
            self._effects.append(_Voice(np.asarray(data, dtype=np.float32), loop=False, start=self._frame))

    def close(self) -> None:
        self._discard_input()
        try:
            self._output.stop()
            self._output.close()
        except Exception as exc:
            log.warning("closing audio output failed: %s", exc)
