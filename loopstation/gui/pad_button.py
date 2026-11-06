"""One pad of the grid, drawn in the style of a Launchpad pad."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import PAD_COLORS

MIN_PAD_SIZE = 130  # widget size; the visible pad is about 115 px
PULSE_HZ = 2.0  # how fast the frame of a waiting pad pulses
SPARKLE_COLOR = QColor("#5AC8FA")  # new-session wave, visible on empty white pads


class PadButton(QAbstractButton):
    """A large rounded square that shows the colour of one pad.

    ``set_look`` only repaints when something visible changed, so the GUI can
    call it on every timer tick. A pad that waits for the next loop start
    (``waiting`` = how far the loop has got, 0..1) is drawn dimmed with a
    pulsing white frame and a bar that fills up until the loop starts again;
    it repaints on every tick so the pulse keeps moving. ``sparkle`` (0..1)
    lights the pad up sky blue for the wave that shows a new session.
    """

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.color = "white"
        self.overlay: str | None = None
        self.remaining: float | None = None  # seconds left while recording
        self.fraction = 0.0  # share of the recording time that is left
        self.waiting: float | None = None  # progress towards the next loop start
        self.sparkle = 0.0  # new-session wave
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"Pad {index + 1}")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(MIN_PAD_SIZE * 3 // 2, MIN_PAD_SIZE * 3 // 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(MIN_PAD_SIZE, MIN_PAD_SIZE)

    def set_look(
        self,
        color: str,
        overlay: str | None,
        remaining: float | None,
        fraction: float,
        waiting: float | None = None,
        sparkle: float = 0.0,
    ) -> None:
        # The countdown only needs whole seconds and a bar with ~200 steps.
        shown_remaining = None if remaining is None else max(1, math.ceil(remaining))
        sparkle = round(sparkle, 2)
        new = (color, overlay, shown_remaining, round(fraction, 3), waiting, sparkle)
        old = (self.color, self.overlay, self.remaining, round(self.fraction, 3), self.waiting,
               self.sparkle)
        if new == old and waiting is None:
            return
        self.color, self.overlay, self.remaining, self.fraction = color, overlay, shown_remaining, fraction
        self.waiting, self.sparkle = waiting, sparkle
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
        if self.waiting is not None:
            base = base.darker(165)  # not yet (or no longer) what the colour says
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
        elif self.waiting is None and self.overlay:
            icon = rect.width() * 0.36
            center = QPointF(rect.center())
            draw_icon(painter, self.overlay,
                      QRectF(center.x() - icon / 2, center.y() - icon / 2, icon, icon),
                      QColor(0, 0, 0, 105))

        if self.waiting is not None:
            self._paint_waiting(painter, rect, radius, side, inset)
        if self.sparkle > 0:
            # New session: the pad lights up sky blue with a soft glow.
            self._paint_sparkle(painter, rect, radius, glow)
        painter.end()

    def _paint_sparkle(self, painter: QPainter, rect: QRectF, radius: float, glow: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        steps = 6
        for i in range(steps, 0, -1):
            halo = QColor(SPARKLE_COLOR)
            halo.setAlpha(int(110 * self.sparkle * (1 - i / (steps + 1))))
            grow = glow * i / steps
            painter.setPen(QPen(halo, glow / steps * 2))
            painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)
        fill = QColor(SPARKLE_COLOR)
        fill.setAlpha(int(215 * self.sparkle))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

    def _paint_waiting(self, painter: QPainter, rect: QRectF, radius: float, side: float,
                       inset: float) -> None:
        """Pulsing frame plus a bar that is full when the next loop starts."""
        pulse = 0.5 + 0.5 * math.cos(2 * math.pi * PULSE_HZ * time.monotonic())
        frame = QColor("#FFFFFF")
        frame.setAlpha(int(110 + 145 * pulse))
        width = max(4.0, side * 0.045)
        painter.setPen(QPen(frame, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = width / 2
        painter.drawRoundedRect(rect.adjusted(half, half, -half, -half), radius, radius)

        bar_h = rect.height() * 0.11
        track = QRectF(rect.left() + inset, rect.bottom() - inset - bar_h,
                       rect.width() - 2 * inset, bar_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(track, bar_h / 2, bar_h / 2)
        filled = QRectF(track.left(), track.top(),
                        max(bar_h, track.width() * min(1.0, max(0.0, self.waiting))), bar_h)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(filled, bar_h / 2, bar_h / 2)
