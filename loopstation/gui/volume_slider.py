"""The large volume control in the top right corner (mockup 01/02).

One widget for the whole window: it shows and sets the controller's master
volume and nothing else. The track always spans the full range, the part
above the parents' ceiling is hatched and cannot be reached, so when the
ceiling drops the handle visibly slides down with it.

The position on the track is the square root of the linear gain, which feels
evenly spaced to the ear; ``position_to_volume`` and ``volume_to_position``
are the two directions of that curve.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from loopstation.gui.widgets import SURFACE, TEXT, TEXT_DIM

WHEEL_STEP = 0.05  # position per wheel notch
FILL = QColor("#5AC8FA")  # filled part and handle rim (as in the mockups)
TRACK = QColor("#3A3A41")


def position_to_volume(position: float) -> float:
    """Track position 0..1 to linear gain."""
    return min(1.0, max(0.0, position)) ** 2


def volume_to_position(volume: float) -> float:
    """Linear gain to track position 0..1."""
    return math.sqrt(min(1.0, max(0.0, volume)))


class VolumeSlider(QWidget):
    """Big horizontal slider with a speaker icon; ``volumeChanged(gain)`` while it is dragged."""

    volumeChanged = Signal(float)  # noqa: N815 - Qt API

    HEIGHT = 104

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume = 0.0
        self._limit = 1.0
        self._dragging = False
        self.setAccessibleName("Lautstärke")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(240, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # ----------------------------------------------------------- the value

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def limit(self) -> float:
        return self._limit

    def set_state(self, volume: float, limit: float) -> None:
        """Show ``volume`` with the reachable range ending at ``limit`` (both linear gains)."""
        limit = min(1.0, max(0.0, limit))
        volume = min(limit, max(0.0, volume))
        if volume != self._volume or limit != self._limit:
            self._volume, self._limit = volume, limit
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(384, self.HEIGHT)

    # ------------------------------------------------------------ geometry

    def _track(self) -> QRectF:
        """The bar the handle runs on (between the two speaker icons)."""
        h = self.height()
        left = h * 0.63
        middle = h * 0.5
        return QRectF(left, middle - h * 0.105, max(1.0, self.width() - 2 * left), h * 0.21)

    def _x_of(self, position: float) -> float:
        track = self._track()
        return track.left() + track.width() * position

    def _position_at(self, x: float) -> float:
        track = self._track()
        return min(1.0, max(0.0, (x - track.left()) / track.width()))

    # --------------------------------------------------------------- mouse

    def _set_from_x(self, x: float) -> None:
        volume = min(self._limit, position_to_volume(self._position_at(x)))
        if volume != self._volume:
            self._volume = volume
            self.update()
            self.volumeChanged.emit(volume)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if self._dragging:
            self._set_from_x(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        notches = event.angleDelta().y() / 120
        if notches:
            position = volume_to_position(self._volume) + WHEEL_STEP * notches
            self._set_from_x(self._x_of(position))
        event.accept()

    # --------------------------------------------------------------- paint

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = self.height()
        track = self._track()
        radius = track.height() / 2
        handle_x = self._x_of(volume_to_position(self._volume))
        reach_x = self._x_of(volume_to_position(self._limit))

        # Panel, then the whole track.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SURFACE)
        painter.drawRoundedRect(QRectF(self.rect()), h * 0.19, h * 0.19)
        painter.setBrush(TRACK)
        painter.drawRoundedRect(track, radius, radius)
        # Filled part up to the handle.
        painter.save()
        painter.setClipRect(QRectF(track.left(), track.top(), handle_x - track.left(), track.height()))
        painter.setBrush(FILL)
        painter.drawRoundedRect(track, radius, radius)
        painter.restore()
        # Above the parents' ceiling: hatched, not reachable, with a lock on the line.
        if self._limit < 1.0:
            blocked = QRectF(reach_x, track.top(), track.right() - reach_x, track.height())
            painter.save()
            painter.setClipRect(blocked)
            painter.setBrush(QColor("#2E2E34"))
            painter.drawRoundedRect(track, radius, radius)
            painter.setPen(QPen(QColor("#4A4A52"), 4))
            x = blocked.left() - track.height()
            while x < blocked.right():
                painter.drawLine(QPointF(x, track.bottom()), QPointF(x + track.height(), track.top()))
                x += 10
            painter.restore()
        line = QPen(QColor("#AEAEB2"), 3)
        line.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(line)
        middle = track.center().y()
        painter.drawLine(QPointF(reach_x, middle - h * 0.19), QPointF(reach_x, middle + h * 0.19))
        self._paint_lock(painter, QPointF(reach_x, middle - h * 0.30), h * 0.15)

        # Handle: white disc with a sky-blue rim.
        r = h * 0.26
        painter.setPen(QPen(FILL, max(3.0, h * 0.048)))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(handle_x, track.center().y()), r, r)

        self._paint_speaker(painter, QRectF(h * 0.18, h * 0.36, h * 0.27, h * 0.28), 1)
        self._paint_speaker(painter, QRectF(self.width() - h * 0.47, h * 0.34, h * 0.30, h * 0.32), 3)
        painter.end()

    @staticmethod
    def _paint_lock(painter: QPainter, center: QPointF, size: float) -> None:
        """Small padlock (the ceiling that the parents set)."""
        pen = QPen(QColor("#AEAEB2"), max(1.5, size * 0.14))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(center.x() - size * 0.5, center.y() - size * 0.05, size, size * 0.62)
        painter.drawRoundedRect(body, size * 0.12, size * 0.12)
        painter.drawArc(QRectF(center.x() - size * 0.3, center.y() - size * 0.55, size * 0.6, size * 0.9),
                        0, 180 * 16)

    def _paint_speaker(self, painter: QPainter, rect: QRectF, waves: int) -> None:
        color = QColor(TEXT) if self.isEnabled() else QColor(TEXT_DIM)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        painter.drawPolygon(QPolygonF([
            QPointF(x, y + h * 0.35), QPointF(x + w * 0.28, y + h * 0.35),
            QPointF(x + w * 0.55, y + h * 0.08), QPointF(x + w * 0.55, y + h * 0.92),
            QPointF(x + w * 0.28, y + h * 0.65), QPointF(x, y + h * 0.65),
        ]))
        pen = QPen(color, max(2.0, h * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(waves):
            r = h * (0.22 + 0.22 * i)
            painter.drawArc(QRectF(x + w * 0.55 - r * 0.6, y + h * 0.5 - r, r * 1.2, r * 2),
                            -45 * 16, 90 * 16)
