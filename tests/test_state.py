"""Reducer and replay: the heart of the event sourcing."""

from __future__ import annotations

import json

from loopstation import events as ev
from loopstation.state import UNDO_LIMIT, AppState, apply, replay


class Log:
    """Builds events with increasing seq and folds them like the store does."""

    def __init__(self, pad_count: int = 12) -> None:
        self.events: list[ev.Event] = []
        self.state = AppState.empty(pad_count)
        self.pad_count = pad_count

    def add(self, type_: str, pad: int | None = None, **data) -> ev.Event:
        event = ev.Event(len(self.events) + 1, "2026-11-05T12:00:00.000Z", type_, pad, data)
        self.events.append(event)
        self.state = apply(self.state, event)
        return event

    def record(self, pad: int, name: str) -> ev.Event:
        self.add(ev.RECORD_START, pad, stamp=1)
        return self.add(ev.RECORD_STOP, pad, sample=name, duration=1.0)

    def snapshot(self) -> ev.Event:
        return self.add(ev.SNAPSHOT, None, state=self.state.to_dict())

    def undo(self) -> ev.Event:
        return self.add(ev.UNDO, None, target=self.state.undo_stack[-1]["seq"])


def samples(state: AppState) -> dict[int, str | None]:
    return {p: pad.sample for p, pad in state.pads.items()}


def test_event_json_roundtrip():
    event = ev.Event(42, "2026-11-05T12:34:56.789Z", ev.RECORD_STOP, 3,
                     {"sample": "pad_3_1793878085123.wav", "duration": 2.4})
    line = event.to_json()
    assert json.loads(line)["type"] == "record_stop"
    assert ev.Event.from_json(line) == event
    assert ev.format_ts(0) == "1970-01-01T00:00:00.000Z"


def test_record_stop_sets_sample_and_history():
    log = Log()
    log.record(3, "a.wav")
    pad = log.state.pads[3]
    assert pad.sample == "a.wav" and pad.history == ["a.wav"]
    assert log.state.undo_stack[-1]["pads"] == {3: None}


def test_record_stop_without_sample_changes_nothing():
    log = Log()
    log.add(ev.RECORD_START, 1, stamp=5)
    log.add(ev.RECORD_STOP, 1, sample=None, duration=0.1)
    assert log.state.pads[1].sample is None
    assert log.state.undo_stack == []


def test_play_and_loops_do_not_touch_undo_stack():
    log = Log()
    log.record(0, "a.wav")
    stack = list(log.state.undo_stack)
    log.add(ev.PLAY, 0)
    log.add(ev.LOOP_ON, 0)
    assert log.state.pads[0].looping
    log.add(ev.LOOP_OFF, 0)
    log.add(ev.RECORD_START, 0, stamp=9)
    assert log.state.undo_stack == stack
    assert not log.state.pads[0].looping


def test_loop_on_needs_a_sample():
    log = Log()
    log.add(ev.LOOP_ON, 5)
    assert not log.state.pads[5].looping


def test_delete_pad_and_undo():
    log = Log()
    log.record(2, "a.wav")
    log.add(ev.LOOP_ON, 2)
    log.add(ev.DELETE_PAD, 2)
    assert log.state.pads[2].sample is None
    assert not log.state.pads[2].looping
    assert log.state.pads[2].history == ["a.wav"]
    log.undo()
    assert log.state.pads[2].sample == "a.wav"
    assert not log.state.pads[2].looping


def test_delete_empty_pad_adds_no_undo_entry():
    log = Log()
    log.add(ev.DELETE_PAD, 4)
    log.add(ev.DELETE_ALL)
    assert log.state.undo_stack == []


def test_undo_over_several_steps():
    log = Log()
    log.record(0, "a1.wav")
    log.record(0, "a2.wav")
    log.record(1, "b1.wav")
    assert samples(log.state)[0] == "a2.wav"
    log.undo()
    assert samples(log.state)[1] is None
    log.undo()
    assert samples(log.state)[0] == "a1.wav"
    log.undo()
    assert samples(log.state)[0] is None
    assert log.state.undo_stack == []
    # history survives every undo
    assert log.state.pads[0].history == ["a1.wav", "a2.wav"]
    assert log.state.pads[1].history == ["b1.wav"]


