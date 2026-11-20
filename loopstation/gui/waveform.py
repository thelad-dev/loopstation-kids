"""Waveform of one loop with the beat lines of the session grid (mockup 13, parents only).

No time axis, no tracks, no editing of the sound: it shows what the loop looks
like on the grid, with the parents' markers (orange flags, mockup 13). A click
puts a cursor on the wave, a click on a flag selects that marker; the page turns
that into "Marker setzen" and "Marker löschen". ``peak_columns`` and
``beat_lines`` are plain functions, so the drawing can be checked without a screen.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from loopstation.gui.widgets import TEXT_DIM

WAVE_COLOR = "#5AC8FA"
PANEL_COLOR = "#141418"
BAR_LINE = "#3A3A41"
COLUMN_PITCH = 5.6  # pixels from one bar of the wave to the next (mockup)
COLUMN_WIDTH = 3.4
LABEL_TOP = 16  # room for the "Schlag n" labels
MIN_HALF_HEIGHT = 1.5  # silence still shows a thin line
MARKER_COLOR = "#FF9F0A"
CURSOR_COLOR = "#F2F2F2"
FLAG_ROOM = 22  # space above the panel for the marker flags
GRAB_PIXELS = 14  # a click this close to a marker's line selects it


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


def marker_name(index: int) -> str:
    """"Marker A", "Marker B" ...: the name follows the order of the markers."""
    return f"Marker {chr(ord('A') + index % 26)}"


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

    # The cursor or the selected marker changed by a click (the page enables its buttons).
    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180 + FLAG_ROOM)
        self.setObjectName("waveform")
        self._data: np.ndarray | None = None
        self._bar_frames: int | None = None
        self._beats = 4
        self._markers: list[int] = []
        self.cursor_frame: int | None = None
        self.selected_marker: int | None = None  # index into the markers
        self.empty_text = "Auf diesem Pad ist noch kein Loop."

    def set_loop(self, data: np.ndarray | None, bar_frames: int | None, beats: int) -> None:
        """Show ``data`` (None = empty pad) with beat lines every ``bar_frames / beats`` frames."""
        self._data, self._bar_frames, self._beats = data, bar_frames, beats
        self.update()

    def set_markers(self, frames: list[int]) -> None:
        """Show markers at ``frames`` (positions in the loop); the selection moves with the list."""
        chosen = None if self.selected_marker is None else self._markers[self.selected_marker]
        self._markers = sorted(frames)
        self.selected_marker = self._markers.index(chosen) if chosen in self._markers else None
        self.update()

    def clear_selection(self) -> None:
        """Forget the cursor and the selected marker (another pad or loop is shown)."""
        self.cursor_frame, self.selected_marker = None, None
        self.update()

    @property
    def markers(self) -> list[int]:
        return list(self._markers)

    def _panel(self) -> QRectF:
        return QRectF(self.rect()).adjusted(0, FLAG_ROOM, 0, 0)

    def _x_of(self, frame: int) -> float:
        panel = self._panel()
        return panel.left() + panel.width() * frame / (1 if self._data is None else max(1, len(self._data)))

    def frame_at(self, x: float) -> int | None:
        """The frame under pixel ``x`` (at least 1 and inside the loop), None without a loop."""
        if self._data is None or len(self._data) < 2:
            return None
        panel = self._panel()
        frame = round((x - panel.left()) / max(1.0, panel.width()) * len(self._data))
        return min(len(self._data) - 1, max(1, frame))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            return
        frame = self.frame_at(event.position().x())
        if frame is None:
            return
        self.pick(event.position().x(), frame)

    def pick(self, x: float, frame: int) -> None:
        """A click at pixel ``x`` (loop frame ``frame``): select the marker there, else move the cursor."""
        near = [(abs(self._x_of(m) - x), i) for i, m in enumerate(self._markers)]
        near = [item for item in near if item[0] <= GRAB_PIXELS]
        if near:
            self.selected_marker, self.cursor_frame = min(near)[1], None
        else:
            self.selected_marker, self.cursor_frame = None, frame
        self.update()
        self.selection_changed.emit()

    def lines(self) -> list[tuple[float, bool, int]]:
        """The beat lines that are drawn now (for tests)."""
        return [] if self._data is None else beat_lines(len(self._data), self._bar_frames, self._beats)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        panel = QRectF(self.rect())
        panel = self._panel()
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
        self._paint_markers(painter, panel, bottom)
        painter.end()

    def _paint_markers(self, painter: QPainter, panel: QRectF, bottom: float) -> None:
        if self.cursor_frame is not None:
            x = self._x_of(self.cursor_frame)
            cursor = QColor(CURSOR_COLOR)
            cursor.setAlpha(170)
            pen = QPen(cursor, 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
        bold = QFont()
        bold.setPointSizeF(9)
        bold.setBold(True)
        for index, frame in enumerate(self._markers):
            x = self._x_of(frame)
            chosen = index == self.selected_marker
            painter.setPen(QPen(QColor(MARKER_COLOR), 4 if chosen else 3))
            painter.drawLine(QPointF(x, panel.top() - 4), QPointF(x, bottom))
            flag = QPainterPath()  # the pointed flag of the mockup, tip down on the line
            top = panel.top() - 18
            flag.moveTo(x - 9, top)
            flag.lineTo(x + 9, top)
            flag.lineTo(x + 9, top + 10)
            flag.lineTo(x, top + 18)
            flag.lineTo(x - 9, top + 10)
            flag.closeSubpath()
            painter.setBrush(QColor(MARKER_COLOR))
            painter.setPen(QPen(QColor(CURSOR_COLOR), 2) if chosen else Qt.PenStyle.NoPen)
            painter.drawPath(flag)
            painter.setFont(bold)
            painter.setPen(QColor(MARKER_COLOR))
            painter.drawText(QPointF(x + 12, panel.top() - 6), marker_name(index))
