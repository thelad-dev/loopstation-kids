"""Loud recordings, remembered locally for the parents (plan section 7.5).

One JSON line per recording whose microphone clipped or came close. The file
stays on this machine next to the event log; nothing is sent anywhere. The
log is not part of the event store: it is only a note for the parents and
may be deleted at any time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The newest events that are kept (and shown).
KEEP = 50


@dataclass(frozen=True)
class ClipEvent:
    at: float  # Unix time of the end of the recording
    pad: int  # 0-based pad index
    peak_db: float  # microphone peak after the trim, in dB(FS); above 0 means it clipped
    clipped: bool  # the microphone clipped (as the audio engine counts it)


class ClipLog:
    """The last ``KEEP`` clip events, newest last; stored in ``path`` (``None`` = memory only)."""

    def __init__(self, path: Path | None = None, keep: int = KEEP) -> None:
        self.path = path
        self.keep = keep
        self._events: list[ClipEvent] = []
        if path is not None:
            self._load()

    def events(self) -> list[ClipEvent]:
        """Newest first."""
        return self._events[::-1]

    def add(self, event: ClipEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.keep:
            del self._events[: len(self._events) - self.keep]
        if self.path is not None:
            self._append(event)

    # ---------------------------------------------------------------- files

    def _load(self) -> None:
        assert self.path is not None
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("cannot read %s: %s", self.path, exc)
            return
        for line in lines:
            try:
                raw = json.loads(line)
                self._events.append(ClipEvent(
                    at=float(raw["at"]), pad=int(raw["pad"]),
                    peak_db=float(raw["peak_db"]), clipped=bool(raw["clipped"]),
                ))
            except (ValueError, KeyError, TypeError):
                continue  # a broken line is only a lost note
        if len(self._events) > self.keep:
            del self._events[: len(self._events) - self.keep]
            self._write_all()

    def _append(self, event: ClipEvent) -> None:
        assert self.path is not None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(self._line(event) + "\n")
        except OSError as exc:
            log.warning("cannot write %s: %s", self.path, exc)

    def _write_all(self) -> None:
        assert self.path is not None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("".join(self._line(e) + "\n" for e in self._events), encoding="utf-8")
        except OSError as exc:
            log.warning("cannot write %s: %s", self.path, exc)

    @staticmethod
    def _line(event: ClipEvent) -> str:
        return json.dumps({"at": event.at, "pad": event.pad, "peak_db": round(event.peak_db, 1),
                           "clipped": event.clipped})
