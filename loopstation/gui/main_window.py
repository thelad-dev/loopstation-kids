"""Main window: mode bar, pad grid, action buttons and a small status line.

The window only talks to the controller (and mirrors colours to the
Launchpad); it contains no audio, MIDI or event-store logic of its own.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPaintEvent, QPen, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller, Mode
from loopstation.gui.confirm_dialog import ConfirmDialog
from loopstation.gui.history_dialog import HistoryDialog
from loopstation.gui.pad_button import MIN_PAD_SIZE, PadButton
from loopstation.gui.widgets import (
    ACCENT_BLUE,
    ACCENT_GRAY,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PURPLE,
    ACCENT_RED,
    BACKGROUND,
    TEXT_DIM,
    BigButton,
    big_font,
)
from loopstation.midi.launchpad import LaunchpadController

TICK_MS = 30
SESSION_WAVE_WIDTH = 0.3  # seconds a pad stays lit while the new-session wave passes
PAD_GAP = 8  # visible gap is larger: each pad keeps a margin for its glow

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
            # A faint wash of the mode colour plus a clear coloured border.
            wash = QColor(self.accent)
            wash.setAlpha(22)
            painter.fillRect(self.rect(), wash)
            painter.setPen(QPen(self.accent, 8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 4, -4, -4), 22, 22)
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: Controller,
        launchpad: LaunchpadController | None = None,
        device_status: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.launchpad = launchpad
        self.device_status = list(device_status or [])
        self._dialog_open = False
        # Factories so tests can replace the modal dialogs.
        self.confirm_factory: Callable[[QWidget], QDialog] = ConfirmDialog
        self.history_factory: Callable[[Controller, int, QWidget], QDialog] = HistoryDialog

        self.setWindowTitle("Loopstation")
        self.frame = Frame()
        self.setCentralWidget(self.frame)

        # Mode bar.
        self.mode_buttons: dict[Mode, BigButton] = {}
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(14)
        for mode, icon, word, accent in MODES:
            button = BigButton(icon, word, accent, checkable=True, stacked=True)
            button.clicked.connect(lambda _checked=False, m=mode: self._choose_mode(m))
            self.mode_buttons[mode] = button
            mode_bar.addWidget(button, 1)  # equal widths

        # Pads.
        rows, cols = controller.settings.rows, controller.settings.cols
        self.grid = PadGrid(rows, cols)
        for pad in self.grid.pads:
            pad.clicked.connect(lambda _checked=False, i=pad.index: self.press(i))

        # Action buttons. "Alle löschen" sits apart on the right.
        self.undo_button = BigButton("undo", "Zurück", ACCENT_GRAY)
        self.undo_button.clicked.connect(self.undo)
        self.stop_button = BigButton("stop", "Alles still", ACCENT_GRAY)
        self.stop_button.clicked.connect(self.stop_all)
        self.delete_all_button = BigButton("trash", "Alle löschen", ACCENT_RED)
        self.delete_all_button.clicked.connect(self.confirm_delete_all)
        # Small, unobtrusive status text in the gap between the buttons.
        self.status_label = QLabel("")
        self.status_label.setFont(big_font(13, bold=False))
        self.status_label.setStyleSheet(f"color: {TEXT_DIM.name()};")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.addWidget(self.undo_button, 2)
        actions.addWidget(self.stop_button, 2)
        actions.addWidget(self.status_label, 2)
        actions.addWidget(self.delete_all_button, 2)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)
        layout.addLayout(mode_bar)
        layout.addWidget(self.grid, 1)
        layout.addLayout(actions)

        # Keyboard: Strg+Z undo, ESC leaves the mode. No menus.
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.escape)

        controller.add_listener(self.refresh)
        controller.add_history_listener(self._history_requested)

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.refresh()

    # -------------------------------------------------------------- actions

    def press(self, pad: int) -> None:
        if not self._dialog_open:
            self.controller.press(pad)

    def _choose_mode(self, mode: Mode) -> None:
        self.controller.set_mode(mode)

    def undo(self) -> None:
        self.controller.undo()

    def escape(self) -> None:
        self.controller.escape()

    def stop_all(self) -> None:
        self.controller.stop_all()

    def confirm_delete_all(self) -> None:
        dialog = self.confirm_factory(self)
        self._dialog_open = True
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
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
            dialog.exec()
        finally:
            self._dialog_open = False
        self.refresh()

    # ------------------------------------------------------------- refresh

    def _tick(self) -> None:
        self.controller.tick()
        if self.launchpad is not None:
            for pad in self.launchpad.poll():
                self.press(pad)
        self.refresh()

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

    def refresh(self) -> None:
        """Bring every widget (and the Launchpad LEDs) in line with the controller."""
        controller = self.controller
        colors = controller.pad_colors()
        remaining = controller.recording_remaining()
        limit = controller.recording_limit()
        waiting = controller.waiting_pads()
        progress = controller.loop_progress() if waiting else None
        session = controller.session_shown()
        for pad in self.grid.pads:
            color = colors.get(pad.index, "white")
            sparkle = 0.0 if session is None else self._session_wave(pad.index, session)
            if pad.index in waiting:
                # Waits for the next loop start: pulsing frame, filling bar, no text.
                pad.set_look(color, None, None, 0.0, progress if progress is not None else 0.0, sparkle)
            elif pad.index == controller.recording_pad and remaining is not None:
                pad.set_look(color, None, remaining, min(1.0, remaining / limit), None, sparkle)
            else:
                pad.set_look(color, self._overlay(controller.mode, color, pad.index), None, 0.0,
                             None, sparkle)

        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == controller.mode)
        self.frame.set_accent(None if controller.mode == Mode.PLAY else MODE_ACCENT[controller.mode])
        self.undo_button.setEnabled(controller.can_undo() or controller.recording_pad is not None)

        parts = [controller.notice(), *self.device_status]
        if self.launchpad is not None and self.launchpad.status_text:
            parts.append(self.launchpad.status_text)
        unique = list(dict.fromkeys(p for p in parts if p))
        text = "   ·   ".join(unique)
        if text != self.status_label.text():
            self.status_label.setText(text)

        if self.launchpad is not None:
            self.launchpad.set_colors(colors)
