"""The way into the parents' area on the child page: a small, dim tile with a lock and the word "Eltern".

Behaviour is the one of ``ParentEntryButton``: it opens only after being held
for two seconds (``held``); a tap does nothing.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import ParentEntryButton

TILE_WIDTH = 88
TILE_HEIGHT = 92  # as the action buttons next to it
WORD = "Eltern"
SURFACE_DARK = QColor("#1B1B1F")
BORDER = QColor("#2C2C31")
DIM = QColor("#6E6E75")
HELD = QColor("#9A9AA2")


class ParentTile(ParentEntryButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(TILE_WIDTH, TILE_HEIGHT))
        self.setText(WORD)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = HELD if self.isDown() else DIM
        painter.setBrush(SURFACE_DARK)
        painter.setPen(HELD if self.isDown() else BORDER)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 18, 18)
        draw_icon(painter, "lock", QRectF((TILE_WIDTH - 32) / 2, 16, 32, 32), color)
        font = QFont()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(0, 58, TILE_WIDTH, 20), Qt.AlignmentFlag.AlignCenter, WORD)
        painter.end()
