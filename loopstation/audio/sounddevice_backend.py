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

Levels: the output is the sum of all voices times the master volume (which
moves in a ramp, never in a jump), kept under the ceiling by a peak limiter
(``dynamics.PeakLimiter``). The microphone gets a trim in dB, an optional
auto gain and a soft clipper; its peak and clipped blocks are counted so the
controller can warn about a recording that is too loud.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from loopstation.audio.devices import HostApiGroup, Kind, list_devices
from loopstation.audio.dynamics import (
    CLIP_LEVEL,
    PeakLimiter,
    auto_gain_step,
    block_peak,
    db_to_gain,
    gain_to_db,
    ramp_gain,
    soft_clip,
)
from loopstation.audio.selection import WASAPI, resolve_choice
from loopstation.audio.sync import next_boundary, soften_seam

log = logging.getLogger(__name__)

# The master volume needs this long to travel its whole range, whatever the block size.
VOLUME_RAMP_SECONDS = 0.04
# Input peaks above this are rounded off by the soft clipper.
SOFT_CLIP_KNEE = 0.7
# Smallest ceiling (about -80 dBFS) so the limiter never divides by zero.
MIN_CEILING = 1e-4
# Work buffers start at this block size and grow if the device asks for more.
MIN_SCRATCH_FRAMES = 8192


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
    # The sample the caller handed in (``data`` may be a seam-faded copy).
    source: np.ndarray | None = None


