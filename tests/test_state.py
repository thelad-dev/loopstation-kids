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


# ---------------------------------------------------------------- loop grid

MASTER = {"frames": 8000, "rate": 8000}


def test_master_set_and_cleared_with_the_last_sound():
    log = Log()
    log.record(0, "a.wav")
    assert log.state.master is None
    log.add(ev.MASTER_SET, None, **MASTER)
    log.record(1, "b.wav")
    log.add(ev.DELETE_PAD, 0)
    assert log.state.master == MASTER  # the first pad is gone, the session goes on
    log.add(ev.DELETE_PAD, 1)
    assert log.state.master is None
    log.add(ev.SESSION_START)
    assert log.state.master is None


def test_undo_brings_the_master_back_with_the_sounds():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)
    log.add(ev.SESSION_START)
    assert log.state.master is None
    log.undo()
    assert samples(log.state)[0] == "a.wav" and log.state.master == MASTER
    log.undo()  # the first recording itself: empty again, no master
    assert samples(log.state)[0] is None and log.state.master is None


def test_undo_across_two_sessions():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_PAD, 0)
    log.add(ev.SESSION_START)
    log.record(1, "b.wav")
    log.add(ev.MASTER_SET, None, frames=6000, rate=8000)
    log.undo()
    assert log.state.master is None
    log.undo()
    assert samples(log.state)[0] == "a.wav" and log.state.master == MASTER


def test_invalid_master_set_is_ignored():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, frames=0, rate=8000)
    log.add(ev.MASTER_SET, None, frames=True, rate=8000)
    assert log.state.master is None


def test_master_survives_snapshot_and_json():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)
    raw = json.loads(json.dumps(log.state.to_dict()))
    again = AppState.from_dict(raw)
    assert again == log.state
    assert again.undo_stack[-1]["master"] == MASTER


def test_old_logs_without_grid_fields_replay_unchanged():
    """A log and snapshot written before the loop grid existed."""
    old_snapshot = {
        "pads": {"0": {"sample": "a.wav", "looping": False, "history": ["a.wav"]}},
        "undo_stack": [{"seq": 2, "pads": {"0": None}}],
        "last_seq": 2,
    }
    lines = [
        {"seq": 3, "ts": "t", "type": "snapshot", "pad": None, "data": {"state": old_snapshot}},
        {"seq": 4, "ts": "t", "type": "record_start", "pad": 1, "data": {"stamp": 5}},
        {"seq": 5, "ts": "t", "type": "record_stop", "pad": 1, "data": {"sample": "b.wav", "duration": 1.0}},
        {"seq": 6, "ts": "t", "type": "undo", "pad": None, "data": {"target": 5}},
        {"seq": 7, "ts": "t", "type": "undo", "pad": None, "data": {"target": 2}},
    ]
    events = [ev.Event.from_json(json.dumps(line)) for line in lines]
    state = replay(events, 12)
    assert state.master is None
    assert samples(state)[0] is None and samples(state)[1] is None
    assert state.pads[1].history == ["b.wav"]


# ---------------------------------------------------------------- undo per pad and redo


def pad_undo(log: Log, pad: int) -> ev.Event:
    entry = next(e for e in reversed(log.state.undo_stack) if pad in e["pads"])
    return log.add(ev.UNDO, pad, target=entry["seq"])


def redo(log: Log, pad: int | None = None) -> ev.Event:
    stack = log.state.redo_stack
    entry = stack[-1] if pad is None else next(e for e in reversed(stack) if pad in e["pads"])
    return log.add(ev.REDO, pad, target=entry["seq"])


def test_pad_undo_takes_back_that_pad_even_after_other_pads_changed():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.record(2, "c.wav")
    pad_undo(log, 0)
    assert samples(log.state) == {**{i: None for i in range(12)}, 1: "b.wav", 2: "c.wav"}
    assert [e["pads"] for e in log.state.undo_stack] == [{1: None}, {2: None}]
    # The global undo neither repeats the pad undo nor loses a step.
    log.undo()
    assert samples(log.state)[2] is None and samples(log.state)[1] == "b.wav"
    log.undo()
    assert samples(log.state)[1] is None
    assert log.state.undo_stack == []
    assert log.state.pads[0].history == ["a.wav"]


def test_pad_undo_walks_back_through_the_versions_of_one_pad():
    log = Log()
    log.record(3, "v1.wav")
    log.record(4, "other.wav")
    log.record(3, "v2.wav")
    pad_undo(log, 3)
    assert log.state.pads[3].sample == "v1.wav"
    pad_undo(log, 3)
    assert log.state.pads[3].sample is None
    assert log.state.pads[4].sample == "other.wav"


