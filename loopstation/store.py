"""Event store: append-only JSONL log with snapshots and archiving.

Files (below ``log_dir``):

- ``events.jsonl``: the active log. It always starts with a snapshot.
- ``archive/events-<firstseq>-<lastseq>.jsonl``: older events moved out of
  the active log, always cut at a snapshot boundary.

Every event is flushed and fsynced before ``append`` returns, so a crash
loses at most the line that was being written. A torn last line is dropped
when the log is loaded; a broken line anywhere else is reported as an error
instead of being silently discarded.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from loopstation import events as ev
from loopstation.state import AppState, apply, ensure_pads, replay

log = logging.getLogger(__name__)

LOG_NAME = "events.jsonl"
ARCHIVE_DIR = "archive"
_ARCHIVE_RE = re.compile(r"^events-(\d+)-(\d+)\.jsonl$")


class StoreCorruptError(RuntimeError):
    """The active log contains a broken line that is not the last one."""


def _fsync_dir(path: Path) -> None:
    """Fsync a directory so that a rename inside it is durable (POSIX only)."""
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path: Path, lines: list[str]) -> None:
    """Replace ``path`` with ``lines`` atomically (temp file, fsync, rename)."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class EventStore:
    """Owns the event log and the current state derived from it."""

    def __init__(
        self,
        log_dir: Path,
        pad_count: int,
        snapshot_interval: int = 100,
        max_active_events: int = 2000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if snapshot_interval < 1:
            raise ValueError("snapshot_interval must be >= 1")
        if max_active_events < 2 * (snapshot_interval + 1):
            raise ValueError("max_active_events must hold at least two snapshot segments")
        self.log_dir = Path(log_dir)
        self.log_path = self.log_dir / LOG_NAME
        self.archive_dir = self.log_dir / ARCHIVE_DIR
        self.pad_count = pad_count
        self.snapshot_interval = snapshot_interval
        self.max_active_events = max_active_events
        self._clock = clock

        # Raw lines and types of the active log, kept in memory so archiving
        # does not need to re-read the file.
        self._lines: list[str] = []
        self._types: list[str] = []
        self._since_snapshot = 0
        self._last_seq = 0
        self._state = AppState.empty(pad_count)
        self._handle: TextIO | None = None

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ API

    @property
    def state(self) -> AppState:
        """The current state. Treat it as read-only."""
        return self._state

    @property
    def last_seq(self) -> int:
        return self._last_seq

    @property
    def active_line_count(self) -> int:
        return len(self._lines)

    def append(self, type_: str, pad: int | None = None, data: dict[str, Any] | None = None) -> ev.Event:
        """Write one event durably, update the state and return the event.

        After every ``snapshot_interval`` non-snapshot events a snapshot is
        written and the active log is trimmed if needed.
        """
        if type_ == ev.SNAPSHOT:
            raise ValueError("snapshots are written by the store itself")
        event = self._write(type_, pad, data or {})
        self._state = apply(self._state, event)
        self._since_snapshot += 1
        if self._since_snapshot >= self.snapshot_interval:
            self._write_snapshot()
            self._archive_if_needed()
        return event

    def close(self) -> None:
        """Close the log file. The store must not be used afterwards."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    # ------------------------------------------------------------- internals

    def _load(self) -> None:
        events: list[ev.Event] = []
        if self.log_path.exists():
            events = self._read_log()
        if not events:
            # Fresh start (or a log that only held a torn line): continue the
            # sequence after the archive, if there is one, and begin with a
            # genesis snapshot of the empty state.
            self._last_seq = self._max_archived_seq()
            self._lines, self._types = [], []
            _write_atomic(self.log_path, [])
            self._open_handle()
            self._state = AppState.empty(self.pad_count)
            self._write_snapshot()
            return

        self._last_seq = events[-1].seq
        self._state = replay(events, self.pad_count)
        self._since_snapshot = 0
        for event in reversed(events):
            if event.type == ev.SNAPSHOT:
                break
            self._since_snapshot += 1
        self._open_handle()
        # A crash between an event and its snapshot (or changed limits) can
        # leave the log over budget; repair that right away.
        if self._since_snapshot >= self.snapshot_interval:
            self._write_snapshot()
        self._archive_if_needed()

    def _read_log(self) -> list[ev.Event]:
        """Read the active log, dropping a torn last line (crash recovery)."""
        text = self.log_path.read_bytes().decode("utf-8", errors="replace")
        raw_lines = text.split("\n")
        # Non-blank lines; only the last of them may be broken (torn write).
        candidates = [i for i, line in enumerate(raw_lines) if line.strip()]
        events: list[ev.Event] = []
        lines: list[str] = []
        for i in candidates:
            line = raw_lines[i].strip()
            try:
                event = ev.Event.from_json(line)
            except ev.EventFormatError as exc:
                if i == candidates[-1]:
                    log.warning("dropping torn last line of %s: %s", self.log_path, exc)
                    break
                raise StoreCorruptError(
                    f"{self.log_path}: Zeile {i + 1} ist beschädigt ({exc})"
                ) from exc
            if events and event.seq <= events[-1].seq:
                raise StoreCorruptError(
                    f"{self.log_path}: Zeile {i + 1} hat seq {event.seq}, "
                    f"erwartet > {events[-1].seq}"
                )
            events.append(event)
            lines.append(line)
        # Rewrite the file if it differs from its clean form (torn last line,
        # missing final newline, blank lines).
        repaired = "".join(line + "\n" for line in lines) != text
        if repaired:
            _write_atomic(self.log_path, lines)
        self._lines = lines
        self._types = [event.type for event in events]
        return events

    def _max_archived_seq(self) -> int:
        if not self.archive_dir.is_dir():
            return 0
        highest = 0
        for path in self.archive_dir.iterdir():
            match = _ARCHIVE_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(2)))
        return highest

    def _open_handle(self) -> None:
        self.close()
        # Long-lived append handle, closed in close(); a context manager does not fit.
        self._handle = open(self.log_path, "a", encoding="utf-8", newline="\n")  # noqa: SIM115

    def _write(self, type_: str, pad: int | None, data: dict[str, Any]) -> ev.Event:
        assert self._handle is not None, "store is closed"
        event = ev.Event(
            seq=self._last_seq + 1,
            ts=ev.format_ts(self._clock()),
            type=type_,
            pad=pad,
            data=data,
        )
        line = event.to_json()
        self._handle.write(line + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._last_seq = event.seq
        self._lines.append(line)
        self._types.append(type_)
        return event

    def _write_snapshot(self) -> None:
        event = self._write(ev.SNAPSHOT, None, {"state": self._state.to_dict()})
        self._state = ensure_pads(apply(self._state, event), self.pad_count)
        self._since_snapshot = 0

    def _archive_if_needed(self) -> None:
        """Move whole snapshot segments to the archive while the log is too long.

        The threshold leaves room for one more full segment (events plus its
        snapshot), so the active log never exceeds ``max_active_events``.
        """
        threshold = self.max_active_events - self.snapshot_interval - 1
        while len(self._lines) > threshold:
            snapshots = [i for i, t in enumerate(self._types) if t == ev.SNAPSHOT]
            if len(snapshots) < 2:
                return
            cut = snapshots[1]
            moved = self._lines[:cut]
            first = ev.Event.from_json(moved[0]).seq
            last = ev.Event.from_json(moved[-1]).seq
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            # 1) write the archive file durably, 2) atomically swap the active
            # log. A crash between both steps leaves the moved events in both
            # files, which is harmless: loading only reads the active log.
            _write_atomic(self.archive_dir / f"events-{first:08d}-{last:08d}.jsonl", moved)
            self.close()
            _write_atomic(self.log_path, self._lines[cut:])
            self._lines = self._lines[cut:]
            self._types = self._types[cut:]
            self._open_handle()
