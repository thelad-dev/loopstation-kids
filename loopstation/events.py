"""Event model: the immutable facts written to the JSONL event log.

One line of the log is one event::

    {"seq": 42, "ts": "2026-11-05T12:34:56.789Z", "type": "record_stop",
     "pad": 3, "data": {"sample": "pad_3_1793878085123.wav", "duration": 2.4}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# The ten event types. Nothing else is ever written to the log.
RECORD_START = "record_start"
RECORD_STOP = "record_stop"
PLAY = "play"
LOOP_ON = "loop_on"
LOOP_OFF = "loop_off"
DELETE_PAD = "delete_pad"
DELETE_ALL = "delete_all"
UNDO = "undo"
RESTORE_PAD = "restore_pad"
SNAPSHOT = "snapshot"

EVENT_TYPES = frozenset(
    {
        RECORD_START,
        RECORD_STOP,
        PLAY,
        LOOP_ON,
        LOOP_OFF,
        DELETE_PAD,
        DELETE_ALL,
        UNDO,
        RESTORE_PAD,
        SNAPSHOT,
    }
)

# Events that change pad content and can therefore be undone. Playback and
# flow events (play, loops, record_start) are skipped by undo on purpose.
CONTENT_TYPES = frozenset({RECORD_STOP, DELETE_PAD, DELETE_ALL, RESTORE_PAD})


class EventFormatError(ValueError):
    """Raised when a log line is not a valid event."""


def format_ts(epoch_seconds: float) -> str:
    """Format a Unix timestamp as UTC ISO-8601 with milliseconds and a 'Z'."""
    moment = datetime.fromtimestamp(epoch_seconds, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Event:
    """A single immutable event."""

    seq: int
    ts: str
    type: str
    pad: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to one compact JSON line (without the trailing newline)."""
        payload = {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "pad": self.pad,
            "data": self.data,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> Event:
        """Parse and validate one JSON line; raise EventFormatError if invalid."""
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventFormatError(f"invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise EventFormatError("event is not a JSON object")

        seq = raw.get("seq")
        ts = raw.get("ts")
        type_ = raw.get("type")
        pad = raw.get("pad")
        data = raw.get("data", {})

        # bool is a subclass of int, so reject it explicitly.
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise EventFormatError(f"invalid seq: {seq!r}")
        if not isinstance(ts, str):
            raise EventFormatError(f"invalid ts: {ts!r}")
        if type_ not in EVENT_TYPES:
            raise EventFormatError(f"unknown event type: {type_!r}")
        if pad is not None and (not isinstance(pad, int) or isinstance(pad, bool) or pad < 0):
            raise EventFormatError(f"invalid pad: {pad!r}")
        if not isinstance(data, dict):
            raise EventFormatError(f"invalid data: {data!r}")
        return cls(seq=seq, ts=ts, type=type_, pad=pad, data=data)
