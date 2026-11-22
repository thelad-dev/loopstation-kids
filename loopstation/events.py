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

# The event types. Nothing else is ever written to the log.
RECORD_START = "record_start"
RECORD_STOP = "record_stop"
PLAY = "play"
LOOP_ON = "loop_on"
LOOP_OFF = "loop_off"
DELETE_PAD = "delete_pad"
DELETE_ALL = "delete_all"
# ``undo {data: {target}}`` takes back the top of the undo stack; with a
# ``pad`` it takes back the latest change of just that pad. ``redo`` brings an
# undone change back (a ``pad`` works the same way). Logs without ``redo`` and
# without a pad on ``undo`` read as before.
UNDO = "undo"
REDO = "redo"
RESTORE_PAD = "restore_pad"
SNAPSHOT = "snapshot"
# Loop grid: ``master_set {data: {frames, rate}}`` records the loop length
# (one bar) that the first sound of a session defines; ``session_start`` marks
# that the last pad was emptied, so the next sound starts a new session with a
# new loop length. Both were added later; logs without them read as before.
# With the onset grid ``master_set`` also says where the bar came from:
# ``{frames, rate, source: "onset"|"duration"|"parent_bpm"|"free_pad",
# signature: "4/4", pad}``. A ``master_set`` without ``source`` reads as
# ``duration`` (the first recording's length was the bar). ``record_stop`` of
# the recording that sets the grid may carry ``grid`` (``onset``, ``duration``
# or ``none``, the outcome of the onset analysis) and ``shift`` (frames the
# recording was moved circularly to its first onset; the WAV already is moved).
MASTER_SET = "master_set"
SESSION_START = "session_start"
# Free pad mode: ``pad_free {pad, data: {free: bool}}`` puts a pad into (or takes
# it out of) the free mode, in which its sample keeps its own length and is
# neither cut nor stretched to the loop grid. It can be undone like a content
# change. A free pad that records while the session has no grid sets one:
# ``master_set`` with ``source: "free_pad"`` (there is no second grid event).
PAD_FREE = "pad_free"
# Markers the parents set in the waveform: ``marker_set {pad, data: {sample,
# rate, frames: [...]}}`` replaces the whole marker list of one sample (an empty
# list removes them). Markers belong to the sample file, not to the pad, so undo,
# redo and the history bring the right ones back. They are an annotation of the
# parents and not on the undo stack. Logs without ``marker_set`` read as before.
MARKER_SET = "marker_set"
# A loop the parents shortened (Erweitert): ``loop_trim {pad, data: {sample, from,
# start_frames, end_frames, frames, rate}}`` puts a new sample (the part ``start_frames`` ..
# ``end_frames`` of the sample ``from`` as it played, cut or padded to ``frames``) on the pad.
# The original stays in the history, so it is a content change like a new recording: undo, redo
# and the history take it back. The markers of ``from`` move with it. It may carry ``master``
# (the new bar, when the parents let a loop that set the grid define a new one) and ``grid``
# (what the onset analysis decided for ``from``, passed on to the new sample).
LOOP_TRIM = "loop_trim"
# A loop the parents stretched between markers (Erweitert) is a ``record_stop`` with
# ``source: "markers"``, ``from`` (the sample it replaced on the pad), ``frames``, and
# (newer logs) ``root`` (the first take of the chain of such stretches, which is what was
# stretched) and ``map`` (``[[frame_in_root, frame_in_result], ...]`` for the inner piece
# boundaries; start and end map onto themselves). The next stretch of that sample maps the
# markers back over ``map`` and stretches ``root`` once. Without ``root``/``map`` (older
# logs) the sample itself is stretched; the state ignores both fields.
# Pad labels and playback shape (parents' detail panel). ``pad_name`` is an annotation
# like ``marker_set`` (not on the child's undo stack). ``pad_gain``, ``pad_start`` and
# ``pad_bars`` change what is heard and can be undone. Logs without them read as before
# (gain 1, start 0, bars = auto fit from the recording).
PAD_NAME = "pad_name"
PAD_GAIN = "pad_gain"
PAD_START = "pad_start"
PAD_BARS = "pad_bars"

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
        REDO,
        RESTORE_PAD,
        SNAPSHOT,
        MASTER_SET,
        SESSION_START,
        PAD_FREE,
        MARKER_SET,
        LOOP_TRIM,
        PAD_NAME,
        PAD_GAIN,
        PAD_START,
        PAD_BARS,
    }
)

# Events that change pad content and can therefore be undone. Playback and
# flow events (play, loops, record_start) are skipped by undo on purpose.
CONTENT_TYPES = frozenset({
    RECORD_STOP, DELETE_PAD, DELETE_ALL, RESTORE_PAD, PAD_FREE, LOOP_TRIM,
    PAD_GAIN, PAD_START, PAD_BARS,
})


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
