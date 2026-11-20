"""Parental gate: the way into the parents' area.

Two steps a six-year-old does not hit by accident: the small lock in the
corner of the window must be held for two seconds, and then a sum of two
two-digit numbers has to be answered. It keeps children out; it is not a
consent mechanism of any kind.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import TEXT, TEXT_DIM, big_font

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


class ParentGate(QDialog):
    """Asks one sum on a big number pad; ``exec()`` is Accepted only for the right answer.

    A wrong answer simply closes the dialog (back to the child page, no alarm).
    """

    def __init__(self, parent: QWidget | None = None, question: GateQuestion | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Für Erwachsene")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.question = question or new_question()

        card = QFrame()
        card.setObjectName("gate_card")
        card.setStyleSheet(
            f"#gate_card {{ background: {PARENT_PANEL}; border: 3px solid {PARENT_ACCENT}; "
            "border-radius: 28px; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

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
        # Back-compat names for the two buttons the dialog is driven by.
        self.ok_button = self.keys["OK"]

        self.cancel_button = QPushButton("Abbrechen – zurück zur Kinderseite")
        self.cancel_button.setFlat(True)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setStyleSheet(
            f"QPushButton {{ color: {TEXT_DIM.name()}; font-size: 15px; font-weight: bold; border: none; "
            "padding: 10px; }")
        self.cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 32, 40, 24)
        layout.setSpacing(16)
        layout.addLayout(title_row)
        layout.addWidget(self.question_label)
        layout.addWidget(self.answer_edit, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(pad)
        layout.addWidget(self.cancel_button)
        self.setFixedSize(620, 620)

    def _question_text(self) -> str:
        return "Wie viel ist " + self.question.text.removesuffix(" = ?") + " ?"

    def _key(self, label: str) -> QPushButton:
        key = QPushButton(label)
        key.setFixedSize(108, 66)
        key.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if label == "OK":
            style = f"background: {PARENT_ACCENT}; color: #111114;"
        else:
            style = f"background: {KEY_SURFACE}; color: {TEXT.name()};"
        key.setStyleSheet(f"QPushButton {{ {style} border: none; border-radius: 16px; "
                          "font-size: 26px; font-weight: bold; }")
        if label.isdigit():
            key.clicked.connect(lambda _checked=False, d=label: self._type(d))
        return key

    def _type(self, digit: str) -> None:
        if len(self.answer_edit.text()) < self.answer_edit.maxLength():
            self.answer_edit.setText(self.answer_edit.text() + digit)

    def _backspace(self) -> None:
        self.answer_edit.setText(self.answer_edit.text()[:-1])

    def check(self) -> bool:
        """Accept on the right answer; a wrong one closes the dialog, nothing opens."""
        text = self.answer_edit.text().strip()
        if text.isdigit() and int(text) == self.question.answer:
            self.accept()
            return True
        self.reject()
        return False
