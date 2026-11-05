"""Per-pad history: listen to earlier versions and put one back."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_GREEN,
    ACCENT_YELLOW,
    BACKGROUND,
    DARK_TEXT,
    SURFACE,
    TEXT,
    BigButton,
    big_font,
)

ROW_HEIGHT = 108  # 76 px buttons + 2 x 12 px padding + 2 x 4 px border
ROW_SPACING = 14


def _time_label(moment: datetime | None) -> str:
    if moment is None:
        return ""
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M")
    return moment.strftime("%d.%m. %H:%M")


class HistoryDialog(QDialog):
    """Modal list of all versions of one pad, newest first."""

    def __init__(self, controller: Controller, pad: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.pad = pad
        self.setWindowTitle(f"Verlauf - Pad {pad + 1}")
        self.setModal(True)
        self.setMinimumWidth(960)
        self.setStyleSheet(
            f"QDialog {{ background: {BACKGROUND.name()}; }}"
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }"
            # A wide, simple scroll bar that small fingers can hit.
            "QScrollBar:vertical { background: #1C1C20; width: 26px; margin: 0; border-radius: 13px; }"
            "QScrollBar::handle:vertical { background: #5A5A62; min-height: 60px; border-radius: 13px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )

        title = QLabel(f"Pad {pad + 1}")
        title.setFont(big_font(30))
        title.setStyleSheet(f"color: {TEXT.name()};")

        current = controller.pad(pad).sample
        entries = controller.history(pad)
        rows = QVBoxLayout()
        # Keep the rows clear of the scroll bar when there is one.
        rows.setContentsMargins(0, 0, 14 if len(entries) > 3 else 0, 0)
        rows.setSpacing(ROW_SPACING)
        self.take_buttons: dict[str, BigButton] = {}
        self.listen_buttons: dict[str, BigButton] = {}
        for number, entry in reversed(list(enumerate(entries, start=1))):
            rows.addWidget(self._row(number, entry.sample, _time_label(entry.recorded_at),
                                     entry.sample == current))
        rows.addStretch(1)

        container = QWidget()
        container.setLayout(rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Show up to three versions without scrolling.
        visible = min(len(entries), 3)
        scroll.setMinimumHeight(visible * ROW_HEIGHT + (visible - 1) * ROW_SPACING)

        self.close_button = BigButton("close", "Schließen", ACCENT_GRAY)
        self.close_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.close_button)

    def _row(self, number: int, sample: str, when: str, is_current: bool) -> QFrame:
        frame = QFrame()
        border = ACCENT_YELLOW.name() if is_current else SURFACE.name()
        frame.setStyleSheet(
            f"QFrame#versionRow {{ background: {SURFACE.name()}; border: 4px solid {border};"
            f" border-radius: 18px; }}"
        )
        frame.setObjectName("versionRow")
        frame.setFixedHeight(ROW_HEIGHT)
        text = f"Version {number}" + (f" - {when}" if when else "")
        label = QLabel(text)
        label.setFont(big_font(22))
        label.setStyleSheet(f"color: {TEXT.name()}; background: transparent; border: none;")
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        listen = BigButton("play", "Anhören", ACCENT_GREEN)
        listen.clicked.connect(lambda: self.controller.preview(sample))
        take = BigButton("check", "Nehmen", ACCENT_YELLOW)
        take.clicked.connect(lambda: self._take(sample))
        for button in (listen, take):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.listen_buttons[sample] = listen
        self.take_buttons[sample] = take

        row = QHBoxLayout(frame)
        row.setContentsMargins(26, 12, 12, 12)
        row.setSpacing(12)
        row.addWidget(label, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(listen)
        if is_current:
            # The version on the pad right now: a yellow "jetzt" mark in the
            # place of the "Nehmen" button (there is nothing to take).
            badge = QLabel("jetzt")
            badge.setFont(big_font(22))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(take.sizeHint())
            badge.setStyleSheet(
                f"color: {DARK_TEXT.name()}; background: {ACCENT_YELLOW.name()};"
                " border: none; border-radius: 18px;"
            )
            take.hide()
            row.addWidget(badge)
        else:
            row.addWidget(take)
        return frame

    def _take(self, sample: str) -> None:
        self.controller.restore(self.pad, sample)
        self.accept()

    def done(self, result: int) -> None:
        """Stop a running preview whenever the dialog closes."""
        self.controller.stop_preview()
        super().done(result)
