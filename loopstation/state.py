"""Application state and the pure reducer that folds events into it.

The state is never stored directly; it is always the result of replaying the
event log (starting at the latest snapshot). ``apply`` has no side effects
apart from an optional log warning for events it has to ignore.

Undo works with a stack that lives inside the state: every content event
pushes ``{"seq": <event seq>, "pads": {pad_id: previous_sample}}`` and an
``undo`` event pops the top entry and puts the previous samples back. Because
the stack is part of every snapshot, undo keeps working after old events have
been moved to the archive.

The loop grid ("master") is the length of the first sound of a session,
``{"frames": int, "rate": int}``. A ``master_set`` event sets it; it is
cleared as soon as no pad holds a sample any more (a ``session_start`` event
follows in the log). Undo entries remember the previous master under
``"master"`` whenever a content event changed it, so undoing "Alle löschen"
brings the grid back together with the samples. Logs and snapshots written
before the grid existed simply have no master.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from loopstation import events as ev

log = logging.getLogger(__name__)

# Maximum number of undo steps kept; the oldest entries are dropped first.
UNDO_LIMIT = 1000


@dataclass
class PadState:
    """State of one pad."""

    sample: str | None = None
    looping: bool = False
    # Every sample ever recorded on this pad, oldest first, without duplicates.
    history: list[str] = field(default_factory=list)


@dataclass
class AppState:
    """Complete application state."""

    pads: dict[int, PadState] = field(default_factory=dict)
    # Entries: {"seq": int, "pads": {pad_id (int): previous sample or None}}.
    # Entries are treated as immutable, so copies of the list may share them.
    undo_stack: list[dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    # Loop grid {"frames": int, "rate": int}, or None while recordings are free.
    master: dict[str, int] | None = None

    @classmethod
    def empty(cls, pad_count: int) -> AppState:
        """Return a state with ``pad_count`` empty pads."""
        return cls(pads={i: PadState() for i in range(pad_count)})

    def copy(self) -> AppState:
        """Return a copy that can be modified without touching ``self``.

        Pad objects are copied; history lists are shared and must therefore
        be replaced (never appended to in place) when they change.
        """
        return AppState(
            pads={pad_id: replace(pad) for pad_id, pad in self.pads.items()},
            undo_stack=list(self.undo_stack),
            last_seq=self.last_seq,
            master=self.master,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (pad ids become strings)."""
        return {
            "pads": {
                str(pad_id): {
                    "sample": pad.sample,
                    "looping": pad.looping,
                    "history": list(pad.history),
                }
                for pad_id, pad in sorted(self.pads.items())
            },
            "undo_stack": [_entry_to_dict(entry) for entry in self.undo_stack],
            "last_seq": self.last_seq,
            "master": None if self.master is None else dict(self.master),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppState:
        """Inverse of ``to_dict``."""
        pads = {
            int(pad_id): PadState(
                sample=pad.get("sample"),
                looping=bool(pad.get("looping", False)),
                history=list(pad.get("history", [])),
            )
            for pad_id, pad in raw.get("pads", {}).items()
        }
        undo_stack = [_entry_from_dict(entry) for entry in raw.get("undo_stack", [])]
        return cls(
            pads=pads,
            undo_stack=undo_stack,
            last_seq=int(raw.get("last_seq", 0)),
            master=parse_master(raw.get("master")),
        )

    def has_content(self) -> bool:
        """True if at least one pad holds a sample."""
        return any(pad.sample is not None for pad in self.pads.values())


def parse_master(raw: Any) -> dict[str, int] | None:
    """A valid master ``{"frames", "rate"}`` from JSON data, else None."""
    if not isinstance(raw, dict):
        return None
    frames, rate = raw.get("frames"), raw.get("rate")
    for value in (frames, rate):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return None
    return {"frames": frames, "rate": rate}


def _entry_to_dict(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "seq": entry["seq"],
        "pads": {str(p): s for p, s in sorted(entry["pads"].items())},
    }
    if "master" in entry:
        out["master"] = None if entry["master"] is None else dict(entry["master"])
    return out


def _entry_from_dict(raw: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "seq": int(raw["seq"]),
        "pads": {int(p): s for p, s in raw["pads"].items()},
    }
    # Only entries of events that changed the master carry the key.
    if "master" in raw:
        entry["master"] = parse_master(raw["master"])
    return entry


def ensure_pads(state: AppState, pad_count: int) -> AppState:
    """Return a state that has at least pads ``0..pad_count-1``.

    Pads beyond the grid (for example after the grid was made smaller) are
    kept, so making the grid larger again brings them back.
    """
    missing = [i for i in range(pad_count) if i not in state.pads]
    if not missing:
        return state
    new = state.copy()
    for i in missing:
        new.pads[i] = PadState()
    return new


def _pad(state: AppState, pad_id: int) -> PadState:
    """Get a pad of a (copied) state, creating it if it does not exist yet."""
    if pad_id not in state.pads:
        state.pads[pad_id] = PadState()
    return state.pads[pad_id]


def _push_undo(state: AppState, seq: int, previous: dict[int, str | None]) -> None:
    """Push an undo entry and enforce the stack limit."""
    state.undo_stack.append({"seq": seq, "pads": dict(previous)})
    if len(state.undo_stack) > UNDO_LIMIT:
        del state.undo_stack[: len(state.undo_stack) - UNDO_LIMIT]


def apply(state: AppState, event: ev.Event) -> AppState:
    """Return the state after ``event``. ``state`` itself is not modified."""
    if event.type == ev.SNAPSHOT:
        new = AppState.from_dict(event.data["state"])
        new.last_seq = event.seq
        return new

    new = state.copy()
    new.last_seq = event.seq
    pad_id = event.pad
    master_before = new.master

    if event.type == ev.RECORD_STOP:
        sample = event.data.get("sample")
        if sample is not None and pad_id is not None:
            pad = _pad(new, pad_id)
            _push_undo(new, event.seq, {pad_id: pad.sample})
            pad.sample = sample
            pad.looping = False
            if sample not in pad.history:
                pad.history = [*pad.history, sample]

    elif event.type == ev.DELETE_PAD:
        if pad_id is not None:
            pad = _pad(new, pad_id)
            if pad.sample is not None:
                _push_undo(new, event.seq, {pad_id: pad.sample})
                pad.sample = None
            pad.looping = False

    elif event.type == ev.DELETE_ALL:
        previous = {p: pad.sample for p, pad in new.pads.items() if pad.sample is not None}
        if previous:
            _push_undo(new, event.seq, previous)
        for pad in new.pads.values():
            pad.sample = None
            pad.looping = False

    elif event.type == ev.RESTORE_PAD:
        sample = event.data.get("sample")
        if pad_id is None:
            return new
        pad = _pad(new, pad_id)
        if sample not in pad.history:
            log.warning("restore_pad seq=%s: %r is not in the history of pad %s; ignored",
                        event.seq, sample, pad_id)
        elif sample != pad.sample:
            _push_undo(new, event.seq, {pad_id: pad.sample})
            pad.sample = sample
            pad.looping = False

    elif event.type == ev.UNDO:
        target = event.data.get("target")
        if not new.undo_stack or new.undo_stack[-1]["seq"] != target:
            log.warning("undo seq=%s: target %r is not on top of the undo stack; ignored",
                        event.seq, target)
            return new
        entry = new.undo_stack.pop()
        for p, previous_sample in entry["pads"].items():
            pad = _pad(new, p)
            # A pad whose sound changes (or disappears) stops looping.
            if pad.sample != previous_sample or previous_sample is None:
                pad.looping = False
            pad.sample = previous_sample
        if "master" in entry:
            new.master = entry["master"]

    elif event.type == ev.LOOP_ON:
        if pad_id is not None:
            pad = _pad(new, pad_id)
            if pad.sample is not None:
                pad.looping = True

    elif event.type == ev.LOOP_OFF and pad_id is not None:
        _pad(new, pad_id).looping = False

    elif event.type == ev.MASTER_SET:
        master = parse_master(event.data)
        if master is None:
            log.warning("master_set seq=%s: invalid data %r; ignored", event.seq, event.data)
        else:
            new.master = master

    elif event.type == ev.SESSION_START:
        new.master = None

    # record_start and play are logged for the record only; they do not
    # change the state apart from last_seq.

    if new.master is not None and not new.has_content():
        new.master = None  # the grid is free again once every pad is empty
    if new.master != master_before and new.undo_stack and new.undo_stack[-1]["seq"] == event.seq:
        # Remember the previous grid so that undoing this event restores it.
        new.undo_stack[-1] = {**new.undo_stack[-1], "master": master_before}
    return new


def replay(events: Iterable[ev.Event], pad_count: int) -> AppState:
    """Fold events into a state, starting at the last snapshot.

    Events before the last snapshot are not needed because the snapshot
    already contains their effect.
    """
    event_list = list(events)
    start = 0
    for index in range(len(event_list) - 1, -1, -1):
        if event_list[index].type == ev.SNAPSHOT:
            start = index
            break
    state = AppState.empty(pad_count)
    for event in event_list[start:]:
        state = apply(state, event)
    return ensure_pads(state, pad_count)
