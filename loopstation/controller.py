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
from loopstation.audio.sync import fit_to_grid, grace_frames, max_grid_frames
from loopstation.config import Settings
from loopstation.state import PadState
from loopstation.store import EventStore

log = logging.getLogger(__name__)

# Recordings shorter than this are treated as accidental taps and discarded.
MIN_RECORD_SECONDS = 0.3
# How long a short hint stays in the status line.
NOTICE_SECONDS = 3.0
# How long the pads show that a new session has begun.
SESSION_SHOW_SECONDS = 1.6

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
    # Cut to the loop grid when it stops (the session already has a loop length).
    synced: bool = False


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
        # Samples fitted to a grid for loop playback, keyed by (sample, grid).
        self._fitted: dict[tuple[str, int], np.ndarray] = {}
        self._grid_sent: int | None = None
        self._session_started: float | None = None
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
        self._apply_grid()
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
        if self._recording.synced and self._grid() is not None:
            # On the grid the recording counts from the loop start on and
            # ends after a whole number of loops.
            return max(0.0, self.recording_limit() - self.audio.recording_seconds())
        elapsed = self._clock() - self._recording.started
        return max(0.0, self.settings.max_record_seconds - elapsed)

    def recording_limit(self) -> float:
        """Longest possible recording in seconds (a whole number of loops on the grid)."""
        grid = self._grid() if self._recording is not None and self._recording.synced else None
        if grid is None:
            return self.settings.max_record_seconds
        rate = self.audio.sample_rate
        return max_grid_frames(grid, int(self.settings.max_record_seconds * rate)) / rate

    def recording_waits(self) -> bool:
        """True while a recording waits for the next loop start."""
        return self._recording is not None and self.audio.recording_wait() > 0

    def waiting_pads(self) -> set[int]:
        """Pads that wait for the next loop start (to record, to start or to stop a loop)."""
        pads = set(self.audio.pending_pads())
        if self.recording_waits():
            pads.add(self._recording.pad)
        return {p for p in pads if 0 <= p < self.pad_count}

    def loop_progress(self) -> float | None:
        """How far the running loops are towards their next start (0..1), None without a grid."""
        grid = self._grid()
        wait = self.audio.next_boundary_in()
        if grid is None or wait is None:
            return None
        loop_seconds = grid / self.audio.sample_rate
        return min(1.0, max(0.0, 1.0 - wait / loop_seconds))

    def notice(self) -> str | None:
        """A short hint for the status line, or None."""
        if self._notice and self._clock() < self._notice[1]:
            return self._notice[0]
        return None

    # ------------------------------------------------------------- loop grid

    def _grid(self) -> int | None:
        """Loop length in frames at the current sample rate, None while recordings are free."""
        master = self.store.state.master
        if not self.settings.loop_sync or master is None:
            return None
        rate = self.audio.sample_rate
        if master["rate"] == rate:
            return master["frames"]
        return max(1, round(master["frames"] * rate / master["rate"]))

    def _apply_grid(self) -> int | None:
        """Hand the current grid to the audio engine (only when it changed)."""
        grid = self._grid()
        if grid != self._grid_sent:
            self.audio.set_grid(grid)
            self._grid_sent = grid
        return grid

    def _set_master_from(self, pad: int) -> None:
        """The first sound of a session sets the loop length (``master_set``)."""
        state = self.store.state
        sample = self.pad(pad).sample
        if not self.settings.loop_sync or state.master is not None or sample is None:
            return
        data = self._load(sample)
        if data is None or len(data) == 0:
            return
        self.store.append(ev.MASTER_SET, None, {"frames": len(data), "rate": self.audio.sample_rate})

    def _content_changed(self, had_content: bool) -> None:
        """Log a new session once the last pad has been emptied."""
        if had_content and not self.store.state.has_content():
            self.store.append(ev.SESSION_START)
            self._session_started = self._clock()

    def session_shown(self) -> float | None:
        """Seconds since a new session began while that is still shown, else None."""
        if self._session_started is None:
            return None
        elapsed = self._clock() - self._session_started
        return elapsed if 0 <= elapsed < SESSION_SHOW_SECONDS else None

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
                self._stop_pad(pad, at_boundary=True)
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
                self._stop_pad(pad, at_boundary=True)
            else:
                data = self._loop_data(state.sample)
                if data is not None:
                    self.store.append(ev.LOOP_ON, pad)
                    self.audio.play(pad, data, loop=True)
        elif self.mode == Mode.DELETE:
            self.audio.stop(pad)
            if state.sample is not None:
                self.store.append(ev.DELETE_PAD, pad)
                self._content_changed(True)
            self.mode = Mode.PLAY
        elif self.mode == Mode.HISTORY:
            self.mode = Mode.PLAY
            if state.history:
                for callback in list(self._history_listeners):
                    callback(pad)
            else:
                self._set_notice("Hier gibt es noch keine Aufnahmen")
        self._changed()

    def _stop_pad(self, pad: int, at_boundary: bool = False) -> None:
        """Stop a pad; ``at_boundary`` lets a loop on the grid finish up to the next loop start."""
        if self.pad(pad).looping:
            self.store.append(ev.LOOP_OFF, pad)
        self.audio.stop(pad, at_boundary=at_boundary)

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
        # Once the session has a loop length every recording is cut to it,
        # even a new take of the first pad; the first one is free and sets it.
        synced = self._apply_grid() is not None
        if not self.audio.start_recording():
            self._set_notice("Mikrofon lässt sich nicht öffnen")
            return
        if self.settings.sound_effects:
            self.audio.play_effect(start_beep(self.audio.sample_rate))
        self.store.append(ev.RECORD_START, pad, {"stamp": stamp})
        self._recording = _Recording(pad, stamp, self._clock(), synced)

    def _stop_recording(self) -> bool:
        """Stop the running recording; return True if a sample was kept."""
        recording = self._recording
        if recording is None:
            return False
        self._recording = None
        data = self.audio.stop_recording()
        rate = self.audio.sample_rate
        if self.settings.sound_effects:
            self.audio.play_effect(stop_beep(rate))
        duration = 0.0 if data is None else len(data) / rate
        sample: str | None = None
        info: dict[str, object] = {}
        if data is not None and duration >= MIN_RECORD_SECONDS:
            grid = self._grid() if recording.synced else None
            if grid is not None:
                limit = int(self.settings.max_record_seconds * rate)
                data = fit_to_grid(data, grid, grace_frames(grid, rate), limit)
                duration = len(data) / rate
            name = sample_filename(recording.pad, recording.stamp)
            try:
                save_wav(self.samples_dir / name, data, rate)
                self._cache[name] = np.asarray(data, dtype=np.float32)
                sample = name
                info["frames"] = len(data)
            except OSError as exc:
                log.error("saving %s failed: %s", name, exc)
                self._set_notice("Aufnahme konnte nicht gespeichert werden")
        else:
            self._set_notice("Zu kurz - nochmal!")
        self.store.append(
            ev.RECORD_STOP, recording.pad, {"sample": sample, "duration": round(duration, 3), **info}
        )
        if sample is not None:
            self._set_master_from(recording.pad)
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

    def _loop_data(self, sample: str) -> np.ndarray | None:
        """Sample data for loop playback, fitted to the grid if there is one.

        Recordings made on the grid already fit; older versions (or a changed
        sample rate) are padded or cut here, the file itself stays untouched.
        """
        data = self._load(sample)
        grid = self._apply_grid()
        if data is None or grid is None:
            return data
        key = (sample, grid)
        if key not in self._fitted:
            self._fitted[key] = fit_to_grid(data, grid, grace_frames(grid, self.audio.sample_rate))
        return self._fitted[key]

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
        if self.audio.pending_pads() or self._session_started is not None:
            changed = True  # waiting pads count down; the new-session wave moves
            if self.session_shown() is None:
                self._session_started = None
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
        had_content = self.store.state.has_content()
        self.store.append(ev.UNDO, None, {"target": top["seq"]})
        self._content_changed(had_content)
        self._changed()

    def restore(self, pad: int, sample: str) -> None:
        """Put an earlier version back on ``pad``."""
        if sample not in self.pad(pad).history or sample == self.pad(pad).sample:
            return
        self._stop_pad(pad)
        self.store.append(ev.RESTORE_PAD, pad, {"sample": sample})
        # Brought back into an empty session: this sound sets the loop length again.
        self._set_master_from(pad)
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
        had_content = self.store.state.has_content()
        self.store.append(ev.DELETE_ALL)
        self._content_changed(had_content)
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
        self._apply_grid()

    def shutdown(self) -> None:
        """Stop recording and loops, then release audio and the store."""
        if self._recording is not None:
            self._stop_recording()
        self._loops_off()
        self.audio.stop_all()
        self.audio.close()
        self.store.close()

