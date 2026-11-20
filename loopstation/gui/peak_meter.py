"""The parents' recording level scale (dBFS), shown only when ``peak_meter`` is on."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from loopstation.gui.widgets import ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED, SURFACE

FLOOR_DB = -60.0
TARGET_LOW_DB, TARGET_HIGH_DB = -12.0, -6.0


def peak_to_position(peak: float) -> float:
    """Linear peak to a position 0..1 on the dBFS scale from -60 to 0."""
    if peak <= 0.0:
        return 0.0
    return min(1.0, max(0.0, (20.0 * math.log10(peak) - FLOOR_DB) / -FLOOR_DB))


class PeakMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.position = 0.0
        self.clip = False
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(18)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(160, 18)

    def set_state(self, peak: float, clip: bool) -> None:
        position = round(peak_to_position(peak), 3)
        if (position, clip) != (self.position, self.clip):
            self.position, self.clip = position, clip
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 4, -1, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SURFACE)
        painter.drawRoundedRect(rect, 5, 5)
        low = (TARGET_LOW_DB - FLOOR_DB) / -FLOOR_DB
        high = (TARGET_HIGH_DB - FLOOR_DB) / -FLOOR_DB
        zone = QColor(ACCENT_GREEN)
        zone.setAlpha(70)
        painter.setBrush(zone)
        painter.drawRect(QRectF(rect.left() + rect.width() * low, rect.top(),
                                rect.width() * (high - low), rect.height()))
        color = ACCENT_RED if self.clip else ACCENT_ORANGE if self.position > high else ACCENT_GREEN
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(rect.left(), rect.top(), rect.width() * self.position,
                                       rect.height()), 5, 5)