def test_pad_undo_stops_the_loop_of_a_pad_whose_sound_goes():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.LOOP_ON, 0)
    pad_undo(log, 0)
    assert not log.state.pads[0].looping


def test_pad_undo_after_delete_all_restores_only_that_pad():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.DELETE_ALL)
    pad_undo(log, 1)
    assert samples(log.state)[1] == "b.wav" and samples(log.state)[0] is None
    # The rest of delete_all is still on the stack, on top.
    assert log.state.undo_stack[-1]["pads"] == {0: "a.wav"}
    log.undo()
    assert samples(log.state)[0] == "a.wav" and samples(log.state)[1] == "b.wav"
    log.undo()  # the second recording
    assert samples(log.state)[1] is None and samples(log.state)[0] == "a.wav"


def test_pad_undo_and_global_undo_in_any_order_lose_nothing():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.DELETE_ALL)
    log.undo()  # delete_all taken back as a whole
    pad_undo(log, 0)
    log.undo()
    assert all(s is None for s in samples(log.state).values())
    assert log.state.undo_stack == []


def test_pad_undo_without_a_matching_entry_or_with_wrong_target_is_ignored():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    before = log.state.to_dict()
    log.add(ev.UNDO, 5, target=2)  # pad 5 never changed
    log.add(ev.UNDO, 0, target=log.state.undo_stack[-1]["seq"])  # not the latest of pad 0
    log.add(ev.UNDO, 0)  # a pad but no target: the latest entry of the pad
    assert samples(log.state)[0] is None
    assert before["undo_stack"][1:] == log.state.to_dict()["undo_stack"]
    # Without a pad the target must name the top entry, as before.
    log.add(ev.UNDO, None)
    log.add(ev.UNDO, None, target=1)
    assert samples(log.state)[1] == "b.wav"


def test_pad_undo_restores_the_grid_only_for_the_event_that_set_it():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.record(1, "b.wav")
    pad_undo(log, 1)
    assert log.state.master == MASTER  # recording b never changed the grid

    log.add(ev.DELETE_PAD, 0)  # the last sound goes: this event clears the grid
    log.add(ev.SESSION_START)
    assert log.state.master is None
    pad_undo(log, 0)
    assert samples(log.state)[0] == "a.wav" and log.state.master == MASTER


def test_pad_undo_never_replaces_a_grid_that_exists_now():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)  # carries the old grid
    log.add(ev.SESSION_START)
    log.record(1, "b.wav")
    log.add(ev.MASTER_SET, None, frames=6000, rate=8000)
    pad_undo(log, 0)
    assert samples(log.state)[0] == "a.wav"
    assert log.state.master == {"frames": 6000, "rate": 8000}


def test_pad_undo_of_delete_all_brings_the_grid_back_once():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)
    log.add(ev.SESSION_START)
    pad_undo(log, 1)
    assert log.state.master == MASTER
    assert "master" not in log.state.undo_stack[-1]  # the grid is not restored twice
    log.undo()
    assert samples(log.state)[0] == "a.wav" and log.state.master == MASTER


def test_redo_brings_back_what_undo_took():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.undo()
    assert samples(log.state)[1] is None
    assert [e["pads"] for e in log.state.redo_stack] == [{1: "b.wav"}]
    redo(log)
    assert samples(log.state)[1] == "b.wav"
    assert log.state.redo_stack == []
    log.undo()  # and the redone step can be undone again
    assert samples(log.state)[1] is None
    redo(log)
    log.undo()
    log.undo()
    redo(log)
    redo(log)
    assert samples(log.state)[0] == "a.wav" and samples(log.state)[1] == "b.wav"


def test_every_new_content_change_clears_redo():
    for change in (
        lambda log: log.record(5, "x.wav"),
        lambda log: log.add(ev.DELETE_PAD, 0),
        lambda log: log.add(ev.DELETE_ALL),
        lambda log: log.add(ev.RESTORE_PAD, 1, sample="c.wav"),
    ):
        log = Log()
        log.record(0, "a.wav")
        log.record(1, "b.wav")
        log.record(1, "c.wav")
        log.undo()
        assert log.state.redo_stack
        change(log)
        assert log.state.redo_stack == [], change


def test_playback_and_empty_changes_keep_redo():
    log = Log()
    log.record(0, "a.wav")
    log.undo()
    log.add(ev.PLAY, 0)
    log.add(ev.LOOP_ON, 0)
    log.add(ev.LOOP_OFF, 0)
    log.add(ev.RECORD_START, 1, stamp=3)
    log.add(ev.DELETE_PAD, 7)  # empty pad: no content change
    assert len(log.state.redo_stack) == 1
    redo(log)
    assert samples(log.state)[0] == "a.wav"


