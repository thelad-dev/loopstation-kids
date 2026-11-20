"""Waveform of one loop with the beat lines of the session grid (mockup 13, parents only).

No time axis, no tracks, no editing: it only shows what the loop looks like
on the grid. ``peak_columns`` and ``beat_lines`` are plain functions, so the
drawing can be checked without a screen.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from loopstation.gui.widgets import TEXT_DIM

WAVE_COLOR = "#5AC8FA"
PANEL_COLOR = "#141418"
BAR_LINE = "#3A3A41"
COLUMN_PITCH = 5.6  # pixels from one bar of the wave to the next (mockup)
COLUMN_WIDTH = 3.4
LABEL_TOP = 16  # room for the "Schlag n" labels
MIN_HALF_HEIGHT = 1.5  # silence still shows a thin line


def peak_columns(data: np.ndarray, columns: int) -> np.ndarray:
    """Largest absolute value of each of ``columns`` equal parts of ``data``, scaled so the loudest is 1.

    Silence (or no data) gives zeros. Every column sees at least one frame.
    """
    if columns <= 0:
        return np.zeros(0, dtype=np.float32)
    if len(data) == 0:
        return np.zeros(columns, dtype=np.float32)
    edges = np.linspace(0, len(data), columns + 1).astype(np.int64)
    magnitude = np.abs(np.asarray(data, dtype=np.float32))
    peaks = np.array([
        magnitude[lo: max(hi, lo + 1)].max() for lo, hi in zip(edges[:-1], edges[1:], strict=True)
    ], dtype=np.float32)
    top = float(peaks.max())
    return peaks / top if top > 0 else peaks


def beat_lines(frames: int, bar_frames: int | None, beats: int) -> list[tuple[float, bool, int]]:
    """``(position 0..1, starts a bar, beat number 1..beats)`` for every beat line over ``frames``.

    Without a grid (``bar_frames`` None) there are no lines. The loop is a whole
    number of bars; a partial last bar still gets its lines.
    """
    if bar_frames is None or bar_frames <= 0 or frames <= 0 or beats <= 0:
        return []
    beat_frames = bar_frames / beats
    lines = []
    index = 0
    while index * beat_frames < frames - 1e-6:
        lines.append((index * beat_frames / frames, index % beats == 0, index % beats + 1))
        index += 1
    return lines


class WaveformWidget(QWidget):
    """The wave of a loop, one bar of lines per beat; empty panel text when there is no sound."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setObjectName("waveform")
        self._data: np.ndarray | None = None
        self._bar_frames: int | None = None
        self._beats = 4
        self.empty_text = "Auf diesem Pad ist noch kein Loop."

    def set_loop(self, data: np.ndarray | None, bar_frames: int | None, beats: int) -> None:
        """Show ``data`` (None = empty pad) with beat lines every ``bar_frames / beats`` frames."""
        self._data, self._bar_frames, self._beats = data, bar_frames, beats
        self.update()

    def lines(self) -> list[tuple[float, bool, int]]:
        """The beat lines that are drawn now (for tests)."""
        return [] if self._data is None else beat_lines(len(self._data), self._bar_frames, self._beats)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        panel = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PANEL_COLOR))
        painter.drawRoundedRect(panel, 10, 10)
        font = QFont()
        font.setPointSizeF(8.5)
        painter.setFont(font)
        if self._data is None:
            painter.setPen(TEXT_DIM)
            painter.drawText(panel, Qt.AlignmentFlag.AlignCenter, self.empty_text)
            painter.end()
            return
        width, top, bottom = panel.width(), panel.top() + LABEL_TOP, panel.bottom() - 4
        middle = (top + bottom) / 2
        half = (bottom - top) / 2 - 4
        for position, bar_start, number in self.lines():
            x = panel.left() + position * width
            pen = QPen(QColor(BAR_LINE), 2 if bar_start else 1)
            if not bar_start:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
            painter.setPen(TEXT_DIM)
            painter.drawText(QPointF(x + 6, panel.top() + 12), f"Schlag {number}")
        columns = max(1, int(width / COLUMN_PITCH))
        pen = QPen(QColor(WAVE_COLOR), COLUMN_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for index, peak in enumerate(peak_columns(self._data, columns)):
            x = panel.left() + (index + 0.5) * width / columns
            reach = max(MIN_HALF_HEIGHT, float(peak) * half)
            painter.drawLine(QPointF(x, middle - reach), QPointF(x, middle + reach))
        painter.end()
