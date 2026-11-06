"""Shared fakes and fixtures. No test needs an audio device or a Launchpad."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# GUI tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeClock:
    """Manually advanced clock (seconds since the epoch)."""

    def __init__(self, start: float = 1_793_878_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeAudio:
    """In-memory audio backend that records every call.

    A recording yields ``clock elapsed * sample_rate`` frames of a quiet sine,
    so the recording length follows the fake clock.
    """

    def __init__(self, clock: FakeClock, sample_rate: int = 8000, available_input: bool = True) -> None:
        self.clock = clock
        self.sample_rate = sample_rate
        self.available_input = available_input
        self.voices: dict[int, tuple[np.ndarray, bool]] = {}
        self.effects: list[np.ndarray] = []
        self.calls: list[tuple[Any, ...]] = []
        self._record_start: float | None = None
        self.closed = False
        # Loop grid as set by the controller; the timing itself is tested
        # against SoundDeviceAudio with a stand-in device.
        self.grid: int | None = None
        self.wait = 0.0  # what recording_wait() reports
        self.boundary_in: float | None = None  # what next_boundary_in() reports
        self.pending: set[int] = set()

    def start_recording(self) -> bool:
        if not self.available_input:
            return False
        self.calls.append(("start_recording",))
        self._record_start = self.clock()
        return True

    def stop_recording(self) -> np.ndarray | None:
        self.calls.append(("stop_recording",))
        if self._record_start is None:
            return None
        frames = int(round((self.clock() - self._record_start) * self.sample_rate))
        self._record_start = None
        if frames <= 0:
            return None
        t = np.arange(frames, dtype=np.float32) / self.sample_rate
        return (0.25 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    def recording_seconds(self) -> float:
        return 0.0 if self._record_start is None else self.clock() - self._record_start

    def recording_wait(self) -> float:
        return self.wait if self._record_start is not None else 0.0

    def set_grid(self, frames: int | None) -> None:
        self.calls.append(("set_grid", frames))
        self.grid = frames

    def next_boundary_in(self) -> float | None:
        return self.boundary_in

    def pending_pads(self) -> set[int]:
        return set(self.pending)

    def play(self, pad: int, data: np.ndarray, loop: bool) -> None:
        self.calls.append(("play", pad, loop))
        self.voices[pad] = (data, loop)

    def stop(self, pad: int, at_boundary: bool = False) -> None:
        self.calls.append(("stop", pad, at_boundary))
        self.voices.pop(pad, None)

    def stop_all(self) -> None:
        self.voices.clear()

    def playing_pads(self) -> set[int]:
        return set(self.voices)

    def finish(self, pad: int) -> None:
        """Simulate a one-shot sound reaching its end."""
        self.voices.pop(pad, None)

    def play_effect(self, data: np.ndarray) -> None:
        self.effects.append(data)

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeMessage:
    type: str
    note: int = 0
    velocity: int = 0
    data: tuple[int, ...] = ()


def fake_message(kind: str, **fields: Any) -> FakeMessage:
    if "data" in fields:
        fields["data"] = tuple(fields["data"])
    return FakeMessage(kind, **fields)


@dataclass
class FakeMidiPort:
    name: str
    pending: list[FakeMessage] = field(default_factory=list)
    sent: list[FakeMessage] = field(default_factory=list)
    fail_send: bool = False
    closed: bool = False

    def iter_pending(self):
        while self.pending:
            yield self.pending.pop(0)

    def send(self, message: FakeMessage) -> None:
        if self.fail_send:
            raise OSError("device gone")
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


class FakeMidiPorts:
    """Fake ``MidiPorts`` with configurable port names."""

    def __init__(self, inputs: list[str], outputs: list[str] | None = None) -> None:
        self.inputs = inputs
        self.outputs = outputs if outputs is not None else list(inputs)
        self.opened: dict[str, FakeMidiPort] = {}

    def input_names(self) -> list[str]:
        return list(self.inputs)

    def output_names(self) -> list[str]:
        return list(self.outputs)

    def open_input(self, name: str) -> FakeMidiPort:
        port = FakeMidiPort(name)
        self.opened["in:" + name] = port
        return port

    def open_output(self, name: str) -> FakeMidiPort:
        port = FakeMidiPort(name)
        self.opened["out:" + name] = port
        return port


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fsync_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip fsync in tests that write thousands of events (speed only)."""
    monkeypatch.setattr(os, "fsync", lambda fd: None)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_settings(tmp_path: Path, **overrides: Any):
    from loopstation.config import Settings

    values: dict[str, Any] = {"data_dir": tmp_path, "sample_rate": 8000, "sound_effects": True}
    values.update(overrides)
    return Settings(**values)


