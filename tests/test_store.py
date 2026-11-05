"""Event store: durability, snapshots, archive limit, restart and crash recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopstation import events as ev
from loopstation.state import replay
from loopstation.store import EventStore, StoreCorruptError


def read_lines(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:  # a fresh handle, not the store's
        return [json.loads(line) for line in handle if line.strip()]


def all_events(store: EventStore) -> list[dict]:
    archived = []
    if store.archive_dir.is_dir():
        for path in sorted(store.archive_dir.glob("events-*.jsonl")):
            archived.extend(read_lines(path))
    return archived + read_lines(store.log_path)


def record(store: EventStore, pad: int, name: str) -> None:
    store.append(ev.RECORD_START, pad, {"stamp": 1})
    store.append(ev.RECORD_STOP, pad, {"sample": name, "duration": 1.0})


def test_fresh_log_starts_with_genesis_snapshot(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)
    lines = read_lines(store.log_path)
    assert [line["type"] for line in lines] == ["snapshot"]
    assert lines[0]["seq"] == 1
    assert lines[0]["ts"].endswith("Z")
    assert set(lines[0]["data"]["state"]["pads"]) == {str(i) for i in range(12)}
    store.close()


def test_every_append_is_on_disk_immediately(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)
    for i in range(5):
        event = store.append(ev.PLAY, i)
        lines = read_lines(store.log_path)
        assert lines[-1] == json.loads(event.to_json())
    seqs = [line["seq"] for line in read_lines(store.log_path)]
    assert seqs == list(range(1, 7))
    store.close()


def test_snapshot_after_exactly_100_events(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)
    for _ in range(99):
        store.append(ev.PLAY, 0)
    assert read_lines(store.log_path)[-1]["type"] == "play"
    store.append(ev.PLAY, 0)
    lines = read_lines(store.log_path)
    assert [line["type"] for line in lines].count("snapshot") == 2
    assert lines[-1]["type"] == "snapshot"
    assert lines[-1]["seq"] == 102  # genesis + 100 events + snapshot
    store.close()


def test_snapshot_contains_the_complete_state(tmp_path, clock):
    store = EventStore(tmp_path, 12, snapshot_interval=3, max_active_events=100, clock=clock)
    record(store, 4, "pad_4_1.wav")
    store.append(ev.LOOP_ON, 4)
    snapshot = read_lines(store.log_path)[-1]
    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["state"]["pads"]["4"] == {
        "sample": "pad_4_1.wav", "looping": True, "history": ["pad_4_1.wav"]
    }
    store.close()


@pytest.mark.usefixtures("fsync_off")
def test_active_log_never_exceeds_2000_lines_and_archive_is_complete(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)  # real limits: 100 / 2000
    longest = 0
    for i in range(5000):
        if i % 3 == 0:
            store.append(ev.RECORD_STOP, i % 12, {"sample": f"pad_{i % 12}_{i}.wav", "duration": 1.0})
        else:
            store.append(ev.PLAY, i % 12)
        longest = max(longest, store.active_line_count)
    assert longest <= 2000
    active = read_lines(store.log_path)
    assert len(active) <= 2000
    assert active[0]["type"] == "snapshot"  # active log always starts with a snapshot
    assert len(list(store.archive_dir.glob("events-*.jsonl"))) > 0

    seqs = [line["seq"] for line in all_events(store)]
    assert seqs == list(range(1, store.last_seq + 1))  # every seq exactly once, in order
    # 5000 events + 1 genesis + one snapshot per 100 events
    assert store.last_seq == 5000 + 1 + 50
    store.close()


@pytest.mark.usefixtures("fsync_off")
def test_small_limits_keep_the_log_bounded(tmp_path, clock):
    store = EventStore(tmp_path, 4, snapshot_interval=5, max_active_events=20, clock=clock)
    for _ in range(203):
        store.append(ev.PLAY, 1)
        assert store.active_line_count <= 20
        assert len(read_lines(store.log_path)) <= 20
    seqs = [line["seq"] for line in all_events(store)]
    assert seqs == list(range(1, store.last_seq + 1))
    store.close()


def test_restart_gives_the_same_state(tmp_path, clock):
    store = EventStore(tmp_path, 12, snapshot_interval=4, max_active_events=40, clock=clock)
    record(store, 0, "a.wav")
    record(store, 1, "b.wav")
    store.append(ev.LOOP_ON, 1)
    store.append(ev.DELETE_PAD, 0)
    record(store, 2, "c.wav")
    expected = store.state.to_dict()
    last_seq = store.last_seq
    store.close()

    again = EventStore(tmp_path, 12, snapshot_interval=4, max_active_events=40, clock=clock)
    assert again.state.to_dict() == expected
    assert again.last_seq == last_seq
    assert replay([ev.Event.from_json(json.dumps(x)) for x in read_lines(again.log_path)],
                  12).to_dict() == expected
    # numbering continues after a restart
    assert again.append(ev.PLAY, 0).seq == last_seq + 1
    again.close()


@pytest.mark.usefixtures("fsync_off")
def test_undo_after_archiving_reaches_into_the_archive(tmp_path, clock):
    store = EventStore(tmp_path, 12, snapshot_interval=5, max_active_events=20, clock=clock)
    record(store, 3, "old.wav")
    target = store.state.undo_stack[-1]["seq"]
    for _ in range(120):
        store.append(ev.PLAY, 0)
    first_active = read_lines(store.log_path)[0]["seq"]
    assert target < first_active  # the recording itself is archived
    store.close()

    store = EventStore(tmp_path, 12, snapshot_interval=5, max_active_events=20, clock=clock)
    assert store.state.undo_stack[-1]["seq"] == target
    store.append(ev.UNDO, None, {"target": target})
    assert store.state.pads[3].sample is None
    assert store.state.pads[3].history == ["old.wav"]
    store.close()


def test_torn_last_line_is_dropped(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)
    record(store, 0, "a.wav")
    expected = store.state.to_dict()
    store.close()
    with open(store.log_path, "a", encoding="utf-8") as handle:
        handle.write('{"seq": 99, "ts": "2026-11-05T12:00:00.000Z", "type": "rec')

    again = EventStore(tmp_path, 12, clock=clock)
    assert again.state.to_dict() == expected
    lines = read_lines(again.log_path)  # file was repaired: every line is valid JSON
    assert lines[-1]["type"] == "record_stop"
    assert again.append(ev.PLAY, 0).seq == 4
    again.close()


def test_broken_line_in_the_middle_is_an_error(tmp_path, clock):
    store = EventStore(tmp_path, 12, clock=clock)
    store.append(ev.PLAY, 0)
    store.append(ev.PLAY, 1)
    store.close()
    lines = store.log_path.read_text(encoding="utf-8").splitlines()
    lines[1] = "this is not json"
    store.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(StoreCorruptError, match="Zeile 2"):
        EventStore(tmp_path, 12, clock=clock)


def test_empty_log_file_gets_a_genesis_snapshot(tmp_path, clock):
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    store = EventStore(tmp_path, 12, clock=clock)
    assert [line["type"] for line in read_lines(store.log_path)] == ["snapshot"]
    store.close()


def test_crash_before_snapshot_is_repaired_on_load(tmp_path, clock):
    store = EventStore(tmp_path, 12, snapshot_interval=5, max_active_events=40, clock=clock)
    for _ in range(4):
        store.append(ev.PLAY, 0)
    store.close()
    # Simulate a crash right after the 5th event, before its snapshot.
    line = ev.Event(6, ev.format_ts(clock()), ev.PLAY, 0, {}).to_json()
    with open(store.log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    again = EventStore(tmp_path, 12, snapshot_interval=5, max_active_events=40, clock=clock)
    assert read_lines(again.log_path)[-1]["type"] == "snapshot"
    again.close()