class SoundDeviceAudio:
    def __init__(
        self,
        sample_rate: int,
        max_record_seconds: float,
        latency_seconds: float | None = None,
        sd: Any = None,
        clock: Callable[[], float] = time.monotonic,
        soft_seam: bool = False,
        volume: float = 1.0,
        ceiling_db: float = 0.0,
        input_gain_db: float = 0.0,
        auto_gain: bool = False,
        input_device: str = "",
        output_device: str = "",
        hostapi: str = "",
        platform: str = sys.platform,
    ) -> None:
        if sd is None:
            import sounddevice as sd  # deferred on purpose, see module docstring

        self._sd = sd
        self._platform = platform
        self._clock = clock
        self._soft_seam = soft_seam
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

        # Level chain. Output: target volume (set from the GUI thread, read by
        # the callback), the gain actually applied, the limiter and work
        # buffers that are only touched by the output callback.
        self._volume = min(1.0, max(0.0, volume))
        self._ceiling = self._ceiling_linear(ceiling_db)
        self._gain = self._volume
        self._gain_step = 1.0 / (VOLUME_RAMP_SECONDS * sample_rate)
        self._limiter = PeakLimiter(sample_rate)
        self._grow_scratch(MIN_SCRATCH_FRAMES)
        # Input: trim, auto gain (offset in dB, reset with every recording)
        # and what the controller polls.
        self._input_gain_db = input_gain_db
        self._auto_gain = auto_gain
        self._auto_db = 0.0
        self._input_peak = 0.0
        self._clip_count = 0

        # One output stream runs for the lifetime of the app and mixes all
        # voices; starting a sound is then just adding it to the table.
        # Devices: what the settings name, or the host API's default.
        self._output: Any = None
        self._input_index: int | None = None
        self._output_index: int | None = None
        self.device_notice = ""
        self.available_input = False
        self._apply_devices(input_device, output_device, hostapi)

    # -------------------------------------------------------------- devices

    def _extra_settings(self, index: int | None) -> Any:
        """WASAPI in shared mode must convert the sample rate if the device runs at another one."""
        wasapi = getattr(self._sd, "WasapiSettings", None)
        if wasapi is None or index is None:
            return None
        try:
            info = self._sd.query_devices(index)
            apis = self._sd.query_hostapis()
            if apis[int(info["hostapi"])]["name"] != WASAPI:
                return None
            return wasapi(auto_convert=True)
        except Exception as exc:
            log.info("no WASAPI settings: %s", exc)
            return None

    def _stream_args(self, index: int | None) -> dict[str, Any]:
        args: dict[str, Any] = {
            "samplerate": self.sample_rate, "channels": 1, "dtype": "float32", "device": index,
        }
        extra = self._extra_settings(index)
        if extra is not None:
            args["extra_settings"] = extra
        return args

    def _open_output(self, preferred: int | None, fallback: int | None) -> tuple[Any, int | None, str]:
        """Open and start the output stream: ``preferred``, else the system default, else ``fallback``.

        Returns the stream, the device it runs on and a hint if it is not the
        preferred one. Raises if nothing can be opened.
        """
        tries = [preferred]
        if preferred is not None:
            tries.append(None)
        if fallback not in tries:
            tries.append(fallback)
        error: Exception | None = None
        for position, index in enumerate(tries):
            try:
                stream = self._sd.OutputStream(callback=self._output_callback, **self._stream_args(index))
                stream.start()
            except Exception as exc:
                log.warning("cannot open output device %s: %s", index, exc)
                error = exc
                continue
            note = "Wiedergabegerät lässt sich nicht öffnen, Standard wird benutzt." if position else ""
            return stream, index, note
        raise error if error is not None else RuntimeError("no output device")

    def _check_input(self, index: int | None) -> bool:
        try:
            self._sd.check_input_settings(**self._stream_args(index))
        except Exception as exc:  # no input device or unsupported format
            log.info("microphone %s not usable: %s", index, exc)
            return False
        return True

    def _apply_devices(self, input_name: str, output_name: str, hostapi: str) -> None:
        """Resolve the saved devices and (re)open the output stream on them."""
        wanted_in = resolve_choice(self._sd, input_name, hostapi, "input", self._platform)
        wanted_out = resolve_choice(self._sd, output_name, hostapi, "output", self._platform)
        notes = [wanted_in.note, wanted_out.note]
        previous = self._output_index
        try:
            opened = self._open_output(wanted_out.index, previous)
        except Exception as exc:
            log.info("opening the new output next to the running one failed (%s), closing the old one first", exc)
            opened = None
        if self._output is not None:
            try:
                self._output.stop()
                self._output.close()
            except Exception as exc:
                log.warning("closing audio output failed: %s", exc)
            self._output = None
        if opened is None:
            opened = self._open_output(wanted_out.index, previous)
        self._output, self._output_index, note = opened
        notes.append(note)
        self._input_index = wanted_in.index
        self.available_input = self._check_input(self._input_index)
        if not self.available_input and self._input_index is not None:
            notes.append("Aufnahmegerät lässt sich nicht öffnen, Standard wird benutzt.")
            self._input_index = None
            self.available_input = self._check_input(None)
        self.device_notice = " ".join(n for n in notes if n)
        with self._lock:
            self._block_time = None  # the new stream has its own clock

    def select_devices(self, input_name: str, output_name: str, hostapi: str) -> str:
        """Switch to other devices or host API while the app runs; returns a hint ("" if all is as asked).

        Playing voices and the loop grid go on (the frame counter just keeps
        counting); the output stream and the microphone are closed and opened
        again, which takes a moment. A recording that is running is dropped.
        """
        self._discard_input()
        with self._lock:
            self._chunks = []
            self._recorded_frames = 0
            self._rec_start = None
            self._rec_aligned = False
        self._apply_devices(input_name, output_name, hostapi)
        return self.device_notice

    def device_groups(self, kind: Kind) -> list[HostApiGroup]:
        """Devices of ``kind`` grouped by host API, for the settings page."""
        return list_devices(self._sd, kind)

    def reported_latency_ms(self) -> float | None:
        """Microphone plus speaker delay PortAudio reports for the devices now (what "auto" uses)."""
        try:
            speaker = float(self._output.latency)
            if self._input_index is None:
                mic_info = self._sd.query_devices(kind="input")
            else:
                mic_info = self._sd.query_devices(self._input_index)
            mic = float(mic_info["default_low_input_latency"])
        except Exception as exc:
            log.info("latency not available: %s", exc)
            return None
        return (speaker + mic) * 1000

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

    def _grow_scratch(self, frames: int) -> None:
        self._mix = np.zeros(frames, dtype=np.float32)
        self._ramp = np.arange(1, frames + 1, dtype=np.float32)
        self._gains = np.empty(frames, dtype=np.float32)

    def _output_callback(self, outdata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
        if frames > len(self._mix):
            self._grow_scratch(max(frames, 2 * len(self._mix)))  # rare: a larger block than ever
        mix = self._mix[:frames]
        mix.fill(0.0)
        with self._lock:
            start = self._frame
            self._block_start = start
            self._block_time = self._clock()
            finished = [p for p, v in self._voices.items() if not self._render(mix, v, start)]
            for pad in finished:
                del self._voices[pad]
            self._effects = [e for e in self._effects if self._render(mix, e, start)]
            self._frame = start + frames
            target, ceiling = self._volume, self._ceiling
        # Master volume in a ramp, then the limiter (the only thing that
        # decides what the peak may be; the final clip inside it is rounding).
        end = ramp_gain(self._gain, target, frames, self._gain_step)
        if end != self._gain:
            gains = self._gains[:frames]
            np.multiply(self._ramp[:frames], (end - self._gain) / frames, out=gains)
            gains += self._gain
            mix *= gains
        elif end != 1.0:
            mix *= end
        self._gain = end
        self._limiter.process(mix, ceiling)
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
            chunk = self._process_input(block[:room])
            self._chunks.append(chunk)
            self._recorded_frames += len(chunk)

    def _process_input(self, part: np.ndarray) -> np.ndarray:
        """Trim, auto gain and soft clip one block; note its peak and clipping (lock held).

        Returns a new array, the microphone buffer itself is never kept.
        """
        raw_peak = block_peak(part)
        trim = db_to_gain(self._input_gain_db)
        gain = trim * db_to_gain(self._auto_db) if self._auto_gain else trim
        loud = raw_peak * gain
        clipped = raw_peak >= CLIP_LEVEL or loud >= CLIP_LEVEL
        chunk = part * np.float32(gain)
        if loud > SOFT_CLIP_KNEE:
            soft_clip(chunk, SOFT_CLIP_KNEE)
        if self._auto_gain and len(part):
            mean_square = float(np.dot(part, part)) / len(part)
            rms_db = gain_to_db(mean_square ** 0.5 * trim)
            self._auto_db = auto_gain_step(
                self._auto_db, rms_db, raw_peak * trim, clipped, len(part) / self.sample_rate
            )
        self._input_peak = max(self._input_peak, loud)
        if clipped:
            self._clip_count += 1
        return chunk

    # --------------------------------------------------------------- levels

    @staticmethod
    def _ceiling_linear(db: float) -> float:
        return max(MIN_CEILING, min(1.0, db_to_gain(db)))

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._volume = min(1.0, max(0.0, float(volume)))

    def set_ceiling_db(self, db: float) -> None:
        with self._lock:
            self._ceiling = self._ceiling_linear(db)

    def set_input_gain_db(self, db: float) -> None:
        with self._lock:
            self._input_gain_db = float(db)

    def set_auto_gain(self, enabled: bool) -> None:
        with self._lock:
            self._auto_gain = bool(enabled)
            self._auto_db = 0.0

    def poll_input_level(self) -> tuple[float, int]:
        with self._lock:
            peak, self._input_peak = self._input_peak, 0.0
            return peak, self._clip_count

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
            self._auto_db = 0.0
            self._input_peak = 0.0
            if self._grid is not None and self._grid_running():
                self._rec_start = next_boundary(self._frame, self._origin, self._grid)
        try:
            stream = self._sd.InputStream(
                callback=self._input_callback, **self._stream_args(self._input_index)
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

    def configure(
        self, max_record_seconds: float, latency_seconds: float | None, soft_seam: bool | None = None
    ) -> None:
        """Take over the recording limit, the latency and the loop seam from the settings while running."""
        with self._lock:
            self._max_frames = int((max_record_seconds + 1) * self.sample_rate)
            self._latency_seconds = latency_seconds
            if soft_seam is not None:
                self._soft_seam = soft_seam

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
        # Looped voices get the faded copy; built here, so the audio callback
        # never allocates. One-shots and the switch being off play unchanged.
        played = soften_seam(data, self.sample_rate) if loop and self._soft_seam else data
        with self._lock:
            now = self._frame
            if not (loop and self._grid is not None):
                self._voices[pad] = _Voice(played, loop, start=now, source=data)
                return
            old = self._voices.get(pad)
            if old is not None and old.synced and old.end is not None and old.source is data:
                old.end = None  # pressed again before it stopped: keep it going
                return
            if self._grid_running(exclude=pad):
                start = next_boundary(now, self._origin, self._grid)
            else:
                # Nothing else on the grid: start right away and anchor it here.
                self._origin = now
                start = now
            self._voices[pad] = _Voice(played, True, start=start, synced=True, source=data)

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
