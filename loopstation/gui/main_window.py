"""Main window: mode bar, pad grid, action buttons and a small status line.

The window only talks to the controller (and mirrors colours to the
Launchpad); it contains no audio, MIDI or event-store logic of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPaintEvent, QPen, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.config import DEFAULT_CONFIG_NAME, Settings
from loopstation.controller import Controller, Mode
from loopstation.gui.advanced_page import AdvancedPage
from loopstation.gui.changes_page import ChangesPage
from loopstation.gui.confirm_dialog import ConfirmDialog
from loopstation.gui.export_dialog import ExportPage
from loopstation.gui.history_dialog import HistoryDialog
from loopstation.gui.pad_button import MIN_PAD_SIZE, PadButton
from loopstation.gui.parent_gate import ParentGate
from loopstation.gui.parent_nav import ParentPage
from loopstation.gui.parent_tile import ParentTile
from loopstation.gui.pulse_strip import PulseStrip
from loopstation.gui.sets_page import SetsPage
from loopstation.gui.settings_page import SettingsDialog
from loopstation.gui.volume_slider import VolumeSlider
from loopstation.gui.widgets import (
    ACCENT_BLUE,
    ACCENT_GRAY,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PURPLE,
    ACCENT_RED,
    BACKGROUND,
    BigButton,
    weak_slot,
)
from loopstation.midi.launchpad import LaunchpadController
from loopstation.session import PreparedOpen, SetSession

TICK_MS = 30
SESSION_WAVE_WIDTH = 0.3  # seconds a pad stays lit while the new-session wave passes
MODE_BAR_HEIGHT = 104  # mode buttons and volume control share one row of this height
MODE_FONT_PT = 13
MODE_PAD_X = 6  # sides of a mode button: the five words and the volume control must fit 1024 px
PAD_GAP = 8  # visible gap is larger: each pad keeps a margin for its glow
# The action row (with "Wiederholen") stays inside a 1024 px wide window at
# this size (checked by a test).
BAR_FONT_PT = 16
BAR_PAD_X = 10
ACTION_HEIGHT = 92  # as in the mockups
DELETE_ALL_FONT_PT = 11  # "Alle löschen" is a small tile next to the lock, not a big action
DELETE_ALL_PAD_X = 8
OUTER_MARGIN_X = 28  # window margins of the mockups
OUTER_MARGIN_Y = 24
BAR_GAP = 12  # gap between the buttons of the bottom row (mockups)
PULSE_CONFIRM_SECONDS = 3.0  # a new grid shows the pulse at least this long (plan 2.2 rule 7)
_UNSET = object()

# (mode, icon, word, accent colour)
MODES = [
    (Mode.PLAY, "play", "Spielen", ACCENT_GREEN),
    (Mode.RECORD, "record", "Aufnehmen", ACCENT_RED),
    (Mode.LOOP, "loop", "Loop", ACCENT_BLUE),
    (Mode.DELETE, "delete", "Löschen", ACCENT_ORANGE),
    (Mode.HISTORY, "history", "Verlauf", ACCENT_PURPLE),
]
MODE_ACCENT = {mode: accent for mode, _icon, _word, accent in MODES}


class Frame(QWidget):
    """Dark background with a rounded border tinted in the mode colour."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.accent: QColor | None = None

    def set_accent(self, accent: QColor | None) -> None:
        if accent != self.accent:
            self.accent = accent
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), BACKGROUND)
        if self.accent is not None:
            # A clear border in the mode colour (the mockups have no wash over the background).
            painter.setPen(QPen(self.accent, 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5), 22, 22)
        painter.end()


