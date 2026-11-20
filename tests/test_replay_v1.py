"""A session recorded with v1.0.0 plays back to the same state with the current code.

``tests/fixtures/replay_v1`` was written by the code of the tag ``v1.0.0``
(``git archive v1.0.0``, a fake clock and fake audio, 8 kHz) with
``fixtures/replay_v1/make_fixture.py``: recordings on several pads, a second
take, undo ("Zurück"), delete pad, "Alle löschen" with undo, a new round with a
new loop length, and more than 2000 events so snapshots (every 100 events) and
the archive (active log at most 2000 lines) took effect. ``expected.json`` is
the state the v1.0.0 code itself computed by replaying that log. Do not
regenerate the fixture with the current code; that would test nothing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import soundfile
from conftest import FakeAudio, FakeClock, make_settings

from loopstation import events as ev
from loopstation.controller import Controller, Mode
from loopstation.state import replay
from loopstation.store import EventStore

FIXTURE = Path(__file__).parent / "fixtures" / "replay_v1"
PADS = 12


@pytest.fixture
def expected() -> dict:
    return json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture
def session(tmp_path: Path) -> Path:
    """A copy of the frozen v1.0.0 session folder (the fixture itself stays untouched)."""
    target = tmp_path / "session"
    target.mkdir()
    shutil.copytree(FIXTURE / "data", target / "data")
    shutil.copytree(FIXTURE / "samples", target / "samples")
    return target


def open_store(session: Path, clock: FakeClock) -> EventStore:
    # The limits the app uses (store defaults): snapshot every 100, 2000 active lines.
    return EventStore(session / "data", PADS, clock=clock)


def build(session: Path, clock: FakeClock) -> Controller:
    settings = make_settings(session)
    store = open_store(session, clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    return controller


def digest(folder: Path) -> dict[str, str]:
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def all_lines(session: Path) -> list[str]:
    """Every event line of archive and active log, in order."""
    lines: list[str] = []
    for path in sorted((session / "data" / "archive").glob("events-*.jsonl")):
        lines += path.read_text(encoding="utf-8").splitlines()
    return lines + (session / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()


def view(store: EventStore) -> dict:
    """The comparable part of a state (what the v1.0.0 expectation covers, plus markers and redo)."""
    state = store.state
    return {
        "pads": {
            pad_id: (pad.sample, pad.looping, tuple(pad.history), pad.free)
            for pad_id, pad in sorted(state.pads.items())
        },
        "master": state.master,
        "undo": [(e["seq"], sorted(e["pads"].items())) for e in state.undo_stack],
        "redo": [(e["seq"], sorted(e["pads"].items())) for e in state.redo_stack],
        "markers": state.markers,
        "last_seq": state.last_seq,
    }


def test_fixture_has_snapshots_and_an_archive(session: Path, expected: dict) -> None:
    """Guard: the frozen log really exercises snapshots and archiving."""
    archive = list((session / "data" / "archive").glob("events-*.jsonl"))
    assert len(archive) >= 3
    active = (session / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert 100 < len(active) <= 2000
    assert json.loads(active[0])["type"] == ev.SNAPSHOT
    assert expected["last_seq"] > 2000


def test_new_code_reaches_the_state_v100_computed(session: Path, expected: dict) -> None:
    store = open_store(session, FakeClock())
    state = store.state

    assert store.last_seq == expected["last_seq"]
    recorded = {pad_id: pad for pad_id, pad in expected["pads"].items()}
    for pad_id in range(PADS):
        want = recorded.get(str(pad_id), {"sample": None, "looping": False, "history": []})
        pad = state.pads[pad_id]
        assert (pad.sample, pad.looping, pad.history) == (
            want["sample"],
            want["looping"],
            want["history"],
        ), f"pad {pad_id}"
        assert not pad.free  # v1.0.0 has no free pads
    assert sorted(i for i, p in state.pads.items() if p.sample is not None) == expected["recorded_pads"]

    # The loop length; a master of v1.0.0 has no source and reads as "duration".
    assert state.master is not None
    assert {k: state.master[k] for k in ("frames", "rate")} == expected["master"]
    assert state.master.get("source", "duration") == "duration"

    # Undo steps: same depth and same previous samples, also those from before the archive.
    assert len(state.undo_stack) == expected["undo_depth"]
    got = [{"pads": {str(k): v for k, v in sorted(e["pads"].items())}} for e in state.undo_stack]
    assert got == expected["undo_stack"]
    assert state.redo_stack == []
    assert state.markers == {}
    store.close()


def test_clips_are_there_and_have_the_expected_length(session: Path, expected: dict) -> None:
    store = open_store(session, FakeClock())
    names = {n for pad in store.state.pads.values() for n in pad.history}
    assert names == set(expected["clip_frames"])
    for name, frames in expected["clip_frames"].items():
        info = soundfile.info(str(session / "samples" / name))
        assert (info.frames, info.samplerate) == (frames, 8000), name
    store.close()


def test_loading_leaves_the_old_log_untouched(session: Path) -> None:
    before = digest(session)
    store = open_store(session, FakeClock())
    store.close()
    assert digest(session) == before


def test_snapshot_replay_equals_full_replay_of_archive_and_log(session: Path) -> None:
    """The snapshot the log starts with agrees with replaying every event from the archive."""
    store = open_store(session, FakeClock())
    events = [ev.Event.from_json(line) for line in all_lines(session)]
    full = replay([e for e in events if e.type != ev.SNAPSHOT], PADS)
    assert [e.seq for e in events] == sorted({e.seq for e in events})  # no gaps in the order
    assert full.to_dict()["pads"] == store.state.to_dict()["pads"]
    assert full.master == store.state.master
    assert full.undo_stack == store.state.undo_stack
    store.close()


def test_app_start_stops_loops_and_keeps_the_rest(session: Path, expected: dict) -> None:
    clock = FakeClock()
    controller = build(session, clock)
    assert expected["pads"]["5"]["looping"] is True
    assert not any(pad.looping for pad in controller.store.state.pads.values())
    assert [p for p in range(PADS) if controller.pad(p).sample] == expected["recorded_pads"]
    assert controller.can_undo()
    assert controller.store.state.master["frames"] == expected["master"]["frames"]
    controller.shutdown()


def test_work_goes_on_after_loading(session: Path, expected: dict) -> None:
    clock = FakeClock(1_793_878_100.0)
    old_lines = all_lines(session)
    controller = build(session, clock)
    pads_before = {p: controller.pad(p).sample for p in range(PADS)}

    # A new recording on an empty pad is cut to the loop length of the old session.
    assert pads_before[3] is None
    controller.press(3)
    clock.advance(0.31)
    controller.press(3)
    new = controller.pad(3).sample
    assert new is not None and new not in expected["clip_frames"]
    assert soundfile.info(str(session / "samples" / new)).frames == expected["master"]["frames"]

    # Undo and redo for one pad do not touch the others.
    controller.undo(3)
    assert controller.pad(3).sample is None
    assert {p: controller.pad(p).sample for p in range(PADS) if p != 3} == {
        p: s for p, s in pads_before.items() if p != 3
    }
    controller.redo(3)
    assert controller.pad(3).sample == new

    # Global undo walks back through steps that were written by v1.0.0, also across the archive.
    steps = len(controller.store.state.undo_stack)
    assert steps == expected["undo_depth"] + 1
    for _ in range(steps):
        controller.undo()
    assert not controller.can_undo()
    assert not any(pad.sample for pad in controller.store.state.pads.values())
    for _ in range(steps):
        controller.redo()
    assert {p: controller.pad(p).sample for p in range(PADS)} == {**pads_before, 3: new}

    # "Alle löschen" and a new round after the old session.
    controller.delete_all()
    assert not controller.store.state.has_content()
    assert controller.store.state.master is None
    controller.set_mode(Mode.RECORD)
    controller.press(0)
    clock.advance(0.7)
    controller.press(0)
    assert controller.store.state.master["frames"] == 5600
    controller.shutdown()

    # The old events are still there, in order, as the beginning of the log.
    assert all_lines(session)[: len(old_lines)] == old_lines


def test_replaying_again_gives_the_same_state(session: Path) -> None:
    clock = FakeClock(1_793_878_100.0)
    controller = build(session, clock)
    controller.press(4)
    clock.advance(0.31)
    controller.press(4)
    controller.undo(6)
    controller.redo(6)
    controller.undo()
    controller.shutdown()
    seen = view(controller.store)

    again = open_store(session, clock)
    assert view(again) == seen
    again.close()

    # And once more from a log that is only read: nothing changes on disk.
    before = digest(session)
    third = open_store(session, clock)
    assert view(third) == seen
    third.close()
    assert digest(session) == before

