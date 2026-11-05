"""Large yes/no confirmation for "Alle löschen"."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_RED,
    BACKGROUND,
    TEXT,
    TEXT_DIM,
    BigButton,
    big_font,
)


class ConfirmDialog(QDialog):
    """Modal dialog with one question and two big buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Alle löschen?")
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {BACKGROUND.name()}; }}")

        question = QLabel("Alle Pads löschen?")
        question.setFont(big_font(30))
        question.setStyleSheet(f"color: {TEXT.name()};")
        question.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Mit „Zurück“ kommt alles wieder.")
        hint.setFont(big_font(18, bold=False))
        hint.setStyleSheet(f"color: {TEXT_DIM.name()};")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.yes_button = BigButton("trash", "Ja, löschen", ACCENT_RED, checkable=True)
        self.yes_button.setChecked(True)  # filled red: this is the dangerous one
        self.yes_button.clicked.connect(self._yes)
        self.no_button = BigButton("close", "Nein", ACCENT_GRAY)
        self.no_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.setSpacing(24)
        buttons.addWidget(self.no_button)
        buttons.addWidget(self.yes_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(18)
        layout.addWidget(question)
        layout.addWidget(hint)
        layout.addSpacing(16)
        layout.addLayout(buttons)

    def _yes(self) -> None:
        self.yes_button.setChecked(True)  # keep it filled after the click toggled it
        self.accept()