class PadGrid(QWidget):
    """Lays out the pads as equal squares, centred in the available space."""

    def __init__(self, rows: int, cols: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows, self.cols = rows, cols
        self.pads = [PadButton(i, self) for i in range(rows * cols)]

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        # On very small screens the pads shrink first, so the buttons are
        # never squeezed. From 1024 x 640 upwards a 4 x 3 grid gets
        # MIN_PAD_SIZE pads.
        floor = MIN_PAD_SIZE * 3 // 4
        return QSize(self.cols * floor + (self.cols - 1) * PAD_GAP,
                     self.rows * floor + (self.rows - 1) * PAD_GAP)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.cols * 200 + (self.cols - 1) * PAD_GAP,
                     self.rows * 200 + (self.rows - 1) * PAD_GAP)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        width, height = self.width(), self.height()
        side = min((width - (self.cols - 1) * PAD_GAP) / self.cols,
                   (height - (self.rows - 1) * PAD_GAP) / self.rows)
        side = max(1, int(side))
        total_w = self.cols * side + (self.cols - 1) * PAD_GAP
        total_h = self.rows * side + (self.rows - 1) * PAD_GAP
        left = (width - total_w) // 2
        top = (height - total_h) // 2
        for index, pad in enumerate(self.pads):
            row, col = divmod(index, self.cols)
            pad.setGeometry(left + col * (side + PAD_GAP), top + row * (side + PAD_GAP), side, side)
            pad.layout_badge()


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: Controller,
        launchpad: LaunchpadController | None = None,
        device_status: list[str] | None = None,
        config_path: Path | None = None,
        launchpad_factory: Callable[[Settings], LaunchpadController | None] | None = None,
        settings_template: str | None = None,
        set_session: SetSession | None = None,
        on_open_set: Callable[[PreparedOpen], None] | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.launchpad = launchpad
        self._launchpad_down: set[int] = set()
        self.config_path = config_path if config_path is not None else Path(DEFAULT_CONFIG_NAME).resolve()
        self.launchpad_factory = launchpad_factory
        self.settings_template = settings_template
        self.device_status = list(device_status or [])
        # Sets (parents' area only): the session they work on and what to do with a set to open.
        self.set_session = set_session
        self.on_open_set = on_open_set
        self._dialog_open = False
        self._settings_dialog: QDialog | None = None
        # Factories so tests can replace the modal dialogs.
        self.confirm_factory: Callable[[QWidget], QDialog] = ConfirmDialog
        self.history_factory: Callable[[Controller, int, QWidget], QDialog] = HistoryDialog
        self.gate_factory: Callable[[QWidget], QDialog] = ParentGate
        self.settings_factory: Callable[..., QDialog] = SettingsDialog
        # The areas of the parents' area (widgets, built on their first visit).
        self.export_factory: Callable[[Controller, QWidget | None], QWidget] = ExportPage
        self.sets_factory: Callable[..., QWidget] = SetsPage
        self.advanced_factory: Callable[[Controller, QWidget | None], QWidget] = AdvancedPage
        self.changes_factory: Callable[[Controller, QWidget | None], QWidget] = ChangesPage

        self.setWindowTitle("Loopstation")
        self.frame = Frame()
        self.setCentralWidget(self.frame)

        # Mode bar.
        self.mode_buttons: dict[Mode, BigButton] = {}
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(12)
        for mode, icon, word, accent in MODES:
            button = BigButton(icon, word, accent, checkable=True, stacked=True,
                               min_height=MODE_BAR_HEIGHT, font_pt=MODE_FONT_PT, pad_x=MODE_PAD_X)
            button.clicked.connect(weak_slot(self._choose_mode, mode))
            # Equal widths: the layout shares the row by stretch only, the words do not matter.
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.mode_buttons[mode] = button
            mode_bar.addWidget(button, 2)  # equal widths
        # The volume control closes the bar on the right (a larger gap sets it apart).
        # No word may be cut off: every mode button is at least as wide as the widest word needs.
        floor = max(b.sizeHint().width() for b in self.mode_buttons.values())
        for button in self.mode_buttons.values():
            button.setMinimumWidth(floor)
        self.volume_slider = VolumeSlider()
        self.volume_slider.volumeChanged.connect(self.controller.set_volume)
        mode_bar.addSpacing(12)
        mode_bar.addWidget(self.volume_slider, 5)

        # Pads.
        rows, cols = controller.settings.rows, controller.settings.cols
        self.grid = PadGrid(rows, cols)
        # Whether the last release of a pad was a tap (not the end of a long hold).
        self._tap: dict[int, bool] = {}
        for pad in self.grid.pads:
            # A tap acts on release as before (clicked); the press and release in front of it
            # let a long hold switch the free mode of the pad instead (see Controller.press_down).
            pad.pressed.connect(weak_slot(self._pad_down, pad.index))
            pad.released.connect(weak_slot(self._pad_up, pad.index))
            pad.clicked.connect(weak_slot(self._pad_clicked, pad.index))
            pad.on_badge = weak_slot(self.undo_pad, pad.index)

        # Bottom row (mockup 01): Zurück, Wiederholen, Alles still, the pulse strip with the status
        # line, and the lock tile. "Alle löschen" stays on the child page as a small tile next to
        # the lock (its move to the parents' area is still undecided).
        self.undo_button = BigButton("undo", "Zurück", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = BigButton("redo", "Wiederholen", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.redo_button.clicked.connect(self.redo)
        self.stop_button = BigButton("stop", "Alles still", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.stop_button.clicked.connect(self.stop_all)
        self.delete_all_button = BigButton("trash", "Alle löschen", ACCENT_RED, stacked=True,
                                           font_pt=DELETE_ALL_FONT_PT, pad_x=DELETE_ALL_PAD_X,
                                           min_height=ACTION_HEIGHT)
        self.delete_all_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.delete_all_button.setFixedWidth(self.delete_all_button.sizeHint().width())
        self.delete_all_button.clicked.connect(self.confirm_delete_all)
        self.pulse_strip = PulseStrip(controller.settings.beats_per_bar)
        self.status_label = self.pulse_strip.status_label  # small status text below the pulse dots
        # Way into the parents' area: a small dim tile, held to open.
        self.parent_entry = ParentTile()
        self.parent_entry.held.connect(self.open_parent_area)
        self._grid_key: object = _UNSET
        self._pulse_until = 0.0

        actions = QHBoxLayout()
        actions.setSpacing(BAR_GAP)
        actions.addWidget(self.undo_button, 236)
        actions.addWidget(self.redo_button, 236)
        actions.addWidget(self.stop_button, 236)
        actions.addWidget(self.pulse_strip, 380)
        actions.addWidget(self.delete_all_button)
        actions.addWidget(self.parent_entry)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(OUTER_MARGIN_X, OUTER_MARGIN_Y, OUTER_MARGIN_X, OUTER_MARGIN_Y)
        layout.setSpacing(14)
        layout.addLayout(mode_bar)
        layout.addWidget(self.grid, 1)
        layout.addLayout(actions)

        # Keyboard: Strg+Z undo, Strg+Y / Strg+Umschalt+Z redo, ESC leaves the mode. No menus.
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcuts = [QShortcut(QKeySequence(keys), self)
                               for keys in ("Ctrl+Y", "Ctrl+Shift+Z")]
        for shortcut in self.redo_shortcuts:
            shortcut.activated.connect(self.redo)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.escape)

        controller.add_listener(weak_slot(self.refresh))
        controller.add_history_listener(weak_slot(self._history_requested, pass_signal_args=True))

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.refresh()

    # -------------------------------------------------------------- actions

    def press(self, pad: int) -> None:
        if not self._dialog_open:
            self.controller.press(pad)

    def _pad_down(self, pad: int) -> None:
        if not self._dialog_open:
            self.controller.press_down(pad)

    def _pad_up(self, pad: int) -> None:
        self._tap[pad] = self.controller.press_up(pad)

    def _pad_clicked(self, pad: int) -> None:
        if self._tap.pop(pad, True):
            self.press(pad)

    def _choose_mode(self, mode: Mode) -> None:
        self.controller.set_mode(mode)

    @staticmethod
    def _exec(dialog: QDialog) -> int:
        """Run a modal dialog and free it: a closed dialog is not kept as a hidden child of the window."""
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()

    def undo(self) -> None:
        self.controller.undo()

    def undo_pad(self, pad: int) -> None:
        """The "back" badge of a pad: take back the latest change of that pad only."""
        if not self._dialog_open:
            self.controller.undo(pad)

    def redo(self) -> None:
        self.controller.redo()

    def escape(self) -> None:
        self.controller.escape()

    def stop_all(self) -> None:
        self.controller.stop_all()

    def confirm_delete_all(self) -> None:
        dialog = self.confirm_factory(self)
        self._dialog_open = True
        try:
            accepted = self._exec(dialog) == QDialog.DialogCode.Accepted
        finally:
            self._dialog_open = False
        if accepted:
            self.controller.delete_all()
        self.refresh()

    def _history_requested(self, pad: int) -> None:
        # Open after the current press has been handled completely.
        QTimer.singleShot(0, lambda: self.open_history(pad))

    def open_history(self, pad: int) -> None:
        dialog = self.history_factory(self.controller, pad, self)
        self._dialog_open = True
        try:
            self._exec(dialog)
        finally:
            self._dialog_open = False
        self.refresh()

    def open_parent_area(self) -> None:
        """Parental gate, then the settings page. Pads are locked while either is open."""
        if self._dialog_open:
            return
        self._dialog_open = True
        try:
            if self._exec(self.gate_factory(self)) != QDialog.DialogCode.Accepted:
                return
            pages = self.parent_pages()
            dialog = self.settings_factory(
                self.config_path, self.controller.settings, self.apply_settings,
                self.settings_template, self, pages,
            )
            self._settings_dialog = dialog
            self._exec(dialog)
        finally:
            self._settings_dialog = None
            self._dialog_open = False
            self.refresh()

    def parent_pages(self) -> list[ParentPage]:
        """The areas of the parents' area behind the three settings pages: history, Erweitert, sets, export.

        A set that was opened ends the parents' area (the sets page says so through ``done``).
        """
        controller = self.controller
        # The builders hold the factories and the controller, not the window: the page tree must not keep
        # the window alive through a cycle (see ``weak_slot``).
        changes, advanced = self.changes_factory, self.advanced_factory
        sets, export = self.sets_factory, self.export_factory
        pages = [
            ParentPage("changes", "history", "Verlauf & Undo", lambda: changes(controller, None)),
            ParentPage("advanced", "layers", "Erweitert", lambda: advanced(controller, None)),
        ]
        if self.set_session is not None:
            session, on_open = self.set_session, self.on_open_set
            pages.append(ParentPage("sets", "save", "Sets", lambda: sets(session, on_open, None)))
        pages.append(ParentPage("export", "download", "Export", lambda: export(controller, None)))
        return pages

    @property
    def audio_devices(self) -> Any:
        """The audio engine if it can list devices (the settings page offers them), else None."""
        audio = self.controller.audio
        return audio if hasattr(audio, "device_groups") else None

    def apply_settings(self, settings: Settings) -> list[str]:
        """Live-apply ``settings``; returns the keys that need a restart."""
        restart = self.controller.apply_settings(settings)
        wanted = self.controller.settings
        if wanted.launchpad != (self.launchpad is not None) and self.launchpad_factory is not None:
            if self.launchpad is not None:
                self.launchpad.close()
            self._release_launchpad_holds()
            self.launchpad = self.launchpad_factory(wanted)
        if wanted.fullscreen != self.isFullScreen():
            if wanted.fullscreen:
                self.showFullScreen()
            else:
                self.showMaximized()
        return restart

    # ------------------------------------------------------------- refresh

    def _tick(self) -> None:
        self.controller.tick()
        if self.launchpad is not None:
            for pad, down in self.launchpad.poll_events():
                if down and not self._dialog_open:
                    self._launchpad_down.add(pad)
                    self.controller.press_down(pad)
                elif not down:
                    self._launchpad_down.discard(pad)
                    if self.controller.press_up(pad):
                        self.press(pad)
            if not self.launchpad.connected:
                self._release_launchpad_holds()
        elif self._launchpad_down:
            self._release_launchpad_holds()
        self.refresh()

    def _release_launchpad_holds(self) -> None:
        """No note off will come for keys that were down when the Launchpad went away."""
        for pad in self._launchpad_down:
            self.controller.cancel_hold(pad)
        self._launchpad_down.clear()

    def _overlay(self, mode: Mode, color: str, pad: int) -> str | None:
        """Small hint icon on a pad that shows what a press will do."""
        has_sample = self.controller.pad(pad).sample is not None
        if mode == Mode.RECORD:
            return "record"
        if mode == Mode.LOOP and has_sample:
            return "stop" if color == "green" else "loop"
        if mode == Mode.DELETE and has_sample:
            return "delete"
        if mode == Mode.HISTORY and self.controller.pad(pad).history:
            return "history"
        return None

    def _session_wave(self, pad: int, elapsed: float) -> float:
        """A new session began: a sky-blue wave runs once across the pads, top left first."""
        rows, cols = self.grid.rows, self.grid.cols
        row, col = divmod(pad, cols)
        spread = max(1, rows + cols - 2)
        delay = 0.15 + 0.75 * (row + col) / spread
        return max(0.0, 1.0 - abs(elapsed - delay) / SESSION_WAVE_WIDTH)

    def _update_pulse(self, colors: dict[int, str], waiting: set[int]) -> None:
        """Dots for the beats of the bar, lit softly by the grid; at rest when nothing plays.

        A grid that has just been set shows the pulse for a few seconds even if no loop runs
        yet (plan 2.2 rule 7). No grid in the session: dim dots.
        """
        controller = self.controller
        info = controller.grid_info()
        now = controller.now()
        key = None if info is None else (info.beats, round(info.seconds, 3))
        if key != self._grid_key:
            if self._grid_key is not _UNSET and info is not None:
                self._pulse_until = now + max(PULSE_CONFIRM_SECONDS, 2 * info.seconds)
            self._grid_key = key
        beats = controller.settings.beats_per_bar if info is None else info.beats
        playing = "green" in colors.values() or bool(waiting)
        lit = info is not None and (playing or now < self._pulse_until)
        position = controller.beat_position() if lit else None
        self.pulse_strip.set_pulse(beats, position)

    def refresh(self) -> None:
        """Bring every widget (and the Launchpad LEDs) in line with the controller."""
        controller = self.controller
        colors = controller.pad_colors()
        remaining = controller.recording_remaining()
        limit = controller.recording_limit()
        waiting = controller.waiting_pads()
        progress = controller.loop_progress() if waiting else None
        session = controller.session_shown()
        self.volume_slider.set_state(controller.volume, controller.volume_limit)
        clipping = controller.input_clipping()
        level = controller.input_level_stage()
        badge_pad = None if controller.recording_pad is not None else controller.last_change_pad()
        for pad in self.grid.pads:
            color = colors.get(pad.index, "white")
            sparkle = 0.0 if session is None else self._session_wave(pad.index, session)
            if pad.index in waiting:
                # Waits for the next loop start: pulsing frame, filling bar, no text.
                pad.set_look(color, None, None, 0.0, progress if progress is not None else 0.0, sparkle,
                             free=controller.is_free(pad.index))
            elif pad.index == controller.recording_pad and remaining is not None:
                pad.set_look(color, None, remaining, min(1.0, remaining / limit), None, sparkle,
                             clip=clipping, level=level, free=controller.is_free(pad.index))
            else:
                pad.set_look(color, self._overlay(controller.mode, color, pad.index), None, 0.0,
                             None, sparkle, badge=pad.index == badge_pad,
                             free=controller.is_free(pad.index), hold=controller.hold_progress(pad.index))

        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == controller.mode)
        self.frame.set_accent(MODE_ACCENT[controller.mode])  # every mode has its colour (mockups 01-07)
        self.undo_button.setEnabled(controller.can_undo() or controller.recording_pad is not None)
        self.redo_button.setEnabled(controller.can_redo())

        parts = [controller.notice(), controller.device_notice, *self.device_status]
        if self.launchpad is not None and self.launchpad.status_text:
            parts.append(self.launchpad.status_text)
        unique = list(dict.fromkeys(p for p in parts if p))
        self.pulse_strip.set_status("   ·   ".join(unique))
        self._update_pulse(colors, waiting)

        if self.launchpad is not None:
            self.launchpad.set_colors(colors)
