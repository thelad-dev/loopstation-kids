"""Parental gate: the way into the parents' area.

Two steps a six-year-old does not hit by accident: the small lock in the
corner of the window must be held for two seconds, and then a sum of two
two-digit numbers has to be answered. It keeps children out; it is not a
consent mechanism of any kind.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QIntValidator, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import TEXT, TEXT_DIM, big_font, weak_slot

HOLD_MS = 2000  # how long the lock has to be held (mockup 08)
ENTRY_SIZE = 20  # small and dim on purpose; it fits into the window margin


@dataclass(frozen=True)
class GateQuestion:
    text: str
    answer: int


def new_question(rng: random.Random | None = None) -> GateQuestion:
    """A sum of two two-digit numbers that needs carrying (too hard to guess for a young child)."""
    rng = rng or random.Random()
    while True:
        a, b = rng.randint(12, 49), rng.randint(12, 49)
        if a % 10 + b % 10 >= 10:
            return GateQuestion(f"{a} + {b} = ?", a + b)


class ParentEntryButton(QAbstractButton):
    """Small lock that fires ``held`` only after being pressed for ``HOLD_MS`` without letting go."""

    held = Signal()

    def __init__(self, parent: QWidget | None = None, hold_ms: int = HOLD_MS) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(ENTRY_SIZE, ENTRY_SIZE))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Eltern-Bereich")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(hold_ms)
        self._timer.timeout.connect(self._fire)
        self.pressed.connect(self._timer.start)
        self.released.connect(self._timer.stop)

    def _fire(self) -> None:
        self.setDown(False)
        self.held.emit()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        color = QColor(TEXT if self.isDown() else "#6E6E75")
        color.setAlpha(230 if self.isDown() else 160)
        draw_icon(painter, "lock", QRectF(self.rect()), color)
        painter.end()


# Colours of the parents' area (mockups 08 and 11).
PARENT_ACCENT = "#7FA7FF"
PARENT_PANEL = "#1F1F24"
KEY_SURFACE = "#26262B"


class _IconLabel(QWidget):
    """A small icon next to a title (the lock or the open lock of the parents' area)."""

    def __init__(self, icon: str, color: str, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._color = icon, QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        draw_icon(painter, self._icon, QRectF(self.rect()), self._color)
        painter.end()


class GateCard(QFrame):
    """The card with the sum: title, question, answer field, number pad and "Abbrechen".

    The in-window ``GateOverlay`` shows it over the child page. ``answered(bool)``
    tells whether the answer was right; ``cancelled`` is the way back without an answer.
    """

    answered = Signal(bool)
    cancelled = Signal()

    KEY_SIZE = QSize(108, 66)
    KEY_SIZE_COMPACT = QSize(96, 46)

    def __init__(self, question: GateQuestion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.question = question
        self.setObjectName("gate_card")
        self.setStyleSheet(
            f"#gate_card {{ background: {PARENT_PANEL}; border: 3px solid {PARENT_ACCENT}; "
            "border-radius: 28px; }")

        title = QLabel("Nur für Erwachsene")
        title.setFont(big_font(22))
        title.setStyleSheet(f"color: {TEXT.name()};")
        title_row = QGridLayout()
        title_row.addWidget(_IconLabel("lock", PARENT_ACCENT, 40), 0, 0)
        title_row.addWidget(title, 0, 1)
        title_row.setColumnStretch(2, 1)

        self.question_label = QLabel(self._question_text())
        self.question_label.setFont(big_font(28))
        self.question_label.setStyleSheet(f"color: {TEXT.name()};")
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.answer_edit = QLineEdit()
        self.answer_edit.setValidator(QIntValidator(0, 999, self))
        self.answer_edit.setMaxLength(3)
        self.answer_edit.setFont(big_font(30))
        self.answer_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.answer_edit.setFixedSize(280, 72)
        self.answer_edit.setStyleSheet(
            f"QLineEdit {{ color: {TEXT.name()}; background: {KEY_SURFACE}; "
            f"border: 2px solid {PARENT_ACCENT}; border-radius: 18px; }}")
        self.answer_edit.returnPressed.connect(self.check)

        pad = QGridLayout()
        pad.setSpacing(12)
        self.keys: dict[str, QPushButton] = {}
        for index, label in enumerate([*"123456789", "⌫", "0", "OK"]):
            key = self._key(label)
            self.keys[label] = key
            pad.addWidget(key, index // 3, index % 3)
        self.keys["⌫"].clicked.connect(self._backspace)
        self.keys["OK"].clicked.connect(self.check)
        self._pad = pad

        self.cancel_button = QPushButton("Abbrechen, zurück zur Kinderseite")
        self.cancel_button.setFlat(True)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_button.setStyleSheet(
            f"QPushButton {{ color: {TEXT_DIM.name()}; font-size: 15px; font-weight: bold; border: none; "
            "padding: 10px; }")
        self.cancel_button.clicked.connect(self.cancelled)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(40, 32, 40, 24)
        self.body.setSpacing(16)
        self.body.addLayout(title_row)
        self.body.addWidget(self.question_label)
        self.body.addWidget(self.answer_edit, 0, Qt.AlignmentFlag.AlignCenter)
        self.body.addLayout(pad)
        self.body.addWidget(self.cancel_button)

    def set_compact(self, compact: bool) -> None:
        """Smaller keys and gaps, so the card fits a low window (1024 x 640)."""
        size = self.KEY_SIZE_COMPACT if compact else self.KEY_SIZE
        for key in self.keys.values():
            key.setFixedSize(size)
        self._pad.setSpacing(8 if compact else 12)
        self.answer_edit.setFixedSize(280, 58 if compact else 72)
        self.body.setSpacing(8 if compact else 16)
        self.body.setContentsMargins(40, 18 if compact else 32, 40, 10 if compact else 24)

    def _question_text(self) -> str:
        return "Wie viel ist " + self.question.text.removesuffix(" = ?") + " ?"

    def _key(self, label: str) -> QPushButton:
        key = QPushButton(label)
        key.setFixedSize(self.KEY_SIZE)
        key.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if label == "OK":
            style = f"background: {PARENT_ACCENT}; color: #111114;"
        else:
            style = f"background: {KEY_SURFACE}; color: {TEXT.name()};"
        key.setStyleSheet(f"QPushButton {{ {style} border: none; border-radius: 16px; "
                          "font-size: 26px; font-weight: bold; }")
        if label.isdigit():
            key.clicked.connect(weak_slot(self._type, label))
        return key

    def _type(self, digit: str) -> None:
        if len(self.answer_edit.text()) < self.answer_edit.maxLength():
            self.answer_edit.setText(self.answer_edit.text() + digit)

    def _backspace(self) -> None:
        self.answer_edit.setText(self.answer_edit.text()[:-1])

    def check(self) -> bool:
        """Report whether the typed answer is right (``answered``); returns the same."""
        text = self.answer_edit.text().strip()
        right = text.isdigit() and int(text) == self.question.answer
        self.answered.emit(right)
        return right


DIM_ALPHA = 150  # how dark the overlay makes the child page beneath it (of 255)
OVERLAY_HINT = "Zahl eingeben · Musik läuft weiter · Esc bricht ab"
OVERLAY_MARGIN = 12  # least room between the card and the edge of the window


def keep_open_text(minutes: int) -> str:
    unit = "Minute" if minutes == 1 else "Minuten"
    return f"Sperre {minutes} {unit} offen lassen"


class GateOverlay(QWidget):
    """The sum as a layer over the whole window (mockup L2-09): no modal dialog, the music goes on.

    It covers its parent completely and takes every click and key, so nothing reaches the pads
    below. ``answered(bool)`` reports the answer (right or wrong), ``cancelled`` the way back
    (the "Abbrechen" button or Esc). ``keep_open`` is the switch "Sperre N Minuten offen lassen";
    it is only shown when ``unlock_minutes`` is above 0.
    """

    answered = Signal(bool)
    cancelled = Signal()

    def __init__(self, parent: QWidget, unlock_minutes: int = 0,
                 question: GateQuestion | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gate_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.unlock_minutes = unlock_minutes
        self.card = GateCard(question or new_question(), self)
        self.card.answered.connect(self.answered)
        self.card.cancelled.connect(self.cancelled)

        self.hint = QLabel(OVERLAY_HINT)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px; background: transparent;")
        self.keep_open = QPushButton(keep_open_text(unlock_minutes))
        self.keep_open.setCheckable(True)
        self.keep_open.setChecked(False)
        self.keep_open.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.keep_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.keep_open.setStyleSheet(
            f"QPushButton {{ color: {TEXT_DIM.name()}; background: {KEY_SURFACE}; "
            "border: 1.5px solid #3A3A41; border-radius: 12px; font-size: 15px; font-weight: bold; "
            "min-height: 40px; padding: 0 18px; } "
            f"QPushButton:checked {{ color: {TEXT.name()}; border-color: {PARENT_ACCENT}; }}")
        self.keep_open.setVisible(unlock_minutes > 0)
        self.keep_open.toggled.connect(weak_slot(self._show_keep_open, pass_signal_args=True))
        self._show_keep_open(False)
        # Hint and switch sit between the number pad and "Abbrechen".
        body = self.card.body
        at = body.indexOf(self.card.cancel_button)
        body.insertWidget(at, self.hint)
        body.insertWidget(at + 1, self.keep_open)
        parent.installEventFilter(self)
        self._fit()

    def _show_keep_open(self, on: bool) -> None:
        """A tick in front of the words while the lock is to stay open."""
        pixmap = QPixmap(26, 18)  # the tick on the left, the rest keeps it apart from the words
        pixmap.fill(Qt.GlobalColor.transparent)
        if on:
            painter = QPainter(pixmap)
            draw_icon(painter, "check", QRectF(0, 0, 18, 18), QColor(PARENT_ACCENT))
            painter.end()
        self.keep_open.setIconSize(pixmap.size())
        self.keep_open.setIcon(QIcon(pixmap))

    @property
    def keep_unlocked(self) -> bool:
        """Is the lock to stay open after a right answer (the setting allows it and the switch was turned on)?"""
        return self.unlock_minutes > 0 and self.keep_open.isChecked()

    def open(self) -> None:
        self._fit()
        self.show()
        self.raise_()
        self.card.answer_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _fit(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self.card.set_compact(parent.height() < 760)
        self.card.setFixedWidth(min(620, parent.width() - 2 * OVERLAY_MARGIN))
        self.card.adjustSize()
        height = min(self.card.sizeHint().height(), parent.height() - 2 * OVERLAY_MARGIN)
        self.card.setFixedHeight(height)
        self.card.move((self.width() - self.card.width()) // 2, (self.height() - height) // 2)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._fit()
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        # Every key ends here: Esc cancels, nothing else reaches the window or the pads.
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        event.accept()  # a click beside the card does nothing (it never reaches a pad)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        event.accept()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, DIM_ALPHA))
        painter.end()
