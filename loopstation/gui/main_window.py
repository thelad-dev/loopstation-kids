"""Main window: mode bar, pad grid, action buttons and a small status line.

The window only talks to the controller (and mirrors colours to the
Launchpad); it contains no audio, MIDI or event-store logic of its own.

It has two states: the child page (``frame``) and the parents' pad view
(``parent_view``, Loopstation 2 variant A). The way from the children to the
parents is the held lock plus a sum that lies over the window (``GateOverlay``);
within ``parent_hold_minutes`` after a right answer the sum is skipped. The way
back is one tap on "Kinder" or F1. The music goes on throughout.

The tools of the parents' view open as side panels next to the pads, in this window; nothing of
them is modal, so the pads and the Launchpad keep working while one is open.
"""

from __future__ import annotations

import math
import time
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from loopstation.config import DEFAULT_CONFIG_NAME, Settings
from loopstation.controller import Controller, Mode
from loopstation.gui.changes_page import ChangesPage
from loopstation.gui.export_dialog import ExportPage
from loopstation.gui.history_dialog import HistoryDialog
from loopstation.gui.pad_button import MIN_PAD_SIZE, PadButton
from loopstation.gui.parent_gate import GateOverlay
from loopstation.gui.parent_tile import ParentTile
from loopstation.gui.parent_view import ParentView, WaveCache
from loopstation.gui.pulse_strip import PulseStrip, glow_levels
from loopstation.gui.sets_page import SetsPage
from loopstation.gui.settings_panels import SETTINGS_PANELS, SettingsPanels
from loopstation.gui.side_panel import SAVED_LINE, flatten_cards
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

# Settings the window takes over while the app runs (the controller does not use them).
PARENT_VIEW_SETTINGS = ("parent_hold_minutes", "parent_hold_until_exit", "parent_idle_minutes")