def test_pad_redo_and_global_redo():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    pad_undo(log, 0)
    pad_undo(log, 1)
    redo(log, pad=0)
    assert samples(log.state)[0] == "a.wav" and samples(log.state)[1] is None
    assert [e["pads"] for e in log.state.redo_stack] == [{1: "b.wav"}]
    redo(log)
    assert samples(log.state)[1] == "b.wav"
    assert [e["pads"] for e in log.state.undo_stack][-2:] == [{0: None}, {1: None}]
    # A pad redo with a wrong target or without anything to redo is ignored.
    before = log.state.to_dict()
    log.add(ev.REDO, 0, target=999)
    log.add(ev.REDO, 3)
    log.add(ev.REDO, None, target=1)
    assert {**log.state.to_dict(), "last_seq": 0} == {**before, "last_seq": 0}


def test_redo_after_pad_undo_of_a_delete_all_entry():
    log = Log()
    log.record(0, "a.wav")
    log.record(1, "b.wav")
    log.add(ev.DELETE_ALL)
    pad_undo(log, 1)
    redo(log, pad=1)
    assert samples(log.state)[1] is None and samples(log.state)[0] is None
    log.undo()  # the pad redo itself
    assert samples(log.state)[1] == "b.wav"
    log.undo()  # what is left of delete_all
    assert samples(log.state)[0] == "a.wav"


def test_redo_of_an_undone_delete_all_restores_the_grid_state():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)
    log.add(ev.SESSION_START)
    log.undo()
    assert log.state.master == MASTER
    redo(log)
    assert samples(log.state)[0] is None and log.state.master is None
    log.undo()  # the redo can be undone: sound and grid are back
    assert samples(log.state)[0] == "a.wav" and log.state.master == MASTER


def test_redo_stack_is_capped():
    log = Log()
    for _ in range(UNDO_LIMIT + 5):
        log.record(0, "x.wav")
    for _ in range(UNDO_LIMIT):
        log.undo()
    assert len(log.state.redo_stack) == UNDO_LIMIT


def test_state_after_live_apply_equals_replay_across_snapshots():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.record(1, "b.wav")
    log.add(ev.DELETE_ALL)
    log.snapshot()
    pad_undo(log, 1)
    log.snapshot()  # a snapshot with a non-empty redo stack in the middle
    assert log.state.redo_stack
    redo(log, pad=1)
    log.undo()
    log.undo()
    log.snapshot()
    redo(log)
    pad_undo(log, 0)
    redo(log, pad=0)
    live = log.state.to_dict()
    assert replay(log.events, log.pad_count).to_dict() == live
    for start, event in enumerate(log.events):
        if event.type == ev.SNAPSHOT:
            assert replay(log.events[start:], log.pad_count).to_dict()["undo_stack"] == live["undo_stack"]
            assert replay(log.events[start:], log.pad_count).to_dict() == live


def test_redo_stack_survives_snapshot_and_json():
    log = Log()
    log.record(0, "a.wav")
    log.add(ev.MASTER_SET, None, **MASTER)
    log.add(ev.DELETE_ALL)
    log.undo()
    raw = json.loads(json.dumps(log.state.to_dict()))
    again = AppState.from_dict(raw)
    assert again == log.state
    assert again.redo_stack == log.state.redo_stack and again.redo_stack


def test_old_snapshot_without_redo_stack_and_old_undo_events_replay_unchanged():
    old_snapshot = {
        "pads": {"0": {"sample": "a.wav", "looping": False, "history": ["a.wav"]}},
        "undo_stack": [{"seq": 2, "pads": {"0": None}}],
        "last_seq": 2,
    }
    state = AppState.from_dict(old_snapshot)
    assert state.redo_stack == []
    lines = [
        {"seq": 3, "ts": "t", "type": "snapshot", "pad": None, "data": {"state": old_snapshot}},
        {"seq": 4, "ts": "t", "type": "undo", "pad": None, "data": {"target": 2}},
    ]
    replayed = replay([ev.Event.from_json(json.dumps(line)) for line in lines], 12)
    assert samples(replayed)[0] is None
    # Only the redo stack is new; the undo entries keep their old shape.
    assert replayed.undo_stack == []
    assert [e["pads"] for e in replayed.redo_stack] == [{0: "a.wav"}]


def test_redo_is_a_known_event_type_and_pad_undo_is_not():
    line = '{"seq":1,"ts":"t","type":"redo","pad":2,"data":{"target":9}}'
    assert ev.Event.from_json(line).type == ev.REDO
    assert "pad_undo" not in ev.EVENT_TYPES
