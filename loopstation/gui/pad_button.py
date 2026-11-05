"""One pad of the grid, drawn in the style of a Launchpad pad."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import PAD_COLORS

MIN_PAD_SIZE = 130  # widget size; the visible pad is about 115 px


class PadButton(QAbstractButton):
    """A large rounded square that shows the colour of one pad.

    ``set_look`` only repaints when something visible changed, so the GUI can
    call it on every timer tick.
    """

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.color = "white"
        self.overlay: str | None = None
        self.remaining: float | None = None  # seconds left while recording
        self.fraction = 0.0  # share of the recording time that is left
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"Pad {index + 1}")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(MIN_PAD_SIZE * 3 // 2, MIN_PAD_SIZE * 3 // 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(MIN_PAD_SIZE, MIN_PAD_SIZE)

    def set_look(self, color: str, overlay: str | None, remaining: float | None, fraction: float) -> None:
        # The countdown only needs whole seconds and a bar with ~200 steps.
        shown_remaining = None if remaining is None else max(1, math.ceil(remaining))
        new = (color, overlay, shown_remaining, round(fraction, 3))
        if new == (self.color, self.overlay, self.remaining, round(self.fraction, 3)):
            return
        self.color, self.overlay, self.remaining, self.fraction = color, overlay, shown_remaining, fraction
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        glow = side * 0.05
        outer = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        rect = outer.adjusted(glow, glow, -glow, -glow)
        radius = rect.width() * 0.12
        base = QColor(PAD_COLORS[self.color])
        lit = self.color in ("green", "red")

        # Soft glow around lit pads (playing or recording).
        if lit:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            steps = 6
            for i in range(steps, 0, -1):
                halo = QColor(base)
                halo.setAlpha(int(70 * (1 - i / (steps + 1))))
                grow = glow * i / steps
                painter.setPen(QPen(halo, glow / steps * 2))
                painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow),
                                        radius + grow, radius + grow)

        # Pad body with a gentle top-to-bottom gradient for depth.
        fill = base.darker(112) if self.isDown() else base
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, fill.lighter(108))
        gradient.setColorAt(1.0, fill.darker(108))
        painter.setPen(QPen(fill.lighter(125) if lit else fill.darker(130), max(2.0, side * 0.012)))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, radius, radius)

        ink = QColor(0, 0, 0, 120)

        # Pad number, small, top left.
        number_font = QFont()
        number_font.setPointSizeF(max(11.0, side * 0.075))
        number_font.setBold(True)
        painter.setFont(number_font)
        painter.setPen(ink)
        inset = rect.width() * 0.08
        painter.drawText(rect.adjusted(inset, inset * 0.7, -inset, -inset),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, str(self.index + 1))

        if self.remaining is not None:
            # Recording: big seconds countdown and a shrinking bar.
            count_font = QFont()
            count_font.setPointSizeF(side * 0.26)
            count_font.setBold(True)
            painter.setFont(count_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(0, -rect.height() * 0.06, 0, -rect.height() * 0.06),
                             Qt.AlignmentFlag.AlignCenter, str(self.remaining))
            bar_h = rect.height() * 0.08
            track = QRectF(rect.left() + inset, rect.bottom() - inset - bar_h,
                           rect.width() - 2 * inset, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 70))
            painter.drawRoundedRect(track, bar_h / 2, bar_h / 2)
            done = QRectF(track.left(), track.top(), max(bar_h, track.width() * self.fraction), bar_h)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(done, bar_h / 2, bar_h / 2)
        elif self.overlay:
            icon = rect.width() * 0.36
            center = QPointF(rect.center())
            draw_icon(painter, self.overlay,
                      QRectF(center.x() - icon / 2, center.y() - icon / 2, icon, icon),
                      QColor(0, 0, 0, 105))
        painter.end()
