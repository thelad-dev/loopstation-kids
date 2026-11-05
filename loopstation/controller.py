"""Operating logic of the loopstation, free of any Qt dependency.

The controller turns pad presses and button clicks into events for the store
and commands for the audio engine. The GUI and the Launchpad only call into
the controller and redraw when it notifies them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import numpy as np

from loopstation import events as ev
from loopstation.audio.base import PREVIEW_VOICE, AudioBackend
from loopstation.audio.effects import start_beep, stop_beep
from loopstation.audio.samples import load_wav, parse_stamp, sample_filename, save_wav
from loopstation.config import Settings
from loopstation.state import PadState
from loopstation.store import EventStore

log = logging.getLogger(__name__)

# Recordings shorter than this are treated as accidental taps and discarded.
MIN_RECORD_SECONDS = 0.3
# How long a short hint stays in the status line.
NOTICE_SECONDS = 3.0

WHITE, YELLOW, GREEN, RED = "white", "yellow", "green", "red"


class Mode(Enum):
    PLAY = "play"
    RECORD = "record"
    LOOP = "loop"
    DELETE = "delete"
    HISTORY = "history"


@dataclass(frozen=True)
class _Recording:
    pad: int
    stamp: int
    started: float


@dataclass(frozen=True)
class HistoryEntry:
    sample: str
    recorded_at: datetime | None  # local time, None if the name has no stamp


class Controller:
    def __init__(
        self,
        store: EventStore,
        audio: AudioBackend,
        settings: Settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.audio = audio
        self.settings = settings
        self._clock = clock
        self.samples_dir = settings.samples_dir
        self.mode = Mode.PLAY
        self._recording: _Recording | None = None
        self._cache: dict[str, np.ndarray] = {}
        self._notice: tuple[str, float] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._history_listeners: list[Callable[[int], None]] = []
        self._last_playing: set[int] = set()

    # ------------------------------------------------------------ listeners

    def add_listener(self, callback: Callable[[], None]) -> None:
        """``callback()`` runs after every visible change."""
        self._listeners.append(callback)

    def add_history_listener(self, callback: Callable[[int], None]) -> None:
        """``callback(pad)`` runs when the history of a pad should be shown."""
        self._history_listeners.append(callback)

    def _changed(self) -> None:
        for callback in list(self._listeners):
            callback()

    # ---------------------------------------------------------------- info

    @property
    def pad_count(self) -> int:
        return self.settings.pad_count

    def pad(self, pad: int) -> PadState:
        return self.store.state.pads.get(pad) or PadState()

    @property
    def recording_pad(self) -> int | None:
        return self._recording.pad if self._recording else None

    def recording_remaining(self) -> float | None:
        """Seconds left until the automatic stop, or None if not recording."""
        if self._recording is None:
            return None
        elapsed = self._clock() - self._recording.started
        return max(0.0, self.settings.max_record_seconds - elapsed)

    def notice(self) -> str | None:
        """A short hint for the status line, or None."""
        if self._notice and self._clock() < self._notice[1]:
            return self._notice[0]
        return None

    def _set_notice(self, text: str) -> None:
        self._notice = (text, self._clock() + NOTICE_SECONDS)

    def can_undo(self) -> bool:
        return bool(self.store.state.undo_stack)

    def pad_colors(self) -> dict[int, str]:
        """Colour of every pad on the grid."""
        playing = self.audio.playing_pads()
        colors: dict[int, str] = {}
        for pad_id in range(self.pad_count):
            pad = self.pad(pad_id)
            if pad_id == self.recording_pad:
                colors[pad_id] = RED
            elif pad_id in playing or pad.looping:
                colors[pad_id] = GREEN
            elif pad.sample is not None:
                colors[pad_id] = YELLOW
            else:
                colors[pad_id] = WHITE
        return colors

    def history(self, pad: int) -> list[HistoryEntry]:
        """All versions ever recorded on ``pad``, oldest first."""
        entries = []
        for sample in self.pad(pad).history:
            stamp = parse_stamp(sample)
            when = datetime.fromtimestamp(stamp / 1000) if stamp is not None else None
            entries.append(HistoryEntry(sample, when))
        return entries

    # ---------------------------------------------------------------- modes

    def set_mode(self, mode: Mode) -> None:
        """Switch mode; choosing the active mode again returns to PLAY."""
        self.mode = Mode.PLAY if mode == self.mode else mode
        self._changed()

    def escape(self) -> None:
        """Leave the current mode and stop a running recording."""
        if self._recording:
            self._stop_recording()
        self.mode = Mode.PLAY
        self._changed()

    # ---------------------------------------------------------------- pads

    def press(self, pad: int) -> None:
        """Handle a press on a pad (screen or Launchpad)."""
        if not 0 <= pad < self.pad_count:
            return
        if self._recording is not None:
            recording_pad = self._recording.pad
            self._stop_recording()
            if recording_pad == pad:
                self._changed()
                return

        state = self.pad(pad)
        if self.mode == Mode.PLAY:
            if state.sample is None:
                self._start_recording(pad)
            elif pad in self.audio.playing_pads() or state.looping:
                self._stop_pad(pad)
            else:
                data = self._load(state.sample)
                if data is not None:
                    self.store.append(ev.PLAY, pad)
                    self.audio.play(pad, data, loop=False)
        elif self.mode == Mode.RECORD:
            self._start_recording(pad)
        elif self.mode == Mode.LOOP:
            if state.sample is None:
                self._start_recording(pad)
            elif state.looping:
                self._stop_pad(pad)
            else:
                data = self._load(state.sample)
                if data is not None:
                    self.store.append(ev.LOOP_ON, pad)
                    self.audio.play(pad, data, loop=True)
        elif self.mode == Mode.DELETE:
            self.audio.stop(pad)
            if state.sample is not None:
                self.store.append(ev.DELETE_PAD, pad)
            self.mode = Mode.PLAY
        elif self.mode == Mode.HISTORY:
            self.mode = Mode.PLAY
            if state.history:
                for callback in list(self._history_listeners):
                    callback(pad)
            else:
                self._set_notice("Hier gibt es noch keine Aufnahmen")
        self._changed()

    def _stop_pad(self, pad: int) -> None:
        if self.pad(pad).looping:
            self.store.append(ev.LOOP_OFF, pad)
        self.audio.stop(pad)

    # ------------------------------------------------------------ recording

    def _start_recording(self, pad: int) -> None:
        if not self.audio.available_input:
            self._set_notice("Kein Mikrofon gefunden")
            return
        self._stop_pad(pad)
        stamp = int(self._clock() * 1000)
        # Never reuse a file name, even if the clock jumped backwards.
        while (self.samples_dir / sample_filename(pad, stamp)).exists():
            stamp += 1
        if not self.audio.start_recording():
            self._set_notice("Mikrofon lässt sich nicht öffnen")
            return
        if self.settings.sound_effects:
            self.audio.play_effect(start_beep(self.audio.sample_rate))
        self.store.append(ev.RECORD_START, pad, {"stamp": stamp})
        self._recording = _Recording(pad, stamp, self._clock())

    def _stop_recording(self) -> bool:
        """Stop the running recording; return True if a sample was kept."""
        recording = self._recording
        if recording is None:
            return False
        self._recording = None
        data = self.audio.stop_recording()
        if self.settings.sound_effects:
            self.audio.play_effect(stop_beep(self.audio.sample_rate))
        duration = 0.0 if data is None else len(data) / self.audio.sample_rate
        sample: str | None = None
        if duration >= MIN_RECORD_SECONDS:
            name = sample_filename(recording.pad, recording.stamp)
            try:
                save_wav(self.samples_dir / name, data, self.audio.sample_rate)
                self._cache[name] = np.asarray(data, dtype=np.float32)
                sample = name
            except OSError as exc:
                log.error("saving %s failed: %s", name, exc)
                self._set_notice("Aufnahme konnte nicht gespeichert werden")
        else:
            self._set_notice("Zu kurz - nochmal!")
        self.store.append(
            ev.RECORD_STOP, recording.pad, {"sample": sample, "duration": round(duration, 3)}
        )
        return sample is not None

    def _load(self, sample: str) -> np.ndarray | None:
        """Sample data from the cache or from disk (None if unreadable)."""
        if sample not in self._cache:
            try:
                self._cache[sample] = load_wav(self.samples_dir / sample, self.audio.sample_rate)
            except Exception as exc:
                log.error("cannot read sample %s: %s", sample, exc)
                self._set_notice("Aufnahme fehlt")
                return None
        return self._cache[sample]

    # ------------------------------------------------------------- buttons

    def tick(self) -> None:
        """Called regularly by the GUI (about every 30 ms)."""
        changed = False
        if self._recording is not None:
            remaining = self.recording_remaining()
            if remaining is not None and remaining <= 0:
                self._stop_recording()
            # The countdown on the recording pad changes continuously.
            changed = True
        playing = self.audio.playing_pads()
        if playing != self._last_playing:
            self._last_playing = playing
            changed = True
        if changed:
            self._changed()

    def undo(self) -> None:
        """Undo the last content change (Strg+Z)."""
        # Undo during a recording cancels it: stop, then undo the new sample.
        # A recording that was too short leaves nothing to undo.
        if self._recording is not None and not self._stop_recording():
            self._changed()
            return
        stack = self.store.state.undo_stack
        if not stack:
            self._set_notice("Nichts mehr zum Zurücknehmen")
            self._changed()
            return
        top = stack[-1]
        for pad_id, previous in top["pads"].items():
            if self.pad(pad_id).sample != previous:
                self.audio.stop(pad_id)
        self.store.append(ev.UNDO, None, {"target": top["seq"]})
        self._changed()

    def restore(self, pad: int, sample: str) -> None:
        """Put an earlier version back on ``pad``."""
        if sample not in self.pad(pad).history or sample == self.pad(pad).sample:
            return
        self._stop_pad(pad)
        self.store.append(ev.RESTORE_PAD, pad, {"sample": sample})
        self._changed()

    def preview(self, sample: str) -> None:
        """Play a version once (history dialog)."""
        data = self._load(sample)
        if data is not None:
            self.audio.play(PREVIEW_VOICE, data, loop=False)

    def stop_preview(self) -> None:
        self.audio.stop(PREVIEW_VOICE)

    def delete_all(self) -> None:
        """Empty every pad (the GUI asks for confirmation first)."""
        if self._recording is not None:
            self._stop_recording()
        self.audio.stop_all()
        self.store.append(ev.DELETE_ALL)
        self.mode = Mode.PLAY
        self._changed()

    def stop_all(self) -> None:
        """Silence everything ("Alles still")."""
        if self._recording is not None:
            self._stop_recording()
        self._loops_off()
        self.audio.stop_all()
        self._changed()

    def _loops_off(self) -> None:
        for pad_id, pad in sorted(self.store.state.pads.items()):
            if pad.looping:
                self.store.append(ev.LOOP_OFF, pad_id)

    # ------------------------------------------------------------ lifecycle

    def startup(self) -> None:
        """Nothing plays after a start: switch off loops left by a crash."""
        self._loops_off()

    def shutdown(self) -> None:
        """Stop recording and loops, then release audio and the store."""
        if self._recording is not None:
            self._stop_recording()
        self._loops_off()
        self.audio.stop_all()
        self.audio.close()
        self.store.close()

