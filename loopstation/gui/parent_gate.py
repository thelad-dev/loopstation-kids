"""Parental gate: the way into the parents' area.

Two steps a six-year-old does not hit by accident: the small gear in the
corner of the window must be held for a moment, and then a sum of two
two-digit numbers has to be answered. It keeps children out; it is not a
consent mechanism of any kind.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIntValidator, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import ACCENT_GRAY, BACKGROUND, TEXT, TEXT_DIM, BigButton, big_font

HOLD_MS = 1500  # how long the gear has to be held
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
    """Small gear that fires ``held`` only after being pressed for ``HOLD_MS`` without letting go."""

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
        color = QColor(TEXT if self.isDown() else TEXT_DIM)
        color.setAlpha(200 if self.isDown() else 90)
        draw_icon(painter, "settings", QRectF(self.rect()), color)
        painter.end()


class ParentGate(QDialog):
    """Asks one sum; ``exec()`` is Accepted only for the right answer."""

    def __init__(self, parent: QWidget | None = None, question: GateQuestion | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Für Erwachsene")
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {BACKGROUND.name()}; }}")
        self.question = question or new_question()

        intro = QLabel("Nur für Erwachsene. Bitte rechnen:")
        intro.setFont(big_font(18, bold=False))
        intro.setStyleSheet(f"color: {TEXT_DIM.name()};")
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.question_label = QLabel(self.question.text)
        self.question_label.setFont(big_font(34))
        self.question_label.setStyleSheet(f"color: {TEXT.name()};")
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.answer_edit = QLineEdit()
        self.answer_edit.setValidator(QIntValidator(0, 999, self))
        self.answer_edit.setMaxLength(3)
        self.answer_edit.setFont(big_font(28))
        self.answer_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.answer_edit.setStyleSheet(
            f"QLineEdit {{ color: {TEXT.name()}; background: #26262B; border-radius: 12px; padding: 8px; }}")
        self.answer_edit.returnPressed.connect(self.check)

        self.feedback = QLabel("")
        self.feedback.setFont(big_font(16, bold=False))
        self.feedback.setStyleSheet("color: #FF9F0A;")
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.cancel_button = BigButton("close", "Abbrechen", ACCENT_GRAY)
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = BigButton("check", "OK", ACCENT_GRAY)
        self.ok_button.clicked.connect(self.check)

        buttons = QHBoxLayout()
        buttons.setSpacing(24)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(14)
        layout.addWidget(intro)
        layout.addWidget(self.question_label)
        layout.addWidget(self.answer_edit)
        layout.addWidget(self.feedback)
        layout.addLayout(buttons)

    def check(self) -> bool:
        """Accept on the right answer; otherwise ask a new question and stay closed."""
        text = self.answer_edit.text().strip()
        if text.isdigit() and int(text) == self.question.answer:
            self.accept()
            return True
        self.question = new_question()
        self.question_label.setText(self.question.text)
        self.answer_edit.clear()
        self.feedback.setText("Das stimmt nicht. Neue Aufgabe:")
        return False
