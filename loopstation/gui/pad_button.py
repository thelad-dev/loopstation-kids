"""One pad of the grid, drawn in the style of a Launchpad pad."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QPushButton, QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import ACCENT_GRAY, PAD_COLORS

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
    lights the pad up sky blue for the wave that shows a new session. ``badge``
    puts a round grey "back" badge in the top right corner (the latest change
    of this pad can be taken back); its button ``badge_button`` has its own click.
    A ``free`` pad (its sound keeps its own length, no beat) is a circle with a
    wave symbol instead of a rounded square, so it is told apart by shape and not
    only by colour. While a pad is held (``hold`` = how far the ring has filled,
    0..1) a ring with the wave symbol fills in the middle and the words "halten ..."
    sit below it.
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
        self.clip = False  # the microphone is too loud right now (recording pad)
        self.level = 0  # coarse input level 0..3 while recording
        self.badge = False  # "back" badge: the latest change of this pad can be undone
        self.free = False  # free mode: a circle with a wave symbol
        self.hold: float | None = None  # how far the ring of a held pad has filled
        # The badge is a child button that exists only while it is shown; a press
        # on it never reaches the pad. ``on_badge`` is called when it is clicked.
        self.badge_button: QPushButton | None = None
        self.on_badge: Callable[[], None] | None = None
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
        clip: bool = False,
        level: int = 0,
        badge: bool = False,
        free: bool = False,
        hold: float | None = None,
    ) -> None:
        # The countdown only needs whole seconds and a bar with ~200 steps.
        shown_remaining = None if remaining is None else max(1, math.ceil(remaining))
        sparkle = round(sparkle, 2)
        hold = None if hold is None else round(hold, 2)
        new = (color, overlay, shown_remaining, round(fraction, 3), waiting, sparkle, clip, level,
               badge, free, hold)
        old = (self.color, self.overlay, self.remaining, round(self.fraction, 3), self.waiting,
               self.sparkle, self.clip, self.level, self.badge, self.free, self.hold)
        if new == old and waiting is None:
            self._sync_badge()
            return
        self.color, self.overlay, self.remaining, self.fraction = color, overlay, shown_remaining, fraction
        self.waiting, self.sparkle, self.clip, self.level = waiting, sparkle, clip, level
        self.badge = badge
        self.free, self.hold = free, hold
        self._sync_badge()
        self.update()

    def _sync_badge(self) -> None:
        if self._badge_visible() and self.badge_button is None:
            self.badge_button = self._make_badge_button()
            self.layout_badge()
            self.badge_button.show()
        elif not self._badge_visible() and self.badge_button is not None:
            self.badge_button.hide()
            self.badge_button.deleteLater()
            self.badge_button = None

    def _badge_clicked(self) -> None:
        if self.on_badge is not None:
            self.on_badge()

    def _make_badge_button(self) -> QPushButton:
        button = QPushButton(self)
        button.clicked.connect(self._badge_clicked)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAccessibleName(f"Pad {self.index + 1} zurück")
        button.setText("\u21b6")
        return button

    def _badge_visible(self) -> bool:
        return self.badge and self.remaining is None and self.waiting is None

    def _pad_rect(self) -> QRectF:
        side = min(self.width(), self.height())
        outer = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        glow = side * 0.05
        return outer.adjusted(glow, glow, -glow, -glow)

    def _badge_circle(self) -> tuple[QPointF, float]:
        """Centre and radius of the badge, in the corner of the visible pad."""
        rect = self._pad_rect()
        center = QPointF(rect.right() - rect.width() * 0.17, rect.top() + rect.height() * 0.17)
        return center, rect.width() * 0.135

    def layout_badge(self) -> None:
        """Place the badge in the corner of the visible pad (call after every resize).

        The badge is a plain child button, so a press on it never reaches the
        pad; its disc and arrow are drawn through a style sheet and an icon.
        """
        if self.badge_button is None:
            return
        center, radius = self._badge_circle()
        reach = round(radius * 1.35)  # the touch target is a little larger than the drawn disc
        self.badge_button.setGeometry(round(center.x()) - reach, round(center.y()) - reach,
                                      2 * reach, 2 * reach)
        disc = round(radius)
        self.badge_button.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_GRAY.name()}; border: 3px solid #FFFFFF;"
            f" border-radius: {disc}px; color: #111114; margin: {reach - disc}px; padding: 0; }}"
            f"QPushButton:pressed {{ background: #7C7C82; }}")
        size = round(radius * 1.35)
        font = self.badge_button.font()
        font.setPixelSize(size)
        font.setBold(True)
        self.badge_button.setFont(font)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        glow = side * 0.05
        outer = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        rect = outer.adjusted(glow, glow, -glow, -glow)
        # A free pad is round (mockup 04), the others are rounded squares.
        radius = rect.width() / 2 if self.free else rect.width() * 0.12
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
        # On a round pad the number sits at the top centre (mockup 04).
        across = Qt.AlignmentFlag.AlignHCenter if self.free else Qt.AlignmentFlag.AlignLeft
        painter.drawText(rect.adjusted(inset, inset * 0.7, -inset, -inset),
                         across | Qt.AlignmentFlag.AlignTop, str(self.index + 1))

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
            self._paint_level(painter, rect, inset)
        elif self.waiting is None and self.hold is not None:
            self._paint_hold(painter, rect, side)
        elif self.waiting is None and (self.overlay or self.free):
            icon = rect.width() * 0.36
            center = QPointF(rect.center())
            draw_icon(painter, self.overlay or "wave",
                      QRectF(center.x() - icon / 2, center.y() - icon / 2, icon, icon),
                      QColor(0, 0, 0, 105))

        if self.waiting is not None:
            self._paint_waiting(painter, rect, radius, side, inset)
        if self.sparkle > 0:
            # New session: the pad lights up sky blue with a soft glow.
            self._paint_sparkle(painter, rect, radius, glow)
        if self.clip:
            self._paint_clip(painter, rect, side)
        painter.end()

    def _paint_hold(self, painter: QPainter, rect: QRectF, side: float) -> None:
        """A ring that fills while the pad is held, the wave inside and "halten ..." below (mockup 04)."""
        assert self.hold is not None
        radius = rect.width() * 0.25
        center = QPointF(rect.center().x(), rect.center().y() - rect.height() * 0.03)
        width = rect.width() * 0.073
        ring = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 48), width))
        painter.drawEllipse(ring)
        ink = QColor("#111114")
        pen = QPen(ink, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self.hold > 0:
            # Clockwise from the top; Qt angles are 1/16 degree, counter-clockwise from 3 o'clock.
            painter.drawArc(ring, 90 * 16, -round(self.hold * 360 * 16))
        icon = rect.width() * 0.22
        draw_icon(painter, "wave", QRectF(center.x() - icon / 2, center.y() - icon / 2, icon, icon), ink)
        pill_w, pill_h = rect.width() * 0.561, rect.height() * 0.1585
        pill = QRectF(rect.center().x() - pill_w / 2, rect.top() + rect.height() * 0.78, pill_w, pill_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 84))
        painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
        font = QFont()
        font.setPixelSize(max(8, round(rect.width() * 0.0854)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, "halten …")

    def _paint_clip(self, painter: QPainter, rect: QRectF, side: float) -> None:
        """"zu laut": white pill with a red rim, a warning triangle and the words (shape, colour, word)."""
        height = rect.height() * 0.20
        width = rect.width() * 0.80
        pill = QRectF(rect.center().x() - width / 2, rect.top() + rect.height() * 0.62, width, height)
        red = QColor("#FF3B30")
        painter.setPen(QPen(red, max(2.5, side * 0.022)))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        # Outlined triangle with an exclamation mark, then the word.
        icon = height * 0.58
        cx, cy = pill.left() + height * 0.62, pill.center().y()
        pen = QPen(red, max(1.5, icon * 0.12))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([QPointF(cx, cy - icon / 2), QPointF(cx + icon / 2, cy + icon * 0.42),
                                       QPointF(cx - icon / 2, cy + icon * 0.42)]))
        painter.drawLine(QPointF(cx, cy - icon * 0.1), QPointF(cx, cy + icon * 0.14))
        painter.drawPoint(QPointF(cx, cy + icon * 0.30))
        font = QFont()
        font.setPointSizeF(max(8.0, side * 0.085))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(red)
        text = QRectF(cx + icon * 0.75, pill.top(), pill.right() - cx - icon * 0.75 - height * 0.2, height)
        painter.drawText(text, Qt.AlignmentFlag.AlignCenter, "zu laut")

    def _paint_level(self, painter: QPainter, rect: QRectF, inset: float) -> None:
        """Three rising bars (coarse input level) in the top right corner of the recording pad."""
        bar_w = rect.width() * 0.065
        gap = bar_w * 0.55
        base = rect.top() + inset * 0.7 + rect.height() * 0.17
        left = rect.right() - inset - 3 * bar_w - 2 * gap
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            tall = rect.height() * (0.07 + 0.045 * i)
            on = self.level > i
            painter.setBrush(QColor(255, 255, 255, 255 if on else 90))
            painter.drawRoundedRect(QRectF(left + i * (bar_w + gap), base - tall, bar_w, tall),
                                    bar_w / 3, bar_w / 3)

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
