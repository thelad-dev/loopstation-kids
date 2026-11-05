"""Simple vector icons drawn with QPainter.

The icons are painted from geometry instead of Unicode symbols, so they look
the same on every machine and can never turn into missing-glyph boxes.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF


def _square(rect: QRectF) -> QRectF:
    side = min(rect.width(), rect.height())
    return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _arrow_head(painter: QPainter, tip: QPointF, direction: QPointF, size: float, color: QColor) -> None:
    """Filled triangular arrow head pointing along ``direction`` (unit vector)."""
    normal = QPointF(-direction.y(), direction.x())
    base = tip - direction * size
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPolygon(QPolygonF([tip, base + normal * size * 0.75, base - normal * size * 0.75]))


def draw_icon(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Draw icon ``name`` centred in ``rect``."""
    r = _square(rect)
    s = r.width()
    c = r.center()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "play":
        painter.setPen(_pen(color, s * 0.08))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([
            QPointF(r.left() + s * 0.26, r.top() + s * 0.16),
            QPointF(r.left() + s * 0.86, c.y()),
            QPointF(r.left() + s * 0.26, r.bottom() - s * 0.16),
        ]))

    elif name == "record":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(c, s * 0.36, s * 0.36)

    elif name == "stop":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(QRectF(c.x() - s * 0.32, c.y() - s * 0.32, s * 0.64, s * 0.64),
                                s * 0.08, s * 0.08)

    elif name in ("delete", "close"):
        painter.setPen(_pen(color, s * 0.16))
        d = s * 0.28
        painter.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        painter.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))

    elif name == "check":
        painter.setPen(_pen(color, s * 0.15))
        path = QPainterPath(QPointF(r.left() + s * 0.18, c.y() + s * 0.02))
        path.lineTo(QPointF(r.left() + s * 0.42, r.top() + s * 0.74))
        path.lineTo(QPointF(r.left() + s * 0.84, r.top() + s * 0.26))
        painter.drawPath(path)

    elif name == "loop":
        # Circular arrow ("again and again"): an open ring with the head
        # sitting tangentially at the end of the stroke.
        width = s * 0.13
        radius = s * 0.30
        painter.setPen(_pen(color, width))
        arc = QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius)
        start, span = 50.0, -280.0  # Qt degrees, negative span = clockwise on screen
        painter.drawArc(arc, int(start * 16), int(span * 16))
        end = math.radians(start + span)
        end_point = QPointF(c.x() + radius * math.cos(end), c.y() - radius * math.sin(end))
        # Screen-space travel direction of a clockwise arc at angle ``end``.
        direction = QPointF(math.sin(end), math.cos(end))
        head = s * 0.24
        _arrow_head(painter, end_point + direction * head * 0.6, direction, head, color)

    elif name == "undo":
        # Hook arrow pointing left.
        width = s * 0.13
        painter.setPen(_pen(color, width))
        path = QPainterPath(QPointF(r.left() + s * 0.36, r.top() + s * 0.38))
        path.lineTo(QPointF(r.left() + s * 0.58, r.top() + s * 0.38))
        path.cubicTo(QPointF(r.left() + s * 0.92, r.top() + s * 0.38),
                     QPointF(r.left() + s * 0.92, r.top() + s * 0.82),
                     QPointF(r.left() + s * 0.58, r.top() + s * 0.82))
        path.lineTo(QPointF(r.left() + s * 0.34, r.top() + s * 0.82))
        painter.drawPath(path)
        _arrow_head(painter, QPointF(r.left() + s * 0.10, r.top() + s * 0.38),
                    QPointF(-1.0, 0.0), s * 0.26, color)

    elif name == "history":
        # Clock face.
        painter.setPen(_pen(color, s * 0.11))
        painter.drawEllipse(c, s * 0.36, s * 0.36)
        painter.drawLine(c, QPointF(c.x(), c.y() - s * 0.22))
        painter.drawLine(c, QPointF(c.x() + s * 0.16, c.y() + s * 0.08))

    elif name == "trash":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        # lid and handle
        painter.drawRoundedRect(QRectF(r.left() + s * 0.14, r.top() + s * 0.16, s * 0.72, s * 0.11),
                                s * 0.04, s * 0.04)
        painter.drawRoundedRect(QRectF(r.left() + s * 0.38, r.top() + s * 0.06, s * 0.24, s * 0.12),
                                s * 0.04, s * 0.04)
        # body with slots
        body = QPainterPath()
        body.moveTo(r.left() + s * 0.22, r.top() + s * 0.32)
        body.lineTo(r.left() + s * 0.78, r.top() + s * 0.32)
        body.lineTo(r.left() + s * 0.72, r.top() + s * 0.92)
        body.lineTo(r.left() + s * 0.28, r.top() + s * 0.92)
        body.closeSubpath()
        for x in (0.38, 0.5, 0.62):
            slot = QPainterPath()
            slot.addRoundedRect(QRectF(r.left() + s * (x - 0.025), r.top() + s * 0.42,
                                       s * 0.05, s * 0.40), s * 0.02, s * 0.02)
            body = body.subtracted(slot)
        painter.drawPath(body)

    painter.restore()
