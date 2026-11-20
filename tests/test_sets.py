"""Sets: round trip, referenced samples, atomic writing, version and ZIP checks."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import numpy as np
import pytest

from loopstation import events as ev
from loopstation import sets
from loopstation.audio.samples import save_wav
from loopstation.sets import SetCorruptError, SetError, SetTooNewError
from loopstation.state import replay
from loopstation.store import EventStore

RATE = 8000
PADS = 4


class Session:
    """A little session on disk: a store plus its samples folder."""

    def __init__(self, root: Path, clock) -> None:
        self.root = root
        self.samples = root / "samples"
        self.log_dir = root / "data"
        self.store = EventStore(self.log_dir, PADS, snapshot_interval=4, max_active_events=40, clock=clock)

    def record(self, pad: int, name: str, *, write: bool = True) -> None:
        if write:
            save_wav(self.samples / name, np.full(100, 0.1, dtype=np.float32), RATE)
        self.store.append(ev.RECORD_START, pad, {"stamp": 1})
        self.store.append(ev.RECORD_STOP, pad, {"sample": name, "duration": 1.0})

    def write_set(self, target: Path, **kwargs):
        return sets.write_set(
            target, log_dir=self.log_dir, samples_dir=self.samples, sample_rate=RATE,
            pad_count=PADS, **kwargs,
        )


@pytest.fixture
def session(tmp_path, clock) -> Session:
    s = Session(tmp_path / "live", clock)
    yield s
    s.store.close()


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def leftovers(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir() if ".tmp-" in p.name or ".old-" in p.name]


@pytest.mark.parametrize("name", ["mine.loopset", "mine"])
def test_round_trip_keeps_state_and_undo_stack(session, tmp_path, clock, name):
    session.record(0, "pad_0_1.wav")
    session.record(1, "pad_1_2.wav")
    session.record(0, "pad_0_3.wav")  # pad 0 now has history of two takes
    session.store.append(ev.MASTER_SET, None, {"frames": 100, "rate": RATE})
    settings = tmp_path / "settings.toml"
    settings.write_text("rows = 2\n", encoding="utf-8")

    manifest = session.write_set(tmp_path / name, settings_file=settings, clock=clock)
    opened = tmp_path / "opened"
    again = sets.open_set(tmp_path / name, opened)

    assert again == manifest
    assert manifest.format_version == sets.FORMAT_VERSION
    assert manifest.sample_rate == RATE and manifest.pad_count == PADS
    assert manifest.grid == {"frames": 100, "rate": RATE}
    assert (opened / "settings.toml").read_text(encoding="utf-8") == "rows = 2\n"

    restored = EventStore(opened / "data", PADS, snapshot_interval=4, max_active_events=40, clock=clock)
    try:
        assert restored.state.pads == session.store.state.pads
        assert restored.state.undo_stack == session.store.state.undo_stack
        assert restored.state.master == session.store.state.master
        assert len(restored.state.undo_stack) == 3
        # Undo keeps working in the opened set.
        restored.append(ev.UNDO, None, {"target": restored.state.undo_stack[-1]["seq"]})
        assert restored.state.pads[0].sample == "pad_0_1.wav"
    finally:
        restored.close()
    for sample in manifest.samples:
        assert (opened / "samples" / sample).is_file()


def test_set_has_exactly_the_referenced_samples(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.record(0, "pad_0_2.wav")  # old take stays in the history
    session.record(1, "pad_1_3.wav")
    session.store.append(ev.DELETE_PAD, 1, {})  # gone from the pad, kept by undo and history
    save_wav(session.samples / "pad_2_9.wav", np.zeros(10, dtype=np.float32), RATE)  # never logged
    (session.samples / "notes.txt").write_text("not a sample", encoding="utf-8")

    manifest = session.write_set(tmp_path / "set")

    expected = {"pad_0_1.wav", "pad_0_2.wav", "pad_1_3.wav"}
    assert set(manifest.samples) == expected
    assert {p.name for p in (tmp_path / "set" / "samples").iterdir()} == expected
    assert manifest.missing_samples == ()


def test_set_log_starts_at_the_last_snapshot(session, tmp_path):
    for i in range(6):
        session.record(i % PADS, f"pad_{i % PADS}_{i}.wav")
    session.write_set(tmp_path / "set")
    lines = (tmp_path / "set" / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert ev.Event.from_json(lines[0]).type == ev.SNAPSHOT
    assert all(ev.Event.from_json(line).type != ev.SNAPSHOT for line in lines[1:])
    assert replay([ev.Event.from_json(line) for line in lines], PADS).pads == session.store.state.pads


def test_missing_sample_file_is_recorded_not_fatal(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.record(1, "pad_1_2.wav", write=False)
    manifest = session.write_set(tmp_path / "x.loopset")
    assert manifest.missing_samples == ("pad_1_2.wav",)
    assert manifest.samples == ("pad_0_1.wav",)
    assert sets.open_set(tmp_path / "x.loopset", tmp_path / "w").missing_samples == ("pad_1_2.wav",)


@pytest.mark.parametrize("name", ["keep.loopset", "keep"])
def test_failed_write_leaves_existing_set_untouched(session, tmp_path, monkeypatch, name):
    session.record(0, "pad_0_1.wav")
    target = tmp_path / name
    session.write_set(target)
    before = tree(target) if target.is_dir() else target.read_bytes()

    session.record(1, "pad_1_2.wav")
    calls = {"n": 0}
    real_fsync = os.fsync

    def failing_fsync(fd):
        calls["n"] += 1
        if calls["n"] == 1:  # while the temporary set is being written, before the swap
            raise OSError("disk full")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="disk full"):
        session.write_set(target)
    monkeypatch.undo()

    assert (tree(target) if target.is_dir() else target.read_bytes()) == before
    assert leftovers(tmp_path) == []
    assert sets.open_set(target, tmp_path / "w").samples == ("pad_0_1.wav",)


def test_failed_swap_restores_the_old_folder(session, tmp_path, monkeypatch):
    session.record(0, "pad_0_1.wav")
    target = tmp_path / "keep"
    session.write_set(target)
    before = tree(target)
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst) == target and Path(src).name.startswith(".keep.tmp-"):
            raise OSError("rename failed")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError, match="rename failed"):
        session.write_set(target)
    monkeypatch.undo()
    assert tree(target) == before
    assert leftovers(tmp_path) == []


def test_overwriting_a_set_replaces_it(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    for name in ("o.loopset", "o"):
        session.write_set(tmp_path / name)
    session.record(1, "pad_1_2.wav")
    for name in ("o.loopset", "o"):
        assert session.write_set(tmp_path / name).samples == ("pad_0_1.wav", "pad_1_2.wav")
    assert leftovers(tmp_path) == []


def test_folder_target_that_is_not_a_set_is_refused(session, tmp_path):
    other = tmp_path / "photos"
    other.mkdir()
    (other / "a.jpg").write_bytes(b"x")
    with pytest.raises(SetError, match="kein Set"):
        session.write_set(other)
    assert (other / "a.jpg").read_bytes() == b"x"


def rewrite_manifest(source: Path, replacement: str) -> Path:
    """Copy a ZIP set with a different manifest."""
    out = source.with_name("changed.loopset")
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item.filename, replacement if item.filename == "manifest.toml" else src.read(item))
    return out


def test_newer_format_version_is_refused_clearly(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.write_set(tmp_path / "s.loopset")
    text = zipfile.ZipFile(tmp_path / "s.loopset").read("manifest.toml").decode()
    text = text.replace("format_version = 1", "format_version = 99")
    newer = rewrite_manifest(tmp_path / "s.loopset", text)
    with pytest.raises(SetTooNewError, match="neuere Loopstation"):
        sets.open_set(newer, tmp_path / "w")
    assert not (tmp_path / "w").exists()
    assert leftovers(tmp_path) == []
    with pytest.raises(SetTooNewError):
        sets.read_manifest(newer)


@pytest.mark.parametrize("bad", ["", "format_version = 0\n", 'format_version = "1"\n', "no toml ="])
def test_bad_manifest_is_corrupt(session, tmp_path, bad):
    session.write_set(tmp_path / "s.loopset")
    with pytest.raises(SetCorruptError):
        sets.open_set(rewrite_manifest(tmp_path / "s.loopset", bad), tmp_path / "w")


def test_damaged_zip_is_an_error_and_leaves_nothing(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.write_set(tmp_path / "s.loopset")
    raw = (tmp_path / "s.loopset").read_bytes()
    for name, content in {"cut.loopset": raw[: len(raw) // 2], "junk.loopset": b"not a zip at all"}.items():
        (tmp_path / name).write_bytes(content)
        with pytest.raises(SetCorruptError):
            sets.open_set(tmp_path / name, tmp_path / "w")
    # A flipped byte inside an entry (CRC mismatch).
    flipped = bytearray(raw)
    flipped[len(raw) // 3] ^= 0xFF
    (tmp_path / "flip.loopset").write_bytes(bytes(flipped))
    with pytest.raises(SetError):
        sets.open_set(tmp_path / "flip.loopset", tmp_path / "w")
    assert not (tmp_path / "w").exists()
    assert leftovers(tmp_path) == []


def test_zip_with_traversal_names_is_refused(session, tmp_path):
    session.write_set(tmp_path / "s.loopset")
    evil_names = (
        "../evil.wav", "samples/../../evil.wav", "/abs/evil", "samples/sub/x.wav", "samples/a\\b.wav",
    )
    for evil in evil_names:
        out = tmp_path / "evil.loopset"
        with zipfile.ZipFile(tmp_path / "s.loopset") as src, zipfile.ZipFile(out, "w") as dst:
            for item in src.infolist():
                dst.writestr(item.filename, src.read(item))
            dst.writestr(evil, b"x")
        with pytest.raises(SetCorruptError, match="Unzulässiger Eintrag"):
            sets.open_set(out, tmp_path / "w")
        assert not (tmp_path / "w").exists()
        assert not (tmp_path / "evil.wav").exists()


def test_set_missing_a_referenced_sample_is_corrupt(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.write_set(tmp_path / "s.loopset")
    out = tmp_path / "cut.loopset"
    with zipfile.ZipFile(tmp_path / "s.loopset") as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            if not item.filename.endswith(".wav"):
                dst.writestr(item.filename, src.read(item))
    with pytest.raises(SetCorruptError, match="pad_0_1.wav"):
        sets.open_set(out, tmp_path / "w")
    assert not (tmp_path / "w").exists()


def test_open_refuses_a_work_folder_that_has_content(session, tmp_path):
    session.write_set(tmp_path / "s.loopset")
    work = tmp_path / "w"
    work.mkdir()
    (work / "mine.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(SetError, match="nicht leer"):
        sets.open_set(tmp_path / "s.loopset", work)
    assert (work / "mine.txt").read_text(encoding="utf-8") == "keep"
    empty = tmp_path / "empty"
    empty.mkdir()
    sets.open_set(tmp_path / "s.loopset", empty)
    assert (empty / "manifest.toml").is_file()


def test_folder_set_with_broken_log_is_corrupt(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    session.write_set(tmp_path / "folder")
    log_path = tmp_path / "folder" / "data" / "events.jsonl"
    log_path.write_text(log_path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    with pytest.raises(SetCorruptError):
        sets.open_set(tmp_path / "folder", tmp_path / "w")
    assert not (tmp_path / "w").exists()


def test_torn_last_log_line_is_not_written_into_the_set(session, tmp_path):
    session.record(0, "pad_0_1.wav")
    with open(session.store.log_path, "a", encoding="utf-8") as handle:
        handle.write('{"seq": 99, "ts"')
    session.write_set(tmp_path / "s.loopset")
    opened = tmp_path / "w"
    sets.open_set(tmp_path / "s.loopset", opened)
    assert (opened / "data" / "events.jsonl").read_text(encoding="utf-8").endswith("}\n")


def test_unsafe_sample_name_in_the_log_blocks_writing(session, tmp_path):
    session.store.append(ev.RECORD_STOP, 0, {"sample": "../x.wav", "duration": 1.0})
    with pytest.raises(SetError, match="ungültigen Sample-Namen"):
        session.write_set(tmp_path / "s.loopset")
    assert not (tmp_path / "s.loopset").exists()


_BAD_SNAPSHOT_STATES = [
    {"pads": {"x": {}}},
    {"pads": 5},
    {"undo_stack": [{}]},
]


@pytest.mark.parametrize("bad_state", _BAD_SNAPSHOT_STATES)
def test_malformed_snapshot_in_a_set_is_corrupt_not_a_raw_error(session, tmp_path, bad_state):
    import json

    session.record(0, "pad_0_1.wav")
    session.write_set(tmp_path / "folder")
    log_path = tmp_path / "folder" / "data" / "events.jsonl"
    first = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    first["data"] = {"state": bad_state}
    log_path.write_text(json.dumps(first) + "\n", encoding="utf-8")
    with pytest.raises(SetError):
        sets.open_set(tmp_path / "folder", tmp_path / "w")


@pytest.mark.parametrize("bad_state", _BAD_SNAPSHOT_STATES)
def test_malformed_snapshot_in_the_live_log_is_a_set_error(session, tmp_path, bad_state):
    session.record(0, "pad_0_1.wav")
    last_seq = ev.Event.from_json(session.store.log_path.read_text(encoding="utf-8").splitlines()[-1]).seq
    bad = ev.Event(
        seq=last_seq + 1,
        ts="2026-01-01T00:00:00.000Z",
        type=ev.SNAPSHOT,
        data={"state": bad_state},
    )
    with open(session.store.log_path, "a", encoding="utf-8") as handle:
        handle.write(bad.to_json() + "\n")
    with pytest.raises(SetError):
        session.write_set(tmp_path / "s.loopset")


@pytest.mark.parametrize("name", ["mine.loopset", "mine"])
def test_round_trip_keeps_where_the_bar_came_from(session, tmp_path, clock, name):
    session.record(0, "pad_0_1.wav")
    master = {"frames": 100, "rate": RATE, "source": "onset", "signature": "4/4", "pad": 0}
    session.store.append(ev.MASTER_SET, None, master)

    manifest = session.write_set(tmp_path / name, clock=clock)
    assert manifest.grid == master
    # The manifest file itself carries the fields, and reading it back gives them again.
    assert sets.read_manifest(tmp_path / name).grid == master
    opened = tmp_path / "opened"
    assert sets.open_set(tmp_path / name, opened).grid == master

    restored = EventStore(opened / "data", PADS, snapshot_interval=4, max_active_events=40, clock=clock)
    try:
        assert restored.state.master == master
    finally:
        restored.close()


def test_older_grid_without_source_still_reads(session, tmp_path, clock):
    session.record(0, "pad_0_1.wav")
    session.store.append(ev.MASTER_SET, None, {"frames": 100, "rate": RATE})
    manifest = session.write_set(tmp_path / "old.loopset", clock=clock)
    assert manifest.grid == {"frames": 100, "rate": RATE}
    with zipfile.ZipFile(tmp_path / "old.loopset") as archive:
        text = archive.read("manifest.toml").decode("utf-8")
    assert "source" not in text and "pad =" not in text
