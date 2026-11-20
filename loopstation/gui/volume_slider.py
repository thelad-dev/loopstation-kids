"""The large volume control in the top right corner.

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

from loopstation.gui.widgets import ACCENT_GREEN, SURFACE, SURFACE_PRESSED, TEXT, TEXT_DIM

WHEEL_STEP = 0.05  # position per wheel notch


def position_to_volume(position: float) -> float:
    """Track position 0..1 to linear gain."""
    return min(1.0, max(0.0, position)) ** 2


def volume_to_position(volume: float) -> float:
    """Linear gain to track position 0..1."""
    return math.sqrt(min(1.0, max(0.0, volume)))


class VolumeSlider(QWidget):
    """Big horizontal slider with a speaker icon; ``volumeChanged(gain)`` while it is dragged."""

    volumeChanged = Signal(float)  # noqa: N815 - Qt API

    HEIGHT = 56

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume = 0.0
        self._limit = 1.0
        self._dragging = False
        self.setAccessibleName("Lautstärke")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(300, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

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
        return QSize(360, self.HEIGHT)

    # ------------------------------------------------------------ geometry

    def _track(self) -> QRectF:
        """The bar the handle runs on (without the speaker icon)."""
        h = self.height()
        left = h * 1.25
        return QRectF(left, h * 0.30, max(1.0, self.width() - left - h * 0.5), h * 0.40)

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
        track = self._track()
        radius = track.height() / 2
        position = volume_to_position(self._volume)
        reach = volume_to_position(self._limit)
        handle_x = self._x_of(position)

        # Whole track, then the part the child cannot reach (hatched, dim).
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SURFACE_PRESSED if self._dragging else SURFACE)
        painter.drawRoundedRect(track, radius, radius)
        if reach < 1.0:
            blocked = QRectF(self._x_of(reach), track.top(), track.right() - self._x_of(reach),
                             track.height())
            painter.save()
            painter.setClipRect(blocked)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRoundedRect(track, radius, radius)
            painter.setPen(QPen(QColor(TEXT_DIM.red(), TEXT_DIM.green(), TEXT_DIM.blue(), 150), 2))
            step = track.height() * 0.5
            x = blocked.left() - track.height()
            while x < blocked.right():
                painter.drawLine(QPointF(x, track.bottom()), QPointF(x + track.height(), track.top()))
                x += step
            painter.restore()
        # The filled part up to the handle.
        if handle_x > track.left():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT_GREEN)
            painter.save()
            painter.setClipRect(QRectF(track.left(), track.top(), handle_x - track.left(), track.height()))
            painter.drawRoundedRect(track, radius, radius)
            painter.restore()

        # Handle: a big white disc with a dark rim.
        handle_r = self.height() * 0.40
        painter.setPen(QPen(QColor("#111114"), 3))
        painter.setBrush(TEXT)
        painter.drawEllipse(QPointF(handle_x, track.center().y()), handle_r, handle_r)

        self._paint_speaker(painter, QRectF(self.height() * 0.08, self.height() * 0.2,
                                            self.height() * 0.7, self.height() * 0.6))
        painter.end()

    def _paint_speaker(self, painter: QPainter, rect: QRectF) -> None:
        """Speaker with 0..3 sound waves for the current position; a cross when silent."""
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
        if self._volume <= 0:
            painter.drawLine(QPointF(x + w * 0.70, y + h * 0.35), QPointF(x + w * 1.0, y + h * 0.65))
            painter.drawLine(QPointF(x + w * 1.0, y + h * 0.35), QPointF(x + w * 0.70, y + h * 0.65))
            return
        waves = 1 + int(volume_to_position(self._volume) * 2.999)
        for i in range(waves):
            r = h * (0.22 + 0.22 * i)
            arc = QRectF(x + w * 0.55 - r * 0.6, y + h * 0.5 - r, r * 1.2, r * 2)
            painter.drawArc(arc, -45 * 16, 90 * 16)
