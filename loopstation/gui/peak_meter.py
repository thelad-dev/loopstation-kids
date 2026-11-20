"""The parents' recording level scale (dBFS, mockup 09).

A bar from -48 to 0 dBFS with the target zone (-12 to -6) behind it, a white
tick that holds the highest peak, and a scale below. It sits in the parents'
area only; the child sees three bars on the recording pad instead.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from loopstation.gui.widgets import ACCENT_GREEN, ACCENT_RED, ACCENT_YELLOW, TEXT_DIM

FLOOR_DB = -48.0
TARGET_LOW_DB, TARGET_HIGH_DB = -12.0, -6.0
TICKS_DB = (-48, -36, -24, -18, -12, -6, -3, 0)
# From here up the bar is red, whether the engine counted a clip or not.
RED_DB = -1.0

LABEL_HEIGHT = 18  # "Ziel -12 ... -6 dBFS" above the bar
BAR_HEIGHT = 28
SCALE_HEIGHT = 26  # tick marks and numbers below the bar
MARGIN = 12  # at both ends, so the "-48" and the "0" are not cut off


def db_to_position(db: float) -> float:
    """dBFS to a position 0..1 on the scale (linear in dB from -48 to 0)."""
    return min(1.0, max(0.0, (db - FLOOR_DB) / -FLOOR_DB))


def peak_to_position(peak: float) -> float:
    """Linear peak to a position 0..1 on the scale."""
    if peak <= 0.0:
        return 0.0
    return db_to_position(20.0 * math.log10(peak))


class PeakMeter(QWidget):
    """Level bar with a peak-hold tick; ``set_state(level, hold, clip)`` takes linear peaks."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.position = 0.0
        self.hold = 0.0
        self.clip = False
        self.setAccessibleName("Aufnahmepegel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(LABEL_HEIGHT + BAR_HEIGHT + SCALE_HEIGHT)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(416, LABEL_HEIGHT + BAR_HEIGHT + SCALE_HEIGHT)

    def set_state(self, level: float, hold: float, clip: bool = False) -> None:
        position = round(peak_to_position(level), 3)
        hold_position = round(peak_to_position(hold), 3)
        if (position, hold_position, clip) != (self.position, self.hold, self.clip):
            self.position, self.hold, self.clip = position, hold_position, clip
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)  # the switch is off
        width = float(self.width() - 2 * MARGIN - 1)  # room for the outer scale numbers
        left = MARGIN + 0.5
        top = float(LABEL_HEIGHT)

        def x_of(position: float) -> float:
            return left + width * position

        low, high = db_to_position(TARGET_LOW_DB), db_to_position(TARGET_HIGH_DB)
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(ACCENT_GREEN))
        painter.drawText(QRectF(x_of(low) - 40, 0, x_of(high) - x_of(low) + 80, LABEL_HEIGHT - 4),
                         Qt.AlignmentFlag.AlignCenter, "Ziel −12 … −6 dBFS")

        # Frame, target zone, bar, hold tick.
        frame = QRectF(left, top, width, BAR_HEIGHT)
        painter.setPen(QPen(QColor("#3A3A41"), 1))
        painter.setBrush(QColor("#1A1A1E"))
        painter.drawRoundedRect(frame, 6, 6)
        zone = QColor(ACCENT_GREEN)
        zone.setAlpha(36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(zone)
        painter.drawRect(QRectF(x_of(low), top, x_of(high) - x_of(low), BAR_HEIGHT))
        bar_top, bar_height = top + 3, BAR_HEIGHT - 6
        bar_left = left + 2
        red_at = db_to_position(RED_DB)
        segments = ((0.0, low, ACCENT_GREEN), (low, red_at, ACCENT_YELLOW), (red_at, 1.0, ACCENT_RED))
        for start, stop, color in segments:
            if self.clip and start >= low:
                color = ACCENT_RED
            end = min(self.position, stop)
            if end <= start:
                continue
            painter.setBrush(color)
            x0 = bar_left if start == 0.0 else x_of(start)
            painter.drawRect(QRectF(x0, bar_top, x_of(end) - x0, bar_height))
        if self.hold > 0.0:
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(QRectF(x_of(self.hold) - 1.5, top + 1, 3, BAR_HEIGHT - 2))

        # Scale.
        painter.setPen(QPen(QColor("#6E6E75"), 1.5))
        small = QFont()
        small.setPixelSize(11)
        painter.setFont(small)
        baseline = top + BAR_HEIGHT
        for db in TICKS_DB:
            x = x_of(db_to_position(db))
            painter.setPen(QPen(QColor("#6E6E75"), 1.5))
            painter.drawLine(QPointF(x, baseline), QPointF(x, baseline + 6))
            painter.setPen(TEXT_DIM)
            painter.drawText(QRectF(x - 20, baseline + 8, 40, 16), Qt.AlignmentFlag.AlignCenter, str(db))
        painter.end()