# Input that counts as "the parents are still here" (the idle return of the parents' view).
INPUT_EVENTS = (
    QEvent.Type.MouseButtonPress,
    QEvent.Type.KeyPress,
    QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
)
# Keys of the parents' view (none of them acts on the child page).
ARROWS = {
    Qt.Key.Key_Left: (0, -1),
    Qt.Key.Key_Right: (0, 1),
    Qt.Key.Key_Up: (-1, 0),
    Qt.Key.Key_Down: (1, 0),
}
ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)  # unfold or fold the detail panel of the chosen pad
MARKER_KEY = Qt.Key.Key_M  # a marker at the cursor of the wave in the detail panel
# Head of each side panel: (icon, title, line under the title).
TOOL_HEADS = {
    "changes": ("history", "Verlauf", "Zurück und Wieder, die Änderungen aller Pads"),
    "sets": ("save", "Sets", "Die Sitzung sichern oder ein Set öffnen"),
    "export": ("download", "Export", "Die Summe oder einzelne Loops als WAV"),
    "levels": ("sliders", "Pegel", SAVED_LINE),
    "devices": ("headphones", "Geräte", SAVED_LINE),
    "tempo": ("pulse", "Takt", SAVED_LINE),
    "system": ("gear", "System", SAVED_LINE),
}
PAD_KEYS = {
    Qt.Key.Key_Space: Mode.PLAY,
    Qt.Key.Key_L: Mode.LOOP,
    Qt.Key.Key_R: Mode.RECORD,
    Qt.Key.Key_Delete: Mode.DELETE,
}


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
        # A real modal dialog is open (the children's history): pads and Launchpad wait.
        self._dialog_open = False
        # The parents' view: built when it is entered, gone again on the child page (with its panels).
        self.parent_view: ParentView | None = None
        self.settings_panels: SettingsPanels | None = None
        self.gate_overlay: GateOverlay | None = None
        # Lock time and idle time run on a monotonic clock (a change of the wall clock must not open
        # the lock or keep the parents' view open); tests hand in their own clock.
        self.clock: Callable[[], float] = time.monotonic
        self._unlocked_until = 0.0  # ``clock`` time until which the lock opens without a sum
        self._last_input = 0.0  # ``clock`` time of the last screen or keyboard input in the parents' view
        # Last parent-side input (also ends the unlock window on the child page).
        self._last_parent_input = 0.0
        self._hold_minutes = controller.settings.parent_hold_minutes
        self._hold_until_exit = controller.settings.parent_hold_until_exit
        self._idle_minutes = controller.settings.parent_idle_minutes
        self._waves = WaveCache()  # mini waves of the tiles, kept across visits
        self._parent_selected = 0
        # Pads held on the screen (child pads and the start fields of the tiles); let go on a change of view.
        self._screen_down: set[int] = set()
        # Factories so tests can replace the modal dialogs.
        self.history_factory: Callable[[Controller, int, QWidget], QDialog] = HistoryDialog
        # The pages of the side panels of the parents' view (widgets, built on their first visit).
        self.export_factory: Callable[[Controller, QWidget | None], QWidget] = ExportPage
        self.sets_factory: Callable[..., QWidget] = SetsPage
        self.changes_factory: Callable[[Controller, QWidget | None], QWidget] = ChangesPage

        self.setWindowTitle("Loopstation")
        # The child page and (while it is shown) the parents' view share one stack in the window.
        self.frame = Frame()
        self.view_host = QWidget()
        self.view_stack = QStackedLayout(self.view_host)
        self.view_stack.addWidget(self.frame)
        self.setCentralWidget(self.view_host)

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
        # line, and the lock tile. "Alle löschen" lives only in the parents' area (history page).
        self.undo_button = BigButton("undo", "Zurück", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = BigButton("redo", "Wiederholen", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.redo_button.clicked.connect(self.redo)
        self.stop_button = BigButton("stop", "Alles still", ACCENT_GRAY, font_pt=BAR_FONT_PT, pad_x=BAR_PAD_X,
                                     min_height=ACTION_HEIGHT)
        self.stop_button.clicked.connect(self.stop_all)
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
        # F1 leads from the parents' view back to the children, never the other way.
        self.kids_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F1), self)
        self.kids_shortcut.activated.connect(self.leave_parent_mode)
        # Strg+Umschalt+L locks the parents' area at once (same as the "Sperren" button).
        self.lock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        self.lock_shortcut.activated.connect(self.lock_parent_area)

        controller.add_listener(weak_slot(self.refresh))
        controller.add_history_listener(weak_slot(self._history_requested, pass_signal_args=True))

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.refresh()

    # -------------------------------------------------------------- actions

    @property
    def _inputs_locked(self) -> bool:
        """A dialog or the sum is open: no new press reaches a pad (what plays goes on)."""
        return self._dialog_open or self.gate_overlay is not None

    def press(self, pad: int) -> None:
        if not self._inputs_locked:
            self.controller.press(pad)

    def _pad_down(self, pad: int) -> None:
        if not self._inputs_locked:
            self._screen_down.add(pad)
            self.controller.press_down(pad)

    def _pad_up(self, pad: int) -> None:
        self._screen_down.discard(pad)
        self._tap[pad] = self.controller.press_up(pad)

    def _tile_down(self, pad: int) -> None:
        """A press on the start field of a tile in the parents' view (as a finger on a child pad)."""
        self._pad_down(pad)

    def _tile_up(self, pad: int, inside: bool) -> None:
        """The start field is let go: a tap there acts like a tap on the pad ("Spielen")."""
        self._screen_down.discard(pad)
        if self.controller.press_up(pad) and inside:
            self.press(pad)

    def press_as(self, pad: int, mode: Mode) -> None:
        """A key of the parents' view: press ``pad`` as in ``mode``, then back to "Spielen"."""
        if self._inputs_locked:
            return
        controller = self.controller
        if controller.mode != mode:
            controller.set_mode(mode)
        controller.press(pad)
        if controller.mode != Mode.PLAY:
            controller.set_mode(Mode.PLAY)

    def _release_screen_holds(self) -> None:
        """Let go of every pad held on the screen: its release will not come (view change, focus lost)."""
        for pad in self._screen_down:
            self.controller.cancel_hold(pad)
            self._tap.pop(pad, None)
        self._screen_down.clear()
        for pad in self.grid.pads:
            if pad.isDown():
                pad.setDown(False)
        if self.parent_view is not None:
            self.parent_view.let_go()

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
        if self.gate_overlay is None:
            self.controller.undo()

    def undo_pad(self, pad: int) -> None:
        """The "back" badge of a pad: take back the latest change of that pad only."""
        if not self._inputs_locked:
            self.controller.undo(pad)

    def redo(self) -> None:
        if self.gate_overlay is None:
            self.controller.redo()

    def escape(self) -> None:
        if self.gate_overlay is not None:
            self._close_gate()  # Esc cancels the sum
            return
        if self.parent_view is not None and self.parent_view.panel_key is not None:
            self.close_tool()  # Esc closes the side panel (the top layer)
            return
        if self.parent_view is not None and self.parent_view.detail.is_open:
            self.parent_view.detail.set_open(False)  # then the unfolded detail panel
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self.controller.escape()

    def stop_all(self) -> None:
        self.controller.stop_all()

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

    # ---------------------------------------------------------- parents' view

    @property
    def parent_mode(self) -> bool:
        """Is the parents' view shown (instead of the child page)?"""
        return self.parent_view is not None

    def open_parent_area(self) -> None:
        """The lock was held: the sum over the window, then the parents' view.

        Within the unlock window after a right answer the sum is skipped. Nothing happens while
        the sum, the parents' view or a dialog is already open.
        """
        if self._dialog_open or self.parent_view is not None or self.gate_overlay is not None:
            return
        if self._is_unlocked():
            self.enter_parent_mode()
            return
        self._release_screen_holds()
        overlay = GateOverlay(self.view_host)
        overlay.answered.connect(weak_slot(self._gate_answered, pass_signal_args=True))
        overlay.cancelled.connect(weak_slot(self._close_gate))
        self.gate_overlay = overlay
        overlay.open()

    def _gate_answered(self, right: bool) -> None:
        self._close_gate()
        if right:
            self._grant_unlock()
            self.enter_parent_mode()

    def _close_gate(self) -> None:
        """Take the sum away; the keyboard goes back to the window (Esc, Strg+Z work at once)."""
        overlay = self.gate_overlay
        if overlay is None:
            return
        self.gate_overlay = None
        overlay.card.answer_edit.clearFocus()
        overlay.hide()
        overlay.deleteLater()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _is_unlocked(self) -> bool:
        """May the lock open the parents' view without a new sum?"""
        return self.clock() < self._unlocked_until

    def _unlock_deadline(self) -> float:
        """``clock`` time until which the lock stays open (``inf`` = until the program ends)."""
        if self._hold_until_exit:
            return float("inf")
        return self.clock() + 60 * self._hold_minutes

    def _grant_unlock(self) -> None:
        """Right answer: open the unlock window from now (and note parent input)."""
        self._unlocked_until = self._unlock_deadline()
        self._note_parent_input()

    def _extend_unlock(self) -> None:
        """Parent input slides the unlock window forward while it is still open."""
        if not self._is_unlocked():
            return
        self._unlocked_until = self._unlock_deadline()

    def _clear_unlock(self) -> None:
        self._unlocked_until = 0.0

    def _note_parent_input(self) -> None:
        now = self.clock()
        self._last_input = now
        self._last_parent_input = now

    def lock_parent_area(self) -> None:
        """Close the unlock window at once and leave the parents' view (button or shortcut)."""
        if self.parent_view is None and not self._is_unlocked():
            return
        self._clear_unlock()
        self.leave_parent_mode()

    def enter_parent_mode(self) -> None:
        """Show the parents' view in this window. The children's mode becomes "Spielen"."""
        if self.parent_view is not None:
            return
        self._release_screen_holds()
        controller = self.controller
        if controller.mode != Mode.PLAY:
            controller.set_mode(Mode.PLAY)
        view = ParentView(controller, self._waves, self.set_session is not None, self._parent_selected)
        # The detail panel shows two settings with the inputs of the settings panels (one way of saving).
        # It holds the window weakly: the view must not keep it alive through a cycle (see ``weak_slot``).
        panels = weakref.WeakMethod(self._settings_panels)
        view.detail.settings_source = lambda: (method() if (method := panels()) is not None else None)
        view.kids_requested.connect(weak_slot(self.leave_parent_mode))
        view.lock_requested.connect(weak_slot(self.lock_parent_area))
        view.tool_requested.connect(weak_slot(self.open_tool, pass_signal_args=True))
        view.pads_touched.connect(weak_slot(self._keys_to_the_view))
        view.pad_down.connect(weak_slot(self._tile_down, pass_signal_args=True))
        view.pad_up.connect(weak_slot(self._tile_up, pass_signal_args=True))
        view.undo_requested.connect(weak_slot(self.undo))
        view.redo_requested.connect(weak_slot(self.redo))
        view.stop_requested.connect(weak_slot(self.stop_all))
        view.detail.fold_changed.connect(weak_slot(self._detail_folded))
        self.parent_view = view
        self.view_stack.addWidget(view)
        self.view_stack.setCurrentWidget(view)
        self._note_parent_input()
        if self._is_unlocked():
            self._extend_unlock()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.refresh()

    def leave_parent_mode(self) -> None:
        """Back to the child page (the switch, F1 or the idle time). The unlock window stays."""
        view = self.parent_view
        if view is None:
            return
        self._release_screen_holds()
        self._parent_selected = view.selected
        if self.settings_panels is not None:
            self.settings_panels.flush()  # a number in its pause or a text still being typed is saved
        self.parent_view = None
        self.settings_panels = None  # a child of the view: it goes with it
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.view_stack.setCurrentWidget(self.frame)
        self.view_stack.removeWidget(view)
        view.hide()
        view.deleteLater()
        self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """The window closes (the app ends, or a set is opened): leave the parents' view first.

        That saves what still waits in a panel and takes the input watch off the application. Left on, it
        would outlive the window: the application would hand every later event to a window that is gone.
        The unlock window dies with the process; a fresh start asks the sum again.
        """
        self.leave_parent_mode()
        super().closeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        # Installed on the application only while the parents' view is shown: any input keeps it open
        # and slides the unlock window forward.
        if self.parent_view is not None and event.type() in INPUT_EVENTS:
            self._note_parent_input()
            self._extend_unlock()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        """Keys of the parents' view: arrows choose, Leertaste plays, L loop, R record, Entf delete."""
        view = self.parent_view
        key = event.key()
        focus = QApplication.focusWidget()
        if (view is None or self._dialog_open or self.gate_overlay is not None
                or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
                or (focus is not None and self._in_a_panel(focus))  # typing in a panel
                or key not in (*ARROWS, *PAD_KEYS, *ENTER_KEYS, MARKER_KEY)):
            super().keyPressEvent(event)
            return
        if key in ENTER_KEYS:
            if not event.isAutoRepeat():
                view.toggle_detail()
                self.setFocus(Qt.FocusReason.OtherFocusReason)
        elif key == MARKER_KEY:
            if not event.isAutoRepeat():
                view.detail.place_marker()
        elif key in ARROWS:
            view.move_selection(*ARROWS[Qt.Key(key)])
        elif not event.isAutoRepeat():
            self.press_as(view.selected, PAD_KEYS[Qt.Key(key)])
        event.accept()

    def _in_a_panel(self, widget: QWidget) -> bool:
        """Is ``widget`` part of the side panel or the detail panel (keys typed there stay there)?"""
        view = self.parent_view
        return view is not None and (view.side_panel.isAncestorOf(widget) or view.detail.isAncestorOf(widget))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self._release_screen_holds()  # no release will reach a pad of a window that lost the focus

    # ---------------------------------------------------------- side panels

    def open_tool(self, key: str) -> None:
        """Open the side panel of the tool ``key`` beside the pads; that tool again or "Pads" closes it."""
        view = self.parent_view
        if view is None:
            return
        if key == "pads" or key == view.panel_key:
            self.close_tool()
            return
        if key not in TOOL_HEADS or (key == "sets" and self.set_session is None):
            return
        widget = view.side_panel.page(key)
        if widget is None:
            widget = self._build_tool(key)
            flatten_cards(widget)  # sections of the panel, as on the settings panels (mockup L2-05)
        icon, title, line = TOOL_HEADS[key]
        view.open_panel(key, icon, title, line, widget)
        self.setFocus(Qt.FocusReason.OtherFocusReason)  # the keys stay with the view until a field is tapped
        panels = self.settings_panels
        if key in SETTINGS_PANELS and panels is not None and panels.level == "error":
            view.side_panel.say(panels.message, panels.level)  # a refused value is still shown
        self._last_input = self.clock()

    def _keys_to_the_view(self) -> None:
        """A tile was pressed: the keys belong to the pads again, not to a field of the panel.

        Taking the focus ends the editing of a field (it saves what it shows, as on leaving any field).
        """
        view = self.parent_view
        focus = QApplication.focusWidget()
        if view is not None and focus is not None and self._in_a_panel(focus):
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def close_tool(self) -> None:
        """Close the side panel; the pads take the whole width again."""
        if self.parent_view is not None:
            self.parent_view.close_panel()
            self.setFocus(Qt.FocusReason.OtherFocusReason)  # the keys of the view work again

    def _build_tool(self, key: str) -> QWidget:
        """The page of the tool ``key``, built on its first visit (kept while the parents' view is shown).

        The builders hold the controller and the panels, not the window: the page tree must not keep the
        window alive through a cycle (see ``weak_slot``).
        """
        controller = self.controller
        if key in SETTINGS_PANELS:
            return self._settings_panels().page(key)
        if key == "changes":
            return self.changes_factory(controller, None)
        if key == "export":
            return self.export_factory(controller, None)
        page = self.sets_factory(self.set_session, self.on_open_set, None)  # "sets"
        done = getattr(page, "done", None)
        if done is not None:
            done.connect(weak_slot(self._sets_done, pass_signal_args=True))
        return page

    def _settings_panels(self) -> SettingsPanels:
        panels = self.settings_panels
        if panels is None:
            panels = SettingsPanels(self.config_path, self.controller.settings, self.apply_settings,
                                    self.settings_template, self.controller, self.audio_devices,
                                    self.parent_view)
            panels.said.connect(weak_slot(self._panels_said, pass_signal_args=True))
            self.settings_panels = panels
        return panels

    def _panels_said(self, text: str, level: str) -> None:
        """What the settings say (saved, refused) goes to the head of the open side panel, else to the
        detail panel (folded: in its line). A save that comes from a pause after another panel opened is
        shown there, not lost; "" takes the message away wherever it is."""
        view = self.parent_view
        if view is None:
            return
        if not text:
            view.side_panel.say("")
            view.detail.say("")
        elif view.panel_key is not None:
            view.side_panel.say(text, level)
            view.detail.say("")
        else:
            view.detail.say(text, level)

    def _detail_folded(self) -> None:
        """The detail panel folded or unfolded (a side panel may have closed for it): the keys go to the
        pads again, not to a field that is no longer in sight."""
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sets_done(self, _opened: bool) -> None:
        """The sets page is done: close the panel.

        After an opened set the app rebuilds the window on the new session.
        """
        self.close_tool()

    @property
    def audio_devices(self) -> Any:
        """The audio engine if it can list devices (the settings page offers them), else None."""
        audio = self.controller.audio
        return audio if hasattr(audio, "device_groups") else None

    def apply_settings(self, settings: Settings) -> list[str]:
        """Live-apply ``settings``; returns the keys that need a restart."""
        restart = self.controller.apply_settings(settings)
        # The parents' view keeps its own two values (the controller does not need them).
        self._hold_minutes = settings.parent_hold_minutes
        self._hold_until_exit = settings.parent_hold_until_exit
        self._idle_minutes = settings.parent_idle_minutes
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
                if down and not self._inputs_locked:
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
        self._check_idle()
        self.refresh()

    def _check_idle(self) -> None:
        """Idle handling for the parents' view and for an open unlock window on the child page.

        No screen or keyboard input in the parents' view for ``parent_idle_minutes``: back to the
        child page (an open side panel goes with it). The unlock window stays until it expires, the
        parents lock it, or the child page sits without parent input for the same idle time.
        """
        if self._idle_minutes <= 0:
            return
        idle_after = 60 * self._idle_minutes
        if self.parent_view is not None:
            if self.clock() - self._last_input >= idle_after:
                self.leave_parent_mode()
            return
        if self._hold_until_exit:
            return
        if self._is_unlocked() and self.clock() - self._last_parent_input >= idle_after:
            self._clear_unlock()

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

    def _update_pulse(self, colors: dict[int, str], waiting: set[int]) -> tuple[float, ...]:
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
        return glow_levels(beats, position)

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
                # Waits for the next loop start: full colour and symbol, slow glow, filling bar, no text.
                pad.set_look(color, self._overlay(controller.mode, color, pad.index), None, 0.0,
                             progress if progress is not None else 0.0, sparkle,
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
        levels = self._update_pulse(colors, waiting)
        if self.parent_view is not None:
            self.parent_view.refresh(colors, levels)
            self.parent_view.set_unlock_remaining(self._unlock_remaining_text())

        if self.launchpad is not None:
            self.launchpad.set_colors(colors)

    def _unlock_remaining_text(self) -> str:
        """Short remaining-time label for the parents' view (empty when the lock is shut)."""
        if not self._is_unlocked():
            return ""
        if self._hold_until_exit or not math.isfinite(self._unlocked_until):
            return "offen"
        seconds = max(0, int(self._unlocked_until - self.clock()))
        minutes = (seconds + 59) // 60  # round up to whole minutes still open
        if minutes <= 0:
            return ""
        return f"noch {minutes} Min"
