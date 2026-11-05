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

    def play(self, pad: int, data: np.ndarray, loop: bool) -> None:
        self.calls.append(("play", pad, loop))
        self.voices[pad] = (data, loop)

    def stop(self, pad: int) -> None:
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