class FakeStream:
    """A PortAudio stream whose callback the test calls itself."""

    def __init__(self, callback: Any, latency: float) -> None:
        self.callback = callback
        self.latency = latency
        self.active = False
        self.closed = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    """Stand-in for the ``sounddevice`` module plus a simple sound card.

    ``step()`` renders one output block and then hands one microphone block
    of the same size to the input callback, like a duplex sound card. The
    microphone hears the frames that were audible ``delay`` frames before:
    after the output block ``[F, F + block)`` it delivers what was audible at
    frames ``[F - delay - block, F - delay)``: the rendered output itself
    (``loopback``, a speaker next to the microphone) plus ``voice(frames)``
    (whatever the child does at those frames). With a frozen clock the
    backend maps that block to ``[F - latency - block, F - latency)``, so a
    latency setting equal to ``delay`` lines everything up exactly.
    """

    def __init__(
        self,
        block: int = 100,
        delay: int = 0,
        input_latency: float = 0.0,
        output_latency: float = 0.0,
        has_input: bool = True,
        loopback: bool = False,
    ) -> None:
        self.block = block
        self.delay = delay
        self.input_latency = input_latency
        self.output_latency = output_latency
        self.has_input = has_input
        self.loopback = loopback
        self.voice: Any = None  # callable(frames: np.ndarray) -> np.ndarray
        self.mic_late_blocks = 0  # blocks the microphone stays silent after opening
        self.output: FakeStream | None = None
        self.input: FakeStream | None = None
        self.rendered: list[np.ndarray] = []
        self._mic_skipped = 0

    # -- sounddevice API used by SoundDeviceAudio

    def OutputStream(self, samplerate: int, channels: int, dtype: str, callback: Any) -> FakeStream:  # noqa: N802
        self.output = FakeStream(callback, self.output_latency)
        return self.output

    def InputStream(self, samplerate: int, channels: int, dtype: str, callback: Any) -> FakeStream:  # noqa: N802
        self.input = FakeStream(callback, self.input_latency)
        self._mic_skipped = 0
        return self.input

    def check_input_settings(self, **_kwargs: Any) -> None:
        if not self.has_input:
            raise RuntimeError("no input device")

    # -- the sound card

    @property
    def frame(self) -> int:
        return sum(len(b) for b in self.rendered)

    def output_signal(self) -> np.ndarray:
        return np.concatenate(self.rendered) if self.rendered else np.zeros(0, dtype=np.float32)

    def step(self, blocks: int = 1) -> None:
        for _ in range(blocks):
            n = self.block
            start = self.frame
            out = np.zeros((n, 1), dtype=np.float32)
            self.output.callback(out, n, None, None)
            self.rendered.append(out[:, 0].copy())
            if self.input is None or not self.input.active:
                continue
            if self._mic_skipped < self.mic_late_blocks:
                self._mic_skipped += 1
                continue
            heard = np.arange(start - self.delay - n, start - self.delay)
            mic = np.zeros(n, dtype=np.float32)
            if self.loopback:
                signal = self.output_signal()
                inside = (heard >= 0) & (heard < len(signal))
                mic[inside] += signal[heard[inside]]
            if self.voice is not None:
                mic += self.voice(heard).astype(np.float32)
            self.input.callback(mic.reshape(-1, 1), n, None, None)

    def run_to(self, frame: int) -> None:
        """Step until ``frame`` frames have been rendered (a multiple of the block)."""
        assert frame % self.block == 0 and frame >= self.frame
        self.step((frame - self.frame) // self.block)
