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
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
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
TRIM_COLOR = "#7FA7FF"  # the parents' accent: the handles that shorten the loop
TRIM_DIM = QColor(14, 14, 16, 170)  # what a trim would cut off
START_COLOR = "#32D74B"  # loop start mark (pad start offset)


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
    # A trim handle moved (``trim_range`` has the new frames).
    trim_changed = Signal()
    # The loop-start mark is being dragged (live: only the mark moves).
    start_changed = Signal(int)
    # The drag of the loop-start mark ended at a new place (once per drag, with the frame).
    start_committed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180 + FLAG_ROOM)
        self.setObjectName("waveform")
        self.setMouseTracking(True)
        self._data: np.ndarray | None = None
        self._bar_frames: int | None = None
        self._beats = 4
        self._markers: list[int] = []
        self.cursor_frame: int | None = None
        self.selected_marker: int | None = None  # index into the markers
        # Handles that shorten the loop: ``(start, end)`` in frames, the whole loop when untouched.
        self._trim: tuple[int, int] = (0, 0)
        self._drag: str | None = None  # "start", "end" or "loop_start" while a handle is held
        self._start_moved = False  # the held start mark was moved
        self._start_frame = 0  # where the pad loop begins inside the shown wave
        self.start_editable = False  # parents' Loop tab: drag the green start mark
        self.empty_text = "Auf diesem Pad ist noch kein Loop."
        # Where the loop plays while it is listened to (a white line), None when it does not play.
        self.play_frame: int | None = None
        # Beat lines named "bar.beat" ("1.1", "1.2" ... as in the detail panel) instead of "Schlag n".
        self.bar_labels = False

    @property
    def start_frame(self) -> int:
        return self._start_frame

    def set_start_frame(self, frame: int) -> None:
        """Put the loop-start mark at ``frame`` (clamped into the loop)."""
        if self._drag == "loop_start":
            return  # the held mark is where the hand put it
        size = 0 if self._data is None else len(self._data)
        frame = 0 if size <= 0 else min(max(0, int(frame)), size - 1)
        if frame != self._start_frame:
            self._start_frame = frame
            self.update()

    def set_loop(self, data: np.ndarray | None, bar_frames: int | None, beats: int) -> None:
        """Show ``data`` (None = empty pad) with beat lines every ``bar_frames / beats`` frames."""
        self._data, self._bar_frames, self._beats = data, bar_frames, beats
        self._trim, self._drag = (0, 0 if data is None else len(data)), None
        if data is None or self._start_frame >= len(data):
            self._start_frame = 0
        self.update()

    @property
    def trim_range(self) -> tuple[int, int]:
        """The part of the loop between the handles, ``(start, end)`` in frames."""
        return self._trim

    @property
    def loop_frames(self) -> int:
        """Length of the loop that is shown, 0 without one."""
        return 0 if self._data is None else len(self._data)

    @property
    def trimmed(self) -> bool:
        """Has a handle been moved off the loop's ends?"""
        return self._data is not None and self._trim != (0, len(self._data))

    def set_trim_range(self, start: int, end: int) -> None:
        """Put the handles at ``start`` and ``end`` (clamped to the loop, the start before the end)."""
        size = 0 if self._data is None else len(self._data)
        start = min(max(0, int(start)), max(0, size - 1))
        end = min(max(start + 1, int(end)), size)
        if (start, end) != self._trim:
            self._trim = (start, end)
            self.update()
            self.trim_changed.emit()

    def reset_trim(self) -> None:
        """Handles back to the ends of the loop."""
        self.set_trim_range(0, 0 if self._data is None else len(self._data))

    def handle_at(self, x: float) -> str | None:
        """``"start"``, ``"end"`` or ``"loop_start"`` if pixel ``x`` is on a handle, else None.

        Trim handles win when they share a pixel with the start mark (usually at frame 0).
        """
        if self._data is None:
            return None
        handles: list[tuple[str, int]] = [("start", self._trim[0]), ("end", self._trim[1])]
        near = [(abs(self._x_of(frame) - x), name) for name, frame in handles]
        near = [item for item in near if item[0] <= GRAB_PIXELS]
        if near:
            return min(near)[1]
        if self.start_editable and abs(self._x_of(self._start_frame) - x) <= GRAB_PIXELS:
            return "loop_start"
        return None

    def set_markers(self, frames: list[int]) -> None:
        """Show markers at ``frames`` (positions in the loop); the selection moves with the list."""
        chosen = None if self.selected_marker is None else self._markers[self.selected_marker]
        self._markers = sorted(frames)
        self.selected_marker = self._markers.index(chosen) if chosen in self._markers else None
        self.update()

    def set_play_frame(self, frame: int | None) -> None:
        """Show the play head at ``frame`` of the loop (None: hide it)."""
        if frame != self.play_frame:
            self.play_frame = frame
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
        handle = self.handle_at(event.position().x())
        if handle is not None:
            self._drag = handle
            return
        self.pick(event.position().x(), frame)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        x = event.position().x()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self.handle_at(x) else Qt.CursorShape.ArrowCursor)
            return
        panel = self._panel()
        size = 0 if self._data is None else len(self._data)
        frame = round((x - panel.left()) / max(1.0, panel.width()) * size)
        if self._drag == "loop_start":
            frame = 0 if size <= 0 else min(max(0, frame), size - 1)
            if frame != self._start_frame:
                self._start_frame = frame
                self._start_moved = True
                self.update()
                self.start_changed.emit(frame)
            return
        start, end = self._trim
        if self._drag == "start":
            self.set_trim_range(frame, end)
        else:
            self.set_trim_range(start, frame)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            committed = self._drag == "loop_start" and self._start_moved
            self._drag = None
            self._start_moved = False
            if committed:
                self.start_committed.emit(self._start_frame)

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
        lines = self.lines()
        # Narrow (a side panel): "1", "2" ... instead of "Schlag 1" when the words would run into each other.
        step = min((b[0] - a[0] for a, b in zip(lines, lines[1:], strict=False)), default=1.0) * width
        long_words = QFontMetrics(font).horizontalAdvance("Schlag 8") + 10 <= step
        for index, (position, bar_start, number) in enumerate(lines):
            x = panel.left() + position * width
            pen = QPen(QColor(BAR_LINE), 2 if bar_start else 1)
            if not bar_start:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
            painter.setPen(TEXT_DIM)
            if self.bar_labels:
                word = f"{index // max(1, self._beats) + 1}.{number}"
            else:
                word = f"Schlag {number}" if long_words else str(number)
            painter.drawText(QPointF(x + 6, panel.top() + 12), word)
        columns = max(1, int(width / COLUMN_PITCH))
        pen = QPen(QColor(WAVE_COLOR), COLUMN_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for index, peak in enumerate(peak_columns(self._data, columns)):
            x = panel.left() + (index + 0.5) * width / columns
            reach = max(MIN_HALF_HEIGHT, float(peak) * half)
            painter.drawLine(QPointF(x, middle - reach), QPointF(x, middle + reach))
        self._paint_markers(painter, panel, bottom)
        self._paint_trim(painter, panel, bottom)
        self._paint_loop_start(painter, panel, bottom)
        if self.play_frame is not None:
            x = self._x_of(self.play_frame)
            painter.setPen(QPen(QColor(CURSOR_COLOR), 2.5))
            painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
        painter.end()

    def _paint_trim(self, painter: QPainter, panel: QRectF, bottom: float) -> None:
        """What a trim cuts off is dimmed; the two handles are accent lines with a grip."""
        start_x, end_x = (self._x_of(frame) for frame in self._trim)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TRIM_DIM)
        if start_x > panel.left():
            painter.drawRect(QRectF(panel.left(), panel.top(), start_x - panel.left(), bottom - panel.top()))
        if end_x < panel.right():
            painter.drawRect(QRectF(end_x, panel.top(), panel.right() - end_x, bottom - panel.top()))
        bold = QFont()
        bold.setPointSizeF(8.5)
        bold.setBold(True)
        painter.setFont(bold)
        for x, name, left in ((start_x, "Anfang", True), (end_x, "Ende", False)):
            painter.setPen(QPen(QColor(TRIM_COLOR), 3))
            painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
            grip = QRectF(x - 7, panel.top() + (bottom - panel.top()) / 2 - 18, 14, 36)
            painter.setBrush(QColor(TRIM_COLOR))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(grip, 6, 6)
            painter.setPen(QPen(QColor(PANEL_COLOR), 2))
            for dx in (-2, 2):
                painter.drawLine(QPointF(x + dx, grip.top() + 9), QPointF(x + dx, grip.bottom() - 9))
            if not (self.trimmed or self._drag):
                continue  # untouched: only the grips, so the picture stays as in the mockup
            label = QRectF(x + 8, bottom - 22, 70, 18) if left else QRectF(x - 78, bottom - 22, 70, 18)
            side = Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight
            align = side | Qt.AlignmentFlag.AlignVCenter
            word = QFontMetrics(bold).boundingRect(label.toRect(), int(align), name)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PANEL_COLOR))  # readable over the wave
            painter.drawRoundedRect(QRectF(word).adjusted(-4, -1, 4, 1), 4, 4)
            painter.setPen(QColor(TRIM_COLOR))
            painter.drawText(label, align, name)

    def _paint_loop_start(self, painter: QPainter, panel: QRectF, bottom: float) -> None:
        """Green start mark: where this pad's loop begins inside the shown wave."""
        if self._data is None or (self._start_frame <= 0 and not self.start_editable):
            return
        x = self._x_of(self._start_frame)
        painter.setPen(QPen(QColor(START_COLOR), 3))
        painter.drawLine(QPointF(x, panel.top()), QPointF(x, bottom))
        if not self.start_editable:
            return
        grip = QRectF(x - 6, panel.top() + 8, 12, 22)
        painter.setBrush(QColor(START_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(grip, 4, 4)
        bold = QFont()
        bold.setPointSizeF(8.5)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(QColor(START_COLOR))
        painter.drawText(QPointF(x + 8, panel.top() + 20), "Start")

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
