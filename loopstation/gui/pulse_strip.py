"""The pulse strip at the bottom of the child page (mockups 01-07).

One dot per beat of the bar; the current beat lights up softly and fades out
over the beat. No numbers, no blinking: a slow swell, so a child can feel the
beat without being startled. Without a running loop the dots rest, dim. The
status line of the window sits below the dots and replaces the word "Puls"
while it has something to say.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from loopstation.gui.widgets import TEXT_DIM

STRIP_HEIGHT = 92  # as the action buttons next to it
DOT_SPACING = 34
DOT_RADIUS = 8.0
DOT_GROW = 2.0  # the lit dot is this much larger
HALO_RADIUS = 16.0
DOT_CENTER_Y = 32
RISE = 0.18  # share of a beat that the glow takes to swell up; the rest is the fade-out
STEPS = 16  # brightness is repainted in this many steps, not on every tick
SURFACE_DARK = QColor("#1B1B1F")
DOT_OFF = QColor("#3A3A41")
DOT_ON = QColor("#5AC8FA")
CAPTION = QColor("#55555C")
CAPTION_TEXT = "Puls"


def beat_glow(distance: float) -> float:
    """Brightness 0..1 of a dot ``distance`` beats after its beat began: a soft swell, then a slow fade."""
    if not 0.0 <= distance < 1.0:
        return 0.0
    if distance < RISE:
        t = distance / RISE
        return t * t * (3.0 - 2.0 * t)
    return 0.5 * (1.0 + math.cos(math.pi * (distance - RISE) / (1.0 - RISE)))


def glow_levels(beats: int, position: float | None) -> tuple[float, ...]:
    """Brightness of every dot for the grid ``position`` (in beats from the bar start), at rest for None."""
    if position is None or beats <= 0:
        return (0.0,) * max(beats, 0)
    levels = []
    for beat in range(beats):
        level = beat_glow((position - beat) % beats)
        levels.append(round(level * STEPS) / STEPS)
    return tuple(levels)


class PulseStrip(QWidget):
    """Dots for the beats of the bar and a one-line status text below them."""

    def __init__(self, beats: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.beats = beats
        self.levels = glow_levels(beats, None)
        self.setFixedHeight(STRIP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label = QLabel("")
        self.status_label.setParent(self)
        font = QFont()
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.Medium)
        self.status_label.setFont(font)
        self.status_label.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 8)
        layout.addStretch(1)
        layout.addWidget(self.status_label)
        self.status_label.setFixedHeight(36)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(380, STRIP_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(DOT_SPACING * 4 + 4, STRIP_HEIGHT)

    def set_status(self, text: str) -> None:
        if text != self.status_label.text():
            self.status_label.setText(text)
            self.status_label.setToolTip(text)
            self.update()

    def set_pulse(self, beats: int, position: float | None) -> None:
        """Show ``beats`` dots lit for ``position``; repaints only when a dot's brightness changed."""
        levels = glow_levels(beats, position)
        if (beats, levels) != (self.beats, self.levels):
            self.beats, self.levels = beats, levels
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SURFACE_DARK)
        painter.drawRoundedRect(QRectF(self.rect()), 18, 18)
        spacing = min(float(DOT_SPACING), (self.width() - 40.0) / max(1, self.beats))
        for beat, level in enumerate(self.levels):
            cx = self.width() / 2 + (beat - (self.beats - 1) / 2) * spacing
            if level > 0:
                halo = QColor(DOT_ON)
                halo.setAlphaF(0.25 * level)
                painter.setBrush(halo)
                painter.drawEllipse(QRectF(cx - HALO_RADIUS, DOT_CENTER_Y - HALO_RADIUS,
                                           2 * HALO_RADIUS, 2 * HALO_RADIUS))
            color = QColor(
                round(DOT_OFF.red() + (DOT_ON.red() - DOT_OFF.red()) * level),
                round(DOT_OFF.green() + (DOT_ON.green() - DOT_OFF.green()) * level),
                round(DOT_OFF.blue() + (DOT_ON.blue() - DOT_OFF.blue()) * level),
            )
            radius = DOT_RADIUS + DOT_GROW * level
            painter.setBrush(color)
            painter.drawEllipse(QRectF(cx - radius, DOT_CENTER_Y - radius, 2 * radius, 2 * radius))
        if not self.status_label.text():
            font = QFont()
            font.setPixelSize(13)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QPen(CAPTION))
            painter.drawText(QRectF(0, 60, self.width(), 20), Qt.AlignmentFlag.AlignCenter, CAPTION_TEXT)
        painter.end()
