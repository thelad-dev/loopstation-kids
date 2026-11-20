"""Operating logic of the loopstation, free of any Qt dependency.

The controller turns pad presses and button clicks into events for the store
and commands for the audio engine. The GUI and the Launchpad only call into
the controller and redraw when it notifies them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np

from loopstation import events as ev
from loopstation.audio.base import PREVIEW_VOICE, AudioBackend
from loopstation.audio.dynamics import db_to_gain, gain_to_db
from loopstation.audio.effects import start_beep, stop_beep
from loopstation.audio.samples import load_wav, parse_stamp, sample_filename, save_wav
from loopstation.audio.sync import fit_to_grid, grace_frames, max_grid_frames
from loopstation.clips import ClipEvent, ClipLog
from loopstation.config import Settings, restart_keys_changed
from loopstation.state import PadState, find_entry
from loopstation.store import EventStore

log = logging.getLogger(__name__)

# Recordings shorter than this are treated as accidental taps and discarded.
MIN_RECORD_SECONDS = 0.3
# How long a short hint stays in the status line.
NOTICE_SECONDS = 3.0
# How long the pads show that a new session has begun.
SESSION_SHOW_SECONDS = 1.6
# A clipped microphone block keeps the "too loud" sign on screen this long.
CLIP_HOLD_SECONDS = 1.5
# Peaks (linear) where the coarse three-step level display moves up a step.
LEVEL_QUIET, LEVEL_MEDIUM, LEVEL_LOUD = 0.02, 0.25, 0.7
# A recording that came this close to full scale (dB(FS)) is noted for the parents.
NEAR_CLIP_DB = -3.0
# Range of the parents' ceiling in dB(FS), as in settings.toml.
MIN_MAX_LEVEL_DB, MAX_MAX_LEVEL_DB = -30.0, 0.0

WHITE, YELLOW, GREEN, RED = "white", "yellow", "green", "red"

# Settings that ``apply_settings`` takes over while the app runs; the rest of
# ``Settings`` (see ``config.RESTART_KEYS``) keeps its running value.
LIVE_SETTINGS = (
    "max_record_seconds",
    "sound_effects",
    "fullscreen",
    "launchpad",
    "loop_sync",
    "latency_ms",
    "soft_seam",
)

# Level settings: applied through their setters, and only when the new value
# differs from the running settings, so saving the page never resets a volume
# the child has set with the slider since the start.
LIVE_LEVEL_SETTINGS = (
    ("max_level_db", "set_max_level_db"),
    ("volume", "set_volume"),
    ("input_gain_db", "set_input_gain_db"),
    ("auto_gain", "set_auto_gain"),
    ("peak_meter", "set_peak_meter"),
)


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
        clip_log: ClipLog | None = None,
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
        # Level chain. The controller holds the one master volume; the
        # volume widgets only show and set this value. It never exceeds the
        # parents' ceiling.
        self._max_level_db = settings.max_level_db
        self._volume = min(settings.volume, self.volume_limit)
        self._input_gain_db = settings.input_gain_db
        self._auto_gain = settings.auto_gain
        self._peak_meter = settings.peak_meter
        self._input_peak = 0.0
        self._clips_seen = 0
        self._clip_count = 0
        self._clip_at: float | None = None
        # Peak and clipping of the running (or last) recording; the clip log
        # keeps the loud ones for the parents.
        self._rec_peak = 0.0
        self._rec_clipped = False
        self.clip_log = clip_log if clip_log is not None else ClipLog()
        self._push_levels()

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

    # ---------------------------------------------------------------- levels

    @property
    def volume(self) -> float:
        """Master volume as a linear gain, 0 (silent) to ``volume_limit``."""
        return self._volume

    @property
    def volume_limit(self) -> float:
        """Highest volume the child can choose: the ceiling as a linear gain."""
        return db_to_gain(self._max_level_db)

    @property
    def max_level_db(self) -> float:
        return self._max_level_db

    @property
    def input_gain_db(self) -> float:
        return self._input_gain_db

    @property
    def auto_gain(self) -> bool:
        return self._auto_gain

    @property
    def peak_meter(self) -> bool:
        return self._peak_meter

    def _push_levels(self) -> None:
        self.audio.set_ceiling_db(self._max_level_db)
        self.audio.set_volume(self._volume)
        self.audio.set_input_gain_db(self._input_gain_db)
        self.audio.set_auto_gain(self._auto_gain)

    def set_volume(self, volume: float) -> float:
        """Set the master volume (clamped to 0..ceiling); returns the value that applies."""
        volume = min(self.volume_limit, max(0.0, float(volume)))
        if volume != self._volume:
            self._volume = volume
            self.audio.set_volume(volume)
            self._changed()
        return self._volume

    def set_max_level_db(self, db: float) -> float:
        """Set the parents' ceiling in dB(FS); the volume slides down with it, never above."""
        db = min(MAX_MAX_LEVEL_DB, max(MIN_MAX_LEVEL_DB, float(db)))
        if db != self._max_level_db:
            self._max_level_db = db
            self.audio.set_ceiling_db(db)
            self.set_volume(self._volume)  # clamps to the new ceiling
            self._changed()
        return self._max_level_db

    def set_input_gain_db(self, db: float) -> None:
        self._input_gain_db = min(24.0, max(-24.0, float(db)))
        self.audio.set_input_gain_db(self._input_gain_db)

    def set_auto_gain(self, enabled: bool) -> None:
        self._auto_gain = bool(enabled)
        self.audio.set_auto_gain(self._auto_gain)

    def set_peak_meter(self, enabled: bool) -> None:
        self._peak_meter = bool(enabled)
        self._changed()

    def input_peak(self) -> float:
        """Microphone peak at the last poll (linear, after the trim; 0 when not recording)."""
        return self._input_peak

    def input_level_stage(self) -> int:
        """Coarse input level for the child while recording: 0 (silent) to 3 (very loud).

        Always 0 while the ``peak_meter`` switch is off; the "too loud" sign
        (``input_clipping``) does not depend on it.
        """
        if self._recording is None or not self._peak_meter:
            return 0
        peak = self._input_peak
        return 3 if peak >= LEVEL_LOUD else 2 if peak >= LEVEL_MEDIUM else 1 if peak >= LEVEL_QUIET else 0

    @property
    def clip_count(self) -> int:
        """How many microphone blocks clipped since the start (for the parents)."""
        return self._clip_count

    def input_clipping(self) -> bool:
        """True while a recording runs and the microphone clipped a moment ago."""
        return (
            self._recording is not None
            and self._clip_at is not None
            and self._clock() - self._clip_at < CLIP_HOLD_SECONDS
        )

    def meter_levels(self) -> tuple[float, float]:
        """``(level, hold)`` for the parents' scale, linear after the trim.

        While recording: the current microphone peak and the highest peak so
        far. Afterwards both stay at the peak of the last recording (the
        microphone is only open while recording).
        """
        if self._recording is not None:
            return self._input_peak, self._rec_peak
        return self._rec_peak, self._rec_peak

    def clip_events(self) -> list[ClipEvent]:
        """Loud recordings kept for the parents, newest first."""
        return self.clip_log.events()

    def _poll_input_level(self) -> None:
        peak, clips = self.audio.poll_input_level()
        self._input_peak = peak
        self._rec_peak = max(self._rec_peak, peak)
        if clips > self._clips_seen:
            self._clip_count += clips - self._clips_seen
            self._clip_at = self._clock()
            self._rec_clipped = True
        self._clips_seen = clips

    def _note_loud_recording(self, pad: int) -> None:
        """Keep a recording that clipped or came close to full scale in the clip log."""
        peak_db = gain_to_db(self._rec_peak) if self._rec_peak > 0 else -120.0
        if self._rec_clipped or peak_db >= NEAR_CLIP_DB:
            self.clip_log.add(ClipEvent(self._clock(), pad, peak_db, self._rec_clipped))

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

    def can_undo(self, pad: int | None = None) -> bool:
        """Is there a change to take back (of ``pad`` only, if given)?"""
        return find_entry(self.store.state.undo_stack, pad) is not None

    def last_change_pad(self) -> int | None:
        """The pad of the latest change if that change touched just one pad, else None.

        The pad shows its "back" badge for this change; a change of many pads
        ("Alle löschen") has no single pad and is left to the big "Zurück".
        """
        entry = find_entry(self.store.state.undo_stack)
        if entry is None or len(entry["pads"]) != 1:
            return None
        return next(iter(entry["pads"]))

    def can_redo(self, pad: int | None = None) -> bool:
        """Is there an undone change to bring back? Not while recording."""
        return self._recording is None and find_entry(self.store.state.redo_stack, pad) is not None

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
        self._clips_seen = self.audio.poll_input_level()[1]
        self._clip_at = None
        self._input_peak = 0.0
        self._rec_peak = 0.0
        self._rec_clipped = False
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
        self._poll_input_level()  # count clips of the last blocks, too
        self._note_loud_recording(recording.pad)
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
            self._poll_input_level()
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

    def undo(self, pad: int | None = None) -> None:
        """Undo the last content change (Strg+Z), or the last one of ``pad`` only."""
        # Undo during a recording cancels it: stop, then undo the new sample.
        # A recording that was too short leaves nothing to undo.
        if self._recording is not None and not self._stop_recording():
            self._changed()
            return
        entry = find_entry(self.store.state.undo_stack, pad)
        if entry is None:
            self._set_notice("Nichts mehr zum Zurücknehmen" if pad is None
                             else "Hier gibt es nichts zum Zurücknehmen")
            self._changed()
            return
        self._travel(ev.UNDO, entry, pad)

    def redo(self, pad: int | None = None) -> None:
        """Bring back what was just undone (Strg+Y), or the last undone change of ``pad``."""
        entry = find_entry(self.store.state.redo_stack, pad)
        if self._recording is not None or entry is None:
            self._set_notice("Nichts zum Wiederholen")
            self._changed()
            return
        self._travel(ev.REDO, entry, pad)

    def _travel(self, kind: str, entry: dict[str, Any], pad: int | None) -> None:
        """Log an undo or redo of ``entry`` and stop the pads whose sound changes."""
        affected = [pad] if pad is not None else list(entry["pads"])
        for pad_id in affected:
            if self.pad(pad_id).sample != entry["pads"][pad_id]:
                self.audio.stop(pad_id)
        had_content = self.store.state.has_content()
        self.store.append(kind, pad, {"target": entry["seq"]})
        self._content_changed(had_content)
        if kind == ev.REDO or pad is not None:
            # A sound brought back into an empty session sets the loop length again.
            for pad_id in affected:
                self._set_master_from(pad_id)
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

    # ------------------------------------------------------------- settings

    def apply_settings(self, new: Settings) -> list[str]:
        """Take over the live settings of ``new`` (all at once) without a restart.

        Returns the keys that differ from the running ones but only act after
        a restart (``rows``, ``cols``, ``sample_rate``, ``data_dir``); those keep
        their running value here. Nothing changes if the audio engine refuses.
        """
        updated = replace(self.settings, **{key: getattr(new, key) for key in LIVE_SETTINGS})
        configure = getattr(self.audio, "configure", None)
        if configure is not None:
            latency = None if updated.latency_ms is None else updated.latency_ms / 1000
            configure(updated.max_record_seconds, latency, soft_seam=updated.soft_seam)
        for key, setter in LIVE_LEVEL_SETTINGS:
            if getattr(new, key) != getattr(self.settings, key):
                getattr(self, setter)(getattr(new, key))
        updated = replace(updated, **{key: getattr(new, key) for key, _ in LIVE_LEVEL_SETTINGS})
        self.settings = updated
        self._changed()
        return restart_keys_changed(updated, new)

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