def test_undo_delete_all_restores_every_pad():
    log = Log()
    log.record(0, "a.wav")
    log.record(5, "f.wav")
    log.add(ev.LOOP_ON, 5)
    log.add(ev.DELETE_ALL)
    assert all(s is None for s in samples(log.state).values())
    assert not log.state.pads[5].looping
    log.undo()
    assert samples(log.state)[0] == "a.wav"
    assert samples(log.state)[5] == "f.wav"


def test_restore_pad_and_undo_after_restore():
    log = Log()
    log.record(7, "v1.wav")
    log.record(7, "v2.wav")
    log.add(ev.RESTORE_PAD, 7, sample="v1.wav")
    assert log.state.pads[7].sample == "v1.wav"
    log.undo()
    assert log.state.pads[7].sample == "v2.wav"


def test_restore_unknown_sample_is_ignored():
    log = Log()
    log.record(7, "v1.wav")
    before = log.state.to_dict()
    log.add(ev.RESTORE_PAD, 7, sample="other.wav")
    after = log.state.to_dict()
    assert before["pads"] == after["pads"]
    assert before["undo_stack"] == after["undo_stack"]


def test_undo_with_wrong_target_is_ignored():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.UNDO, None, target=999)
    assert log.state.pads[0].sample == "a.wav"
    assert len(log.state.undo_stack) == 1


def test_apply_does_not_modify_its_input():
    log = Log()
    log.record(0, "a.wav")
    before = log.state.to_dict()
    apply(log.state, ev.Event(99, "x", ev.DELETE_ALL, None, {}))
    assert log.state.to_dict() == before


def test_undo_stack_is_capped():
    log = Log(pad_count=1)
    for i in range(UNDO_LIMIT + 5):
        log.add(ev.RECORD_STOP, 0, sample=f"s{i}.wav", duration=1.0)
    assert len(log.state.undo_stack) == UNDO_LIMIT
    assert log.state.undo_stack[0]["pads"] == {0: "s4.wav"}


def test_snapshot_roundtrip_through_json():
    log = Log()
    log.record(0, "a.wav")
    log.record(11, "l.wav")
    log.add(ev.LOOP_ON, 11)
    log.add(ev.DELETE_PAD, 0)
    raw = json.loads(json.dumps(log.state.to_dict()))
    restored = AppState.from_dict(raw)
    assert restored == log.state


def test_snapshot_event_replaces_state():
    log = Log()
    log.record(1, "b.wav")
    snap = log.snapshot()
    other = apply(AppState.empty(12), snap)
    assert other.pads[1].sample == "b.wav"
    assert other.last_seq == snap.seq


def test_replay_from_last_snapshot_equals_full_replay():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.snapshot()
    log.add(ev.LOOP_ON, 1)
    log.add(ev.DELETE_PAD, 0)
    log.snapshot()
    log.record(2, "c.wav")
    log.undo()
    log.undo()
    full = AppState.empty(12)
    for event in log.events:
        full = apply(full, event)
    from_snapshot = replay(log.events, 12)
    last_snapshot = max(i for i, e in enumerate(log.events) if e.type == ev.SNAPSHOT)
    tail_only = replay(log.events[last_snapshot:], 12)
    assert from_snapshot.to_dict() == full.to_dict() == log.state.to_dict()
    assert tail_only.to_dict() == full.to_dict()
    assert from_snapshot.pads[0].sample == "a.wav"  # second undo brought it back


def test_replay_keeps_pads_outside_a_smaller_grid():
    log = Log(pad_count=12)
    log.record(11, "l.wav")
    state = replay(log.events, 4)
    assert state.pads[11].sample == "l.wav"
    assert set(range(4)) <= set(state.pads)


def test_replay_adds_pads_for_a_larger_grid():
    log = Log(pad_count=4)
    log.record(0, "a.wav")
    log.snapshot()
    state = replay(log.events, 16)
    assert set(state.pads) == set(range(16))
