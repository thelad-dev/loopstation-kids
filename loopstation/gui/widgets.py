"""Shared colours and the large icon-plus-word button used everywhere."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from loopstation.gui.icons import draw_icon

# Pad colours (Launchpad look).
PAD_COLORS = {
    "white": QColor("#F2F2F2"),
    "yellow": QColor("#FFD60A"),
    "green": QColor("#32D74B"),
    "red": QColor("#FF3B30"),
}

BACKGROUND = QColor("#0E0E10")
SURFACE = QColor("#26262B")
SURFACE_PRESSED = QColor("#3A3A41")
TEXT = QColor("#F2F2F2")
TEXT_DIM = QColor("#8E8E93")
DARK_TEXT = QColor("#111114")

# One accent colour per mode, used for the mode buttons and the window frame.
ACCENT_GREEN = QColor("#32D74B")
ACCENT_RED = QColor("#FF3B30")
ACCENT_BLUE = QColor("#40A9FF")
ACCENT_ORANGE = QColor("#FF9F0A")
ACCENT_PURPLE = QColor("#C77DFF")
ACCENT_YELLOW = QColor("#FFD60A")
ACCENT_GRAY = QColor("#AEAEB2")

BUTTON_FONT_PT = 22


def big_font(point_size: int = BUTTON_FONT_PT, bold: bool = True) -> QFont:
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(bold)
    return font


class BigButton(QAbstractButton):
    """A large rounded button with a vector icon and one word.

    Unchecked: dark surface, icon in the accent colour. Checked: filled with
    the accent colour so the active mode is obvious from across the room.
    ``stacked`` puts the icon above the word (used for the mode bar, so all
    five modes fit side by side even on small screens).
    """

    def __init__(
        self,
        icon: str,
        text: str,
        accent: QColor,
        checkable: bool = False,
        parent: QWidget | None = None,
        min_height: int = 76,
        font_pt: int = BUTTON_FONT_PT,
        stacked: bool = False,
    ) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.stacked = stacked
        self.accent = QColor(accent)
        self.setText(text)
        self.setCheckable(checkable)
        self.setFont(big_font(font_pt))
        self.setMinimumHeight(min_height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # Layout constants (pixels).
    PAD_X = 26
    PAD_Y = 12
    GAP = 14
    STACK_GAP = 4

    def _icon_size(self, metrics: QFontMetrics) -> float:
        return metrics.height() * (1.35 if self.stacked else 1.25)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = QFontMetrics(self.font())
        icon = self._icon_size(metrics)
        text = metrics.horizontalAdvance(self.text())
        if self.stacked:
            width = 2 * self.PAD_X + max(icon, text)
            height = 2 * self.PAD_Y + icon + self.STACK_GAP + metrics.height()
        else:
            width = 2 * self.PAD_X + icon + self.GAP + text
            height = metrics.height() * 2.3
        return QSize(int(width), max(self.minimumHeight(), int(height)))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = min(18.0, rect.height() / 3)
        enabled = self.isEnabled()
        filled = self.isChecked()

        if filled:
            fill = QColor(self.accent)
            if self.isDown():
                fill = fill.darker(115)
            fg = DARK_TEXT
            icon_color = DARK_TEXT
        else:
            fill = SURFACE_PRESSED if self.isDown() else SURFACE
            fg = TEXT
            icon_color = QColor(self.accent)
        if not enabled:
            fg = QColor(TEXT_DIM)
            fg.setAlpha(120)
            icon_color = QColor(fg)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        if filled:
            # thin bright rim, like a lit Launchpad button
            painter.setPen(QColor(255, 255, 255, 110))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        metrics = QFontMetrics(self.font())
        icon_size = self._icon_size(metrics)
        text_width = metrics.horizontalAdvance(self.text())
        painter.setFont(self.font())
        if self.stacked:
            content = icon_size + self.STACK_GAP + metrics.height()
            top = rect.center().y() - content / 2
            icon_rect = QRectF(rect.center().x() - icon_size / 2, top, icon_size, icon_size)
            text_rect = QRectF(rect.left(), top + icon_size + self.STACK_GAP,
                               rect.width(), metrics.height())
            align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        else:
            content = icon_size + self.GAP + text_width
            left = rect.center().x() - content / 2
            icon_rect = QRectF(left, rect.center().y() - icon_size / 2, icon_size, icon_size)
            text_rect = QRectF(left + icon_size + self.GAP, rect.top(), text_width + 2, rect.height())
            align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        draw_icon(painter, self.icon_name, icon_rect, icon_color)
        painter.setPen(fg)
        painter.drawText(text_rect, align, self.text())
        painter.end()
