"""The side panel of the parents' view (Loopstation 2, mockup L2-05).

A tool of the parents' view (Verlauf, Sets, Export, Pegel, Geräte, System, Takt from the bar chip, Loop
from the detail line) opens here, to the right of the pads, in the same window. The pads stay in sight
and can be played. The panel has a head (icon, title, a line under it, the close button) and the page
of the tool below it. A page is built on its first visit and kept while the parents' view is shown.

The line under the title says what the page does ("wirkt sofort · automatisch gesichert" on the
settings pages); ``say`` puts a message in its place (green: done, orange: needs a restart, red: refused).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import CARD_FILL, PAGE_STYLE, RADIO_QSS, IconLabel
from loopstation.gui.widgets import ACCENT_GREEN, SURFACE, TEXT, TEXT_DIM

SAVED_LINE = "wirkt sofort · automatisch gesichert"
COLORS = {"ok": ACCENT_GREEN.name(), "warning": "#FF9F0A", "error": "#FF3B30", "": TEXT_DIM.name()}

# Form controls inside the panel (the pages that set their own style keep theirs).
FORM_QSS = (
    f"QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
    f"font-size: 16px; border: 1px solid {PARENT_ACCENT}; border-radius: 10px; padding: 6px 10px; }} "
    "QComboBox { border: 1.5px solid #3A3A41; border-radius: 12px; padding: 8px 14px; font-weight: 600; } "
    "QComboBox::drop-down { border: none; width: 28px; } "
    f"QComboBox QAbstractItemView {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
    f"selection-background-color: {PARENT_ACCENT}; selection-color: #000000; font-size: 16px; }} "
    "QSpinBox:disabled, QDoubleSpinBox:disabled { color: #5A5A60; border-color: #3A3A41; } "
    # Arrows hidden by the style, not by ``NoButtons``: with a style sheet that leaves no room for the text.
    "#stepped::up-button, #stepped::down-button { width: 0px; border: none; } "
    "#stepped::up-arrow, #stepped::down-arrow { width: 0px; height: 0px; } "
    "QPushButton#step { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
    "border-radius: 10px; font-size: 22px; font-weight: 700; min-width: 44px; max-width: 44px; "
    "min-height: 38px; } "
    "QPushButton#step:pressed { background: #3A3A41; } "
    "QPushButton#secondary { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
    "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 44px; padding: 0 22px; } "
    "QPushButton#secondary:pressed { background: #3A3A41; } "
)
# The cards of a page are sections of the panel: no box of their own (mockup L2-05).
FLAT_CARDS_QSS = "#card { background: transparent; border: none; } "


def flatten_cards(widget: QWidget) -> None:
    """Let the cards in ``widget`` sit flush with the panel: no box, no side margins (the panel has them)."""
    widget.setStyleSheet(widget.styleSheet() + FLAT_CARDS_QSS)  # after the page's own rules: they win
    for frame in widget.findChildren(QFrame, "card"):
        layout = frame.layout()
        if isinstance(layout, QLayout):
            margins = layout.contentsMargins()
            layout.setContentsMargins(0, min(margins.top(), 6), 0, min(margins.bottom(), 10))


class CloseButton(QAbstractButton):
    """The cross at the top right of the panel."""

    SIDE = 46

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setAccessibleName("Schließen")
        self.setToolTip("Schließen (Esc)")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.SIDE, self.SIDE)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setPen(QPen(QColor("#3A3A41"), 1.5))
        painter.setBrush(QColor("#2A2A30") if self.isDown() else QColor("#1F1F24"))
        painter.drawRoundedRect(rect, 12, 12)
        pen = QPen(TEXT, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        middle = rect.center()
        reach = 8.0
        painter.drawLine(middle.x() - reach, middle.y() - reach, middle.x() + reach, middle.y() + reach)
        painter.drawLine(middle.x() - reach, middle.y() + reach, middle.x() + reach, middle.y() - reach)
        painter.end()


class SidePanelHost(QWidget):
    """Head and page of the open tool. ``close_requested`` when the cross is tapped."""

    close_requested = Signal()

    MARGIN = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key: str | None = None
        self.pages: dict[str, QWidget] = {}
        self._lines: dict[str, str] = {}
        self.setObjectName("side_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet(PAGE_STYLE + RADIO_QSS + FORM_QSS)

        self.icon = IconLabel("sliders", PARENT_ACCENT, 28)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 24px; font-weight: 800;")
        self.line = QLabel("")
        self.line.setWordWrap(True)
        self.close_button = CloseButton()
        self.close_button.clicked.connect(self.close_requested)
        self.stack = QStackedWidget()
        self.stack.setObjectName("side_stack")
        self.stack.setStyleSheet("#side_stack { background: transparent; }")

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.line)
        icon_column = QVBoxLayout()
        icon_column.setContentsMargins(0, 4, 0, 0)
        icon_column.addWidget(self.icon)
        icon_column.addStretch(1)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        head.addLayout(icon_column)
        head.addLayout(titles, 1)
        head.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.MARGIN, 14, 12, 16)
        layout.setSpacing(14)
        head_margin = QHBoxLayout()
        head_margin.setContentsMargins(0, 0, 4, 0)
        head_margin.addLayout(head)
        layout.addLayout(head_margin)
        layout.addWidget(self.stack, 1)

    # ------------------------------------------------------------ pages

    def page(self, key: str) -> QWidget | None:
        return self.pages.get(key)

    def current_page(self) -> QWidget | None:
        return None if self.key is None else self.pages.get(self.key)

    def show_page(self, key: str, icon: str, title: str, line: str, widget: QWidget) -> None:
        """Show ``widget`` (kept under ``key``) with its head; the message of an earlier visit is gone."""
        if self.pages.get(key) is not widget:
            old = self.pages.get(key)
            if old is not None:
                self.stack.removeWidget(old)
                old.deleteLater()
            self.pages[key] = widget
            self.stack.addWidget(widget)
        self.key = key
        self._lines[key] = line
        self.icon.set_icon(icon)
        self.title.setText(title)
        self.stack.setCurrentWidget(widget)
        self.say("")

    def say(self, text: str, level: str = "ok") -> None:
        """``text`` in place of the line under the title; "" brings the line back."""
        if text:
            self.line.setProperty("message", True)
            self.line.setText(text)
            color = COLORS.get(level, COLORS[""])
        else:
            self.line.setProperty("message", False)
            line = self._lines.get(self.key or "", "")
            self.line.setText(line)
            color = COLORS["ok"] if line == SAVED_LINE else COLORS[""]
        self.line.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")

    def message(self) -> str:
        """The message shown now ("" while the line under the title is the normal one)."""
        return self.line.text() if self.line.property("message") else ""

    # ------------------------------------------------------------ paint

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(PARENT_ACCENT), 2))
        painter.setBrush(QColor(CARD_FILL))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
        painter.end()

