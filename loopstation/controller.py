"""Operating logic of the loopstation, free of any Qt dependency.

The controller turns pad presses and button clicks into events for the store
and commands for the audio engine. The GUI and the Launchpad only call into
the controller and redraw when it notifies them.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np

from loopstation import events as ev
from loopstation.audio import metronome
from loopstation.audio.base import PREVIEW_VOICE, AudioBackend
from loopstation.audio.dynamics import db_to_gain, gain_to_db
from loopstation.audio.effects import start_beep, stop_beep
from loopstation.audio.onset import GridResult, derive_grid, detect_onsets, rotate_to_onset
from loopstation.audio.samples import load_wav, parse_stamp, sample_filename, save_wav
from loopstation.audio.stretch import (
    MarkerStretchError,
    stretch_between_markers,
    stretch_target,
    stretch_to_grid,
)
from loopstation.audio.sync import SEAM_FADE_MAX_SECONDS, fit_to_grid, grace_frames, max_grid_frames
from loopstation.clips import ClipEvent, ClipLog
from loopstation.config import SIGNATURES, Settings, restart_keys_changed
from loopstation.state import MAX_MARKERS, PadState, find_entry, master_source
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

# The metronome tick is handed to the audio engine this long before its beat
# (padded with silence), so it sounds on the beat whatever the GUI tick jitter.
METRONOME_LOOKAHEAD_SECONDS = 0.1
# Source name of a grid the parents set (``master_set.source``).
PARENT_BPM = "parent_bpm"
# ``record_stop.source`` of a sample made by stretching between markers.
MARKER_STRETCH = "markers"

# What the parents are told when stretching between markers does not happen
# (keyed by ``MarkerStretchError.reason`` plus the cases before it).
MARKER_STRETCH_REFUSALS = {
    "no_pad": "Auf diesem Pad ist noch kein Loop.",
    "free": "Ein freies Pad hat seine eigene Länge, ohne Schlaglinien: Hier gibt es nichts zu strecken.",
    "no_grid": "Ohne Takt gibt es keine Schlaglinien zum Strecken.",
    "no_markers": "Setze zuerst mindestens einen Marker.",
    "recording": "Es läuft gerade eine Aufnahme.",
    "unreadable": "Die Aufnahme fehlt oder ist nicht lesbar.",
    "edge": "Ein Marker liegt am Anfang oder Ende des Loops und lässt sich nicht verschieben.",
    "same_beat": "Zwei Marker gehören zum selben Schlag. Lösche einen davon.",
    "too_far": "Ein Marker liegt zu weit neben seinem Schlag (mehr als 10 %). Es wurde nichts verändert.",
    "already": "Die Marker liegen schon auf den Schlägen: Da gibt es nichts zu strecken.",
    "save": "Der gestreckte Loop konnte nicht gespeichert werden.",
}

WHITE, YELLOW, GREEN, RED = "white", "yellow", "green", "red"

# How long a pad has to be held to switch its free mode (the ring on the pad
# fills in this time). A tap is far shorter; the parents' lock needs 2 s.
FREE_HOLD_SECONDS = 0.8

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
    "auto_grid",
    "time_signature",
    "grid_bpm_min",
    "grid_bpm_max",
    "stretch_to_grid",
    "metronome_tone",
    "metronome_level_db",
    "free_pad_on_grid",
    "export_cue_points",
)

# Audio devices: the streams are opened again when one of these changes.
LIVE_DEVICE_SETTINGS = ("input_device", "output_device", "audio_hostapi")

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
    # Recorded on a free pad: kept as it is, neither cut nor stretched.
    free: bool = False


@dataclass
class _Hold:
    """A pad that is being pressed. ``state``: ``armed`` (the ring fills towards a switch of
    the free mode), ``plain`` (only a tap can come of it) or ``done`` (it has switched, or was
    called off; letting go does nothing)."""

    since: float
    state: str


@dataclass(frozen=True)
class GridInfo:
    """The session grid as the parents' view shows it (one bar = ``beats`` beats)."""

    bpm: float
    signature: str
    beats: int
    seconds: float  # length of one bar
    source: str  # onset, duration, parent_bpm or free_pad
    pad: int | None  # the pad that set it, None if the log did not say


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
        # What the onset analysis decided for a sample (``onset``, ``duration`` or
        # ``none``), so that bringing it back (redo, restore) sets the same grid.
        self._sample_grid: dict[str, str] = {}
        # Outcome of the latest grid-setting recording, for the parents' view.
        self.last_grid: GridResult | None = None
        # The parents' grid (bpm, signature) while it overrides what recordings
        # would set (plan 2.2 rule 8). Kept here, not in the log, so that it also
        # holds while the session is empty (the log has no grid without sound).
        self._parent_grid: tuple[float, str] | None = None
        # The grid the session had before the parents' grid replaced it.
        self._measured_master: dict[str, Any] | None = None
        # Metronome: controller clock time of the last tick handed to the audio
        # engine, and the bar start the free-running beat counts from.
        self._tick_at: float | None = None
        self._bar_origin: float | None = None
        # Pads that are being pressed now (screen, Launchpad), see ``press_down``.
        self._holds: dict[int, _Hold] = {}
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
        """The first sound of a session sets the loop length (``master_set``).

        With ``auto_grid`` the event also says where the bar came from
        (``source``), the time signature and the pad. A sound that the onset
        analysis found no usable grid in sets nothing: the session stays free.
        """
        state = self.store.state
        sample = self.pad(pad).sample
        if not self.settings.loop_sync or state.master is not None or sample is None:
            return
        parent = self._parent_event()
        if parent is not None:
            # The parents' tempo wins over anything the sound would say (rule 8).
            self._measured_master = None
            self.store.append(ev.MASTER_SET, None, {**parent, "pad": pad})
            return
        origin = self._sample_grid.get(sample)
        if origin == "none":
            return
        free = self.pad(pad).free
        data = self._load(sample)
        if data is None or len(data) == 0:
            return
        event: dict[str, object] = {"frames": len(data), "rate": self.audio.sample_rate}
        if free:
            # A free pad that comes first gives the session its bar: the length of its
            # sound, untouched, if that length passes the same check as any other bar.
            # The log says so, there is no second grid event.
            if not self._free_grid(data, self.audio.sample_rate).has_grid:
                return
            event.update(source="free_pad", signature=self.settings.time_signature, pad=pad)
        elif self.settings.auto_grid:
            event.update(source=origin or "duration", signature=self.settings.time_signature, pad=pad)
        self.store.append(ev.MASTER_SET, None, event)

    def _grid_limits(self, rate: int) -> dict[str, float | int]:
        settings = self.settings
        seam = 2 * SEAM_FADE_MAX_SECONDS + 0.05 if settings.soft_seam else 0.0
        return {
            "bpm_min": settings.grid_bpm_min,
            "bpm_max": settings.grid_bpm_max,
            "beats_per_bar": settings.beats_per_bar,
            "min_frames": round(max(MIN_RECORD_SECONDS, seam) * rate),
            "max_frames": int(settings.max_record_seconds * rate),
        }

    def _free_grid(self, data: np.ndarray, rate: int) -> GridResult:
        """Is the length of a free sound a plausible bar? Same limits as ``_seed_grid``."""
        return derive_grid([], len(data), rate, **self._grid_limits(rate))

    def _seed_grid(self, data: np.ndarray, rate: int) -> tuple[np.ndarray, GridResult]:
        """Onset analysis of the grid-setting recording (before ``fit_to_grid``).

        Returns the recording shifted circularly to its first reliable onset (and
        cut to one bar if the bar came from onset distances) together with the
        decision. Without a grid (``none``) the recording stays as it is.
        """
        result = derive_grid(detect_onsets(data, rate), len(data), rate, **self._grid_limits(rate))
        if not result.has_grid:
            return data, result
        if result.start_frame > 0:
            data = rotate_to_onset(data, result.start_frame)
        if result.source == "onset":
            data = np.ascontiguousarray(data[: result.bar_frames])
        return data, result

    def grid_info(self) -> GridInfo | None:
        """Tempo, time signature, bar length and source of the session grid, None without one."""
        master = self.store.state.master
        if master is None or self._grid() is None:
            return None
        signature = master.get("signature", self.settings.time_signature)
        beats = SIGNATURES.get(signature, self.settings.beats_per_bar)
        return GridInfo(
            bpm=beats * 60.0 * master["rate"] / master["frames"],
            signature=signature,
            beats=beats,
            seconds=master["frames"] / master["rate"],
            source=master_source(master),
            pad=master.get("pad"),
        )

    def _scan_grid_sources(self) -> None:
        """Remember from the log what the onset analysis decided for earlier recordings."""
        try:
            lines = self.store.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            if '"record_stop"' not in line:
                continue
            try:
                data = json.loads(line).get("data", {})
            except (ValueError, AttributeError):
                continue
            if not isinstance(data, dict):
                continue
            sample, grid = data.get("sample"), data.get("grid")
            if isinstance(sample, str) and isinstance(grid, str):
                self._sample_grid[sample] = grid

    def _content_changed(self, had_content: bool) -> None:
        """Log a new session once the last pad has been emptied."""
        if had_content and not self.store.state.has_content():
            self.store.append(ev.SESSION_START)
            self._session_started = self._clock()
            self.last_grid = None

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
                data = self._loop_data(state.sample, pad)
                if data is not None:
                    self.store.append(ev.LOOP_ON, pad)
                    if state.free:
                        self.audio.play(pad, data, loop=True, free=True,
                                        align=self.settings.free_pad_on_grid)
                    else:
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

    # ------------------------------------------------------ free mode and hold

    def is_free(self, pad: int) -> bool:
        """Is ``pad`` in the free mode (its sound keeps its own length)?"""
        return self.pad(pad).free

    def set_free(self, pad: int, free: bool) -> None:
        """Put ``pad`` into (or out of) the free mode. Undoable; not while recording.

        A pad that plays is stopped: it has to be started again, because it now plays
        with a different length.
        """
        if not 0 <= pad < self.pad_count or self._recording is not None:
            return
        if self.pad(pad).free == free:
            return
        self._stop_pad(pad)
        self.store.append(ev.PAD_FREE, pad, {"free": free})
        self._changed()

    def press_down(self, pad: int) -> None:
        """A pad is pressed (finger down, Launchpad note on).

        Holding it for ``FREE_HOLD_SECONDS`` (``tick`` counts) switches its free mode; a
        short press ends in ``press_up`` returning True and the caller then calls ``press``.
        The hold only counts in the play, record and loop modes and while nothing records.
        """
        if not 0 <= pad < self.pad_count:
            return
        armed = self._recording is None and self.mode in (Mode.PLAY, Mode.RECORD, Mode.LOOP)
        self._holds[pad] = _Hold(self._clock(), "armed" if armed else "plain")
        self._changed()

    def press_up(self, pad: int) -> bool:
        """The pad is let go. True if that was a tap (the caller presses the pad now).

        False when the hold already switched the free mode (nothing more to do) or when
        this release has no press before it.
        """
        hold = self._holds.pop(pad, None)
        if hold is None:
            return False
        self._changed()
        return hold.state != "done"

    def cancel_hold(self, pad: int) -> None:
        """Forget a press whose release will never come (the Launchpad was unplugged)."""
        if self._holds.pop(pad, None) is not None:
            self._changed()

    def hold_progress(self, pad: int) -> float | None:
        """How far the ring of a pad that is being held has filled (0..1), None if not held."""
        hold = self._holds.get(pad)
        if hold is None or hold.state != "armed":
            return None
        return min(1.0, max(0.0, (self._clock() - hold.since) / FREE_HOLD_SECONDS))

    def _advance_holds(self) -> bool:
        """Switch the free mode of pads held long enough; True while a ring is still moving."""
        moving = False
        for pad, hold in list(self._holds.items()):
            if hold.state != "armed":
                continue
            if self._recording is not None or self.mode not in (Mode.PLAY, Mode.RECORD, Mode.LOOP):
                hold.state = "done"  # something else took over: letting go does nothing
                moving = True
            elif self._clock() - hold.since >= FREE_HOLD_SECONDS:
                hold.state = "done"
                self.set_free(pad, not self.pad(pad).free)
                moving = True
            else:
                moving = True
        return moving

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
        # A free pad is neither cut nor waits for a loop start: it records at once.
        free = self.pad(pad).free
        synced = self._apply_grid() is not None and not free
        started = self.audio.start_recording(align=False) if free else self.audio.start_recording()
        if not started:
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
        self._recording = _Recording(pad, stamp, self._clock(), synced, free)

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
        seeded: GridResult | None = None
        parent_seeded = False
        free_grid: GridResult | None = None
        if data is not None and duration >= MIN_RECORD_SECONDS:
            grid = self._grid() if recording.synced else None
            if grid is not None:
                limit = int(self.settings.max_record_seconds * rate)
                data = self._fit_recording(data, grid, rate, limit)
                duration = len(data) / rate
            elif (self._parent_grid is not None and self.settings.loop_sync
                  and self.store.state.master is None):
                # The parents set the tempo: onsets may only align this recording.
                # It goes through fit_to_grid, not _fit_recording: it is the
                # first recording on the parents' bar, so it is aligned to that
                # grid (padded or cut) and not stretched. stretch_to_grid
                # applies to the recordings that follow.
                data, shift = self._fit_to_parent_grid(data, rate)
                info["grid"] = PARENT_BPM
                if shift > 0:
                    info["shift"] = shift
                parent_seeded = True
                duration = len(data) / rate
            elif recording.free:
                # A free sound keeps its length and its start; the session has no grid
                # yet if it is the first sound, and then the length becomes the bar.
                if self.settings.loop_sync and self.store.state.master is None:
                    free_grid = self._free_grid(data, rate)
                    info["grid"] = "free_pad" if free_grid.has_grid else "none"
            elif self.settings.auto_grid and self.settings.loop_sync and self.store.state.master is None:
                # Only the recording that sets the grid is shifted to its first
                # onset; recordings on an existing grid keep their latency-
                # compensated alignment. This runs before any fit_to_grid.
                data, seeded = self._seed_grid(data, rate)
                info["grid"] = seeded.source
                if seeded.has_grid and seeded.start_frame > 0:
                    info["shift"] = seeded.start_frame
                duration = len(data) / rate
            name = sample_filename(recording.pad, recording.stamp)
            try:
                save_wav(self.samples_dir / name, data, rate)
                self._cache[name] = np.asarray(data, dtype=np.float32)
                sample = name
                info["frames"] = len(data)
                if seeded is not None:
                    self._sample_grid[name] = seeded.source
                    self.last_grid = seeded
                if parent_seeded:
                    self._sample_grid[name] = PARENT_BPM
                elif free_grid is not None:
                    self._sample_grid[name] = str(info["grid"])
                    if not free_grid.has_grid:
                        self.last_grid = free_grid
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

    def _fit_recording(self, data: np.ndarray, grid: int, rate: int, limit: int) -> np.ndarray:
        """A recording on the grid: stretched when it is just off a whole number of loops.

        Runs once at stop, outside the audio callback. Anything further off, a
        stop within the grace window after a boundary, a result over the
        recording limit, or ``stretch_to_grid`` off falls back to
        ``fit_to_grid``, so the length is always a multiple of the grid.
        """
        grace = grace_frames(grid, rate)
        if self.settings.stretch_to_grid:
            target = stretch_target(len(data), grid)
            over = len(data) - target
            if target <= max_grid_frames(grid, limit) and not 0 < over <= grace:
                stretched = stretch_to_grid(data, grid)
                if stretched is not None:
                    return stretched
        return fit_to_grid(data, grid, grace, limit)

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

    def _loop_data(self, sample: str, pad: int | None = None) -> np.ndarray | None:
        """Sample data for loop playback, fitted to the grid if there is one.

        Recordings made on the grid already fit; older versions (or a changed
        sample rate) are padded or cut here, the file itself stays untouched.
        A free pad (``pad`` given) keeps its own length: no fitting at all.
        """
        data = self._load(sample)
        grid = self._apply_grid()
        if data is None or grid is None or (pad is not None and self.pad(pad).free):
            return data
        key = (sample, grid)
        if key not in self._fitted:
            self._fitted[key] = fit_to_grid(data, grid, grace_frames(grid, self.audio.sample_rate))
        return self._fitted[key]

    # ----------------------------------------- parents' grid and metronome

    def parent_grid(self) -> tuple[float, str] | None:
        """``(bpm, signature)`` the parents set, None while recordings decide the grid."""
        return self._parent_grid

    def bpm_range(self) -> tuple[float, float]:
        """Tempo the parents may set (the window of ``settings.toml``)."""
        return self.settings.grid_bpm_min, self.settings.grid_bpm_max

    def _parent_event(self) -> dict[str, Any] | None:
        """``master_set`` data of the parents' grid at the current sample rate."""
        if self._parent_grid is None:
            return None
        bpm, signature = self._parent_grid
        rate = self.audio.sample_rate
        frames = max(1, round(SIGNATURES[signature] * 60.0 * rate / bpm))
        return {"frames": frames, "rate": rate, "source": PARENT_BPM, "signature": signature}

    def set_parent_grid(self, bpm: float, signature: str) -> bool:
        """Set tempo and time signature (the parents' override); False if not possible.

        It needs ``loop_sync`` and a tempo inside the allowed window, and waits
        while a recording runs. With sound in the session the grid is replaced
        by a ``master_set`` with source ``parent_bpm``: the files stay as they
        are, the loops are fitted again (like ``_loop_data`` does for any grid)
        and running loops start over on the new bars. Without sound it applies
        to the next first recording.
        """
        low, high = self.bpm_range()
        if signature not in SIGNATURES or not low <= bpm <= high:
            return False
        if not self.settings.loop_sync or self._recording is not None:
            return False
        self._parent_grid = (float(bpm), signature)
        state = self.store.state
        if state.master is not None:
            if master_source(state.master) != PARENT_BPM:
                self._measured_master = dict(state.master)
            self.store.append(ev.MASTER_SET, None, self._parent_event())
            self._refit_loops()
        self._changed()
        return True

    def use_measured_grid(self) -> bool:
        """Give the grid back to the recordings ("Gemessenen Takt"); False if nothing was set.

        If the session had a measured grid before, it is restored (a new
        ``master_set``, loops fitted again). Otherwise the current bars stay
        and only the override ends, so the next session is measured again.
        """
        if self._parent_grid is None:
            return False
        self._parent_grid = None
        state = self.store.state
        measured, self._measured_master = self._measured_master, None
        if state.master is not None and master_source(state.master) == PARENT_BPM and measured:
            self.store.append(ev.MASTER_SET, None, measured)
            self._refit_loops()
        self._changed()
        return True

    def _refit_loops(self) -> None:
        """Start the running loops again on the grid as it is now (their files stay untouched)."""
        running = [p for p, state in sorted(self.store.state.pads.items())
                   if state.looping and state.sample is not None and p in self.audio.playing_pads()]
        for pad in running:
            self.audio.stop(pad)
        for pad in running:
            data = self._loop_data(self.pad(pad).sample)
            if data is not None:
                self.audio.play(pad, data, loop=True)
        self._apply_grid()

    def _fit_to_parent_grid(self, data: np.ndarray, rate: int) -> tuple[np.ndarray, int]:
        """The grid-setting recording on the parents' bars; also returns the shift to its first onset.

        Onsets only align the recording (circular shift, as ``auto_grid`` does);
        the bar length comes from the parents' tempo.
        """
        shift = 0
        if self.settings.auto_grid:
            onsets = detect_onsets(data, rate)
            if onsets and onsets[0] > 0:
                shift = onsets[0]
                data = rotate_to_onset(data, shift)
        grid = self._parent_event()["frames"]
        limit = int(self.settings.max_record_seconds * rate)
        return fit_to_grid(data, grid, grace_frames(grid, rate), limit), shift

    def _resume_parent_grid(self) -> None:
        """After a start: a grid of the parents in the log is still their override."""
        master = self.store.state.master
        if master is None or master_source(master) != PARENT_BPM or "signature" not in master:
            return
        beats = SIGNATURES.get(master["signature"])
        if beats:
            self._parent_grid = (beats * 60.0 * master["rate"] / master["frames"], master["signature"])

    def bar_seconds(self) -> float | None:
        """Length of one bar in seconds, None without a grid."""
        grid = self._grid()
        return None if grid is None else grid / self.audio.sample_rate

    def metronome_period(self) -> float | None:
        """Seconds between two metronome beats: a bar divided into its beats, None without a grid."""
        info = self.grid_info()
        bar = self.bar_seconds()
        if info is None or bar is None:
            return None
        return metronome.beat_seconds(bar, info.beats)

    def beat_position(self) -> float | None:
        """Where the grid is inside the bar, in beats from its start (0 <= x < beats), None without a grid.

        While loops run it follows the audio engine's loop start; otherwise
        it keeps counting on the clock from where it was, so the parents can
        hear and see a tempo they just set.
        """
        info = self.grid_info()
        bar = self.bar_seconds()
        if info is None or bar is None:
            self._bar_origin = None
            return None
        now = self._clock()
        wait = self.audio.next_boundary_in()
        if wait is not None:
            phase = min(1.0, max(0.0, 1.0 - wait / bar))
            self._bar_origin = now - phase * bar
        else:
            if self._bar_origin is None:
                self._bar_origin = now
            phase = ((now - self._bar_origin) / bar) % 1.0
        return (phase * info.beats) % info.beats

    def _tick_metronome(self) -> None:
        """Hand the tick of the next beat to the audio engine shortly before it is due."""
        if not self.settings.metronome_tone:
            self._tick_at = None
            return
        period, position = self.metronome_period(), self.beat_position()
        info = self.grid_info()
        if period is None or position is None or info is None:
            return
        ahead = metronome.seconds_to_next_beat(position, period)
        if ahead > METRONOME_LOOKAHEAD_SECONDS:
            return
        due = self._clock() + ahead
        if self._tick_at is not None and due - self._tick_at < period / 2:
            return  # this beat's tick is already on its way
        self._tick_at = due
        rate = self.audio.sample_rate
        beat = metronome.beat_index(position + ahead / period, info.beats)
        click = metronome.tick(rate, self.settings.metronome_level_db, accent=beat == 0)
        self.audio.play_effect(metronome.delayed(click, round(ahead * rate)))

    # --------------------------------------------- export (read only, parents)

    @property
    def sample_rate(self) -> int:
        """Sample rate of the audio engine (what loaded samples are converted to)."""
        return self.audio.sample_rate

    def grid_frames(self) -> int | None:
        """Loop length in frames, None while recordings are free (no bars to count)."""
        return self._grid()

    def loop_audio(self, sample: str, pad: int | None = None) -> np.ndarray | None:
        """A sample as it plays in a loop (fitted to the grid, a free ``pad`` as recorded), or None."""
        return self._loop_data(sample, pad)

    def sample_audio(self, sample: str) -> np.ndarray | None:
        """A sample as recorded, None if unreadable."""
        return self._load(sample)

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
        if self._holds and self._advance_holds():
            changed = True  # the ring on a held pad fills continuously
        playing = self.audio.playing_pads()
        if playing != self._last_playing:
            self._last_playing = playing
            changed = True
        if self.audio.pending_pads() or self._session_started is not None:
            changed = True  # waiting pads count down; the new-session wave moves
            if self.session_shown() is None:
                self._session_started = None
        self._tick_metronome()
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
        free = entry.get("free", {})
        for pad_id in affected:
            if self.pad(pad_id).sample != entry["pads"][pad_id] or self.pad(pad_id).free != free.get(
                pad_id, self.pad(pad_id).free
            ):
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
        updated = self._apply_devices(updated, new)
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

    def _apply_devices(self, updated: Settings, new: Settings) -> Settings:
        """Open the audio streams on the devices of ``new`` if they differ; ``updated`` with the result."""
        if all(getattr(new, key) == getattr(self.settings, key) for key in LIVE_DEVICE_SETTINGS):
            return updated
        select = getattr(self.audio, "select_devices", None)
        if select is None:
            return updated
        try:
            select(new.input_device, new.output_device, new.audio_hostapi)
        except Exception as exc:  # nothing could be opened again: keep the old names, tell the parents
            log.warning("switching audio devices failed: %s", exc)
            self._set_notice("Audio lässt sich nicht neu starten")
            return updated
        self._set_notice("Audio startet neu: Geräte gewechselt")
        return replace(updated, **{key: getattr(new, key) for key in LIVE_DEVICE_SETTINGS})

    @property
    def device_notice(self) -> str:
        """Hint about devices (a saved one is missing, the default is used instead), or ""."""
        return str(getattr(self.audio, "device_notice", ""))

    # -------------------------------------------------------------- markers

    def markers(self, pad: int) -> list[int]:
        """Marker positions (frames at the engine's sample rate, sorted) of the sound on ``pad``."""
        sample = self.pad(pad).sample
        entry = None if sample is None else self.store.state.markers.get(sample)
        if entry is None:
            return []
        rate = self.audio.sample_rate
        if entry["rate"] == rate:
            return list(entry["frames"])
        return sorted({max(1, round(f * rate / entry["rate"])) for f in entry["frames"]})

    def set_markers(self, pad: int, frames: list[int]) -> bool:
        """Make ``frames`` the markers of the sound on ``pad``; False when nothing was logged.

        Markers belong to the parents: they are one ``marker_set`` event, not a step
        the child's undo would take back. They stay with the sample, so undo,
        redo and the history bring the right ones back with it.
        """
        sample = self.pad(pad).sample
        if sample is None:
            return False
        clean = sorted({int(f) for f in frames if int(f) > 0})[:MAX_MARKERS]
        if clean == self.markers(pad):
            return False
        self.store.append(
            ev.MARKER_SET, pad, {"sample": sample, "rate": self.audio.sample_rate, "frames": clean})
        self._changed()
        return True

    def add_marker(self, pad: int, frame: int) -> bool:
        """Put a marker at ``frame``; False at the limit, on an empty pad or when it is there already."""
        current = self.markers(pad)
        if frame <= 0 or frame in current or len(current) >= MAX_MARKERS:
            return False
        return self.set_markers(pad, [*current, frame])

    def remove_marker(self, pad: int, frame: int) -> bool:
        """Take the marker at ``frame`` away; False if there is none."""
        current = self.markers(pad)
        if frame not in current:
            return False
        return self.set_markers(pad, [f for f in current if f != frame])

    def stretch_to_markers(self, pad: int) -> str | None:
        """Stretch the loop on ``pad`` so its markers sit on the beat lines; None, or why not.

        The pieces between the markers are stretched, the loop keeps exactly its
        length (a multiple of the grid). The result is a new sample logged like a
        recording (``record_stop`` with ``source: "markers"``), so Zurück and the
        history take it back; its markers are the beat lines. Nothing is
        stretched when a piece would change by more than 10 %.
        """
        sample = self.pad(pad).sample
        if sample is None:
            return MARKER_STRETCH_REFUSALS["no_pad"]
        if self._recording is not None:
            return MARKER_STRETCH_REFUSALS["recording"]
        if self.pad(pad).free:
            return MARKER_STRETCH_REFUSALS["free"]
        info, grid = self.grid_info(), self._grid()
        if info is None or grid is None:
            return MARKER_STRETCH_REFUSALS["no_grid"]
        marks = self.markers(pad)
        if not marks:
            return MARKER_STRETCH_REFUSALS["no_markers"]
        data = self._loop_data(sample)
        if data is None:
            return MARKER_STRETCH_REFUSALS["unreadable"]
        try:
            result, targets = stretch_between_markers(data, marks, grid / info.beats)
        except MarkerStretchError as exc:
            return MARKER_STRETCH_REFUSALS[exc.reason]
        if np.array_equal(result, data):
            return MARKER_STRETCH_REFUSALS["already"]
        rate = self.audio.sample_rate
        stamp = int(self._clock() * 1000)
        while (self.samples_dir / sample_filename(pad, stamp)).exists():
            stamp += 1
        name = sample_filename(pad, stamp)
        try:
            save_wav(self.samples_dir / name, result, rate)
        except OSError as exc:
            log.error("saving %s failed: %s", name, exc)
            return MARKER_STRETCH_REFUSALS["save"]
        self._cache[name] = result
        self._stop_pad(pad)
        self.store.append(ev.RECORD_STOP, pad, {
            "sample": name, "duration": round(len(result) / rate, 3), "frames": len(result),
            "source": MARKER_STRETCH, "from": sample,
        })
        self.store.append(ev.MARKER_SET, pad, {"sample": name, "rate": rate, "frames": targets})
        self._changed()
        return None

    # ------------------------------------------------------------ lifecycle

    def startup(self) -> None:
        """Nothing plays after a start: switch off loops left by a crash."""
        self._loops_off()
        self._scan_grid_sources()
        self._resume_parent_grid()
        self._apply_grid()

    def shutdown(self) -> None:
        """Stop recording and loops, then release audio and the store."""
        if self._recording is not None:
            self._stop_recording()
        self._loops_off()
        self.audio.stop_all()
        self.audio.close()
        self.store.close()

