"""Build the frozen v1.0.0 event log of ``tests/test_replay_v1.py``.

Run it with the code of the tag ``v1.0.0`` on the import path, never with the
current code, and check which package is loaded::

    git archive v1.0.0 | tar -x -C /tmp/v100
    PYTHONPATH=/tmp/v100 python -c 'import loopstation; print(loopstation.__file__)'
    PYTHONPATH=/tmp/v100 python tests/fixtures/replay_v1/make_fixture.py /tmp/out

``/tmp/out`` then holds ``data/`` (events.jsonl, archive/), ``samples/`` and
``expected.json`` (the state the old code computes by replaying its own log).
Everything is deterministic (fake clock, fake audio, 8 kHz). The script is not
collected by pytest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile

import loopstation
from loopstation.config import Settings
from loopstation.controller import Controller, Mode
from loopstation.store import EventStore

RATE = 8000
PADS = 12


class FakeClock:
    def __init__(self, start: float = 1_793_878_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeAudio:
    """In-memory audio backend: a recording is a quiet sine as long as the clock advanced."""

    available_input = True
    sample_rate = RATE

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.voices: set[int] = set()
        self._started: float | None = None

    def start_recording(self) -> bool:
        self._started = self.clock()
        return True

    def stop_recording(self):
        if self._started is None:
            return None
        frames = int(round((self.clock() - self._started) * RATE))
        self._started = None
        if frames <= 0:
            return None
        t = np.arange(frames, dtype=np.float32) / RATE
        return (0.25 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    def recording_seconds(self) -> float:
        return 0.0 if self._started is None else self.clock() - self._started

    def recording_wait(self) -> float:
        return 0.0

    def set_grid(self, frames) -> None:
        pass

    def next_boundary_in(self):
        return None

    def pending_pads(self) -> set[int]:
        return set()

    def play(self, pad, data, loop) -> None:
        self.voices.add(pad)

    def stop(self, pad, at_boundary=False) -> None:
        self.voices.discard(pad)

    def stop_all(self) -> None:
        self.voices.clear()

    def playing_pads(self) -> set[int]:
        return set(self.voices)

    def play_effect(self, data) -> None:
        pass

    def close(self) -> None:
        pass


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)
    clock.advance(1.0)


def describe(store: EventStore, samples: Path) -> dict:
    """What the old code holds after replaying the log (the expectation of the test)."""
    state = store.state
    pads = {}
    for pad_id, pad in sorted(state.pads.items()):
        if pad.sample is None and not pad.history and not pad.looping:
            continue
        pads[str(pad_id)] = {
            "sample": pad.sample,
            "looping": pad.looping,
            "history": list(pad.history),
        }
    names = {n for p in state.pads.values() for n in p.history}
    frames = {n: soundfile.info(str(samples / n)).frames for n in sorted(names)}
    return {
        "last_seq": store.last_seq,
        "pads": pads,
        "master": state.master,
        "undo_depth": len(state.undo_stack),
        "undo_stack": [{"pads": {str(k): v for k, v in sorted(e["pads"].items())}} for e in state.undo_stack],
        "recorded_pads": sorted(i for i, p in state.pads.items() if p.sample is not None),
        "clip_frames": frames,
    }


def main(out: Path) -> None:
    print("loaded:", loopstation.__file__, file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    clock = FakeClock()
    settings = Settings(data_dir=out, sample_rate=RATE, sound_effects=False)
    store = EventStore(settings.log_dir, PADS, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()

    # Round 1: four pads (the first one sets the loop length), a second take, undo, delete.
    for pad, seconds in ((0, 0.5), (1, 0.5), (2, 0.6), (3, 0.4)):
        record(controller, clock, pad, seconds)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 1, 0.45)  # second take on pad 1
    controller.set_mode(Mode.PLAY)
    controller.undo()
    controller.set_mode(Mode.DELETE)
    controller.press(2)
    controller.undo()
    controller.delete_all()
    controller.undo()  # "Alle löschen" taken back
    controller.delete_all()

    # Round 2: a new session with a new loop length.
    for pad, seconds in ((5, 0.3), (6, 0.35), (7, 0.3)):
        record(controller, clock, pad, seconds)
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 6, 0.3)  # second take on pad 6
    controller.set_mode(Mode.PLAY)

    # Lots of cheap events (loops on and off) so that snapshots and the archive
    # kick in: more than 2000 lines in total, the early ones end up in archive/.
    controller.set_mode(Mode.LOOP)
    for _ in range(1150):
        controller.press(5)
        clock.advance(0.01)
        controller.press(5)
        clock.advance(0.01)
    controller.press(5)  # loop left running, as after a crash
    controller.set_mode(Mode.PLAY)

    # Round 3 after the archive: more content, undo steps back into old entries.
    record(controller, clock, 8, 0.3)
    controller.undo()  # pad 8 taken back, stays in its history
    record(controller, clock, 9, 0.3)
    controller.undo()
    controller.undo()  # steps back into entries that live in older snapshots
    record(controller, clock, 10, 0.3)

    store.close()  # no shutdown(): the log ends mid-session

    reopened = EventStore(settings.log_dir, PADS, clock=clock)
    expected = describe(reopened, settings.samples_dir)
    reopened.close()
    (out / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = sorted((settings.log_dir / "archive").glob("*.jsonl"))
    print("archive files:", [p.name for p in archive], file=sys.stderr)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
