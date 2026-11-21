"""The parents' pad view (Loopstation 2, mockup L2-02, variant A): the same window in another state.

A header (Kinder|Eltern switch, the bar chip, Zurück / Wieder / Still, the volume), a tool bar on
the left, the pads as wide tiles and a folded detail line for the chosen pad below them.

The view only reads the controller. What a tap does goes out through signals that the main window
handles, so a tile acts exactly like a pad of the child page in the mode "Spielen". The colour of a
tile is the colour the main window hands in (``Controller.pad_colors``), never derived here.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QAbstractButton, QWidget

from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import ACTIVE_FILL, CARD_BORDER, CARD_FILL, fitted_font, paint_icon
from loopstation.gui.pulse_strip import DOT_OFF, DOT_ON
from loopstation.gui.volume_slider import FILL, TRACK, VolumeSlider, volume_to_position
from loopstation.gui.waveform import peak_columns
from loopstation.gui.widgets import BACKGROUND, PAD_COLORS, SURFACE, TEXT, TEXT_DIM, weak_slot

if TYPE_CHECKING:
    from loopstation.controller import Controller, GridInfo

# Geometry of the mockup at 1280 x 800 (pixels).
MARGIN_LEFT = 20
MARGIN_TOP = 20
MARGIN_RIGHT = 24
MARGIN_BOTTOM = 20
TOOLBAR_WIDTH = 76
TOOLBAR_GAP = 12
HEADER_TOP = 24
HEADER_HEIGHT = 64
HEADER_GRID_GAP = 24
DETAIL_HEIGHT = 64
DETAIL_GAP = 16
TILE_GAP = 14
RING = TILE_GAP // 2  # room around a tile for the ring of the chosen pad
WIDE_HEADER = 1100  # from this header width on the switch and the bar chip have their full size
SWITCH_WIDTH = (190, 220)  # narrow, full
CHIP_WIDTH = (236, 290)
ACTION_WIDTH = 65
ACTION_GAP = 7
VOLUME_WIDTH = (200, 480)  # least, most
WAVE_COLUMNS = 240  # peaks kept per sample; a tile draws fewer bars from them
WAVE_PITCH = 5.6  # pixels from one bar of the mini wave to the next (as the waveform of the parents' pages)
WAVE_CENTER = 0.565  # the mini wave is centred a little below the middle of the tile (mockup)
WAVE_SHARE = 0.3  # the loudest bar spans this share of the tile height
WAVE_MOST = 110.0  # the mini wave never gets taller than this (large windows)
WAVE_CACHE_SIZE = 256

PANEL = QColor(CARD_FILL)
BORDER = QColor(CARD_BORDER)
LABEL = QColor("#C7C7CC")
FRAME_WIDTH = 5

SOURCE_WORDS = {
    "onset": "aus Klatschen",
    "duration": "aus Aufnahmelänge",
    "parent_bpm": "von Hand eingestellt",
    "free_pad": "aus freiem Pad",
}
KEYS_HELP = "Pfeile wählen · Leertaste spielt · L Loop · R nimmt auf · Entf löscht · F1 Kinderseite"

# (settings page key, icon, word) of the tool bar; the gap falls after the first four.
TOOLS = (
    ("pads", "pads", "Pads"),
    ("changes", "history", "Verlauf"),
    ("sets", "save", "Sets"),
    ("export", "download", "Export"),
    ("levels", "sliders", "Pegel"),
    ("devices", "headphones", "Geräte"),
    ("advanced", "gear", "System"),
)
TOOL_GROUP = 4


def decimal(value: float, places: int) -> str:
    """``value`` with a German decimal comma."""
    return f"{value:.{places}f}".replace(".", ",")


def bar_lines(info: GridInfo | None) -> tuple[str, str]:
    """The two lines of the bar chip: tempo and time signature, then where the bar came from."""
    if info is None:
        return "Kein Takt", "die erste Aufnahme setzt ihn"
    bpm = decimal(info.bpm, 0 if abs(info.bpm - round(info.bpm)) < 0.05 else 1)
    source = SOURCE_WORDS.get(info.source, info.source)
    return f"{bpm} BPM · {info.signature}", f"{source} · {decimal(info.seconds, 2)} s"


@dataclass(frozen=True, eq=False)
class TileWave:
    """What a tile shows of one sample: peaks for the mini wave, its length and its loudest point.

    Compared by identity (``eq=False``): the cache hands out one object per sample, and the peaks
    are an array, which has no single truth value for ``==``.
    """

    peaks: np.ndarray
    frames: int
    peak_db: float


class WaveCache:
    """Peaks of each sample, computed once (per sample, free mode and bar length) and kept."""

    def __init__(self) -> None:
        self._waves: OrderedDict[tuple[str, bool, int | None], TileWave | None] = OrderedDict()

    def get(self, controller: Controller, sample: str, pad: int, free: bool,
            grid: int | None) -> TileWave | None:
        key = (sample, free, grid)
        if key in self._waves:
            self._waves.move_to_end(key)
            return self._waves[key]
        data = controller.loop_audio(sample, pad)
        if data is None:
            data = controller.sample_audio(sample)
        wave = None
        if data is not None and len(data):
            loudest = float(np.max(np.abs(data)))
            peak_db = 20 * math.log10(loudest) if loudest > 0 else float("-inf")
            wave = TileWave(peak_columns(data, WAVE_COLUMNS), len(data), peak_db)
        self._waves[key] = wave
        while len(self._waves) > WAVE_CACHE_SIZE:
            self._waves.popitem(last=False)
        return wave


def length_text(wave: TileWave | None, free: bool, grid: int | None, rate: int) -> str:
    """"1 Takt", "2 Takte", "frei 3,1 s" (a free pad) or "2,4 s" (no bar yet)."""
    if wave is None:
        return ""
    seconds = wave.frames / max(1, rate)
    if free:
        return f"frei {decimal(seconds, 1)} s"
    if grid:
        bars = max(1, round(wave.frames / grid))
        return "1 Takt" if bars == 1 else f"{bars} Takte"
    return f"{decimal(seconds, 1)} s"


LEFT_MIDDLE = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def _font(pixels: float, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, round(pixels)))
    font.setWeight(weight)
    return font


def draw_line(painter: QPainter, rect: QRectF, text: str, font: QFont, color: QColor,
              align: Qt.AlignmentFlag = LEFT_MIDDLE) -> None:
    """One line of text in ``rect``, cut with "..." when it does not fit."""
    painter.setFont(font)
    painter.setPen(color)
    shown = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
    painter.drawText(rect, align, shown)


# ------------------------------------------------------------------ header


class ModeSegment(QAbstractButton):
    """One half of the Kinder|Eltern switch."""

    def __init__(self, icon: str, word: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.setText(word)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(word)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PARENT_ACCENT))
            painter.drawRoundedRect(rect, 11, 11)
            color = QColor("#111114")
        else:
            if self.isDown():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#2A2A30"))
                painter.drawRoundedRect(rect, 11, 11)
            color = LABEL
        icon = 20.0
        font = fitted_font(self.text(), rect.width() - icon - 22, 18, QFont.Weight.Bold, 13)
        text_width = QFontMetrics(font).horizontalAdvance(self.text())
        left = (rect.width() - icon - 7 - text_width) / 2
        paint_icon(painter, self.icon_name, QRectF(left, (rect.height() - icon) / 2 - 1, icon, icon), color)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(left + icon + 7, 0, text_width + 2, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class ModeSwitch(QWidget):
    """Kinder|Eltern: "Eltern" is lit while this view is shown; a tap on "Kinder" goes back."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kids_button = ModeSegment("person", "Kinder", self)
        self.parents_button = ModeSegment("padlock-open", "Eltern", self)
        self.parents_button.setChecked(True)
        # A tap on the lit half changes nothing.
        self.parents_button.clicked.connect(weak_slot(self._keep_parents_lit))

    def _keep_parents_lit(self) -> None:
        self.parents_button.setChecked(True)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        inner = self.width() - 8
        half = inner // 2
        self.kids_button.setGeometry(4, 4, half - 2, self.height() - 8)
        self.parents_button.setGeometry(4 + half + 2, 4, inner - half - 2, self.height() - 8)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(PANEL)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 14, 14)
        painter.end()


class BarChip(QAbstractButton):
    """The bar, always in sight: beat dots, "96 BPM · 4/4", where it came from; a tap opens "Takt"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Takt")
        self.levels: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
        self.lines = ("", "")

    def set_state(self, levels: tuple[float, ...], lines: tuple[str, str]) -> None:
        if (levels, lines) != (self.levels, self.lines):
            self.levels, self.lines = levels, lines
            self.setText(lines[0])
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(QColor("#2A2A30") if self.isDown() else PANEL)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 14, 14)
        wide = self.width() >= CHIP_WIDTH[1]
        spacing = 16.0 if wide else 11.0
        first = 22.0 if wide else 16.0
        middle = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        for beat, level in enumerate(self.levels):
            color = QColor(
                round(DOT_OFF.red() + (DOT_ON.red() - DOT_OFF.red()) * level),
                round(DOT_OFF.green() + (DOT_ON.green() - DOT_OFF.green()) * level),
                round(DOT_OFF.blue() + (DOT_ON.blue() - DOT_OFF.blue()) * level),
            )
            radius = 4.0 + 1.5 * level
            painter.setBrush(color)
            painter.drawEllipse(QPointF(first + beat * spacing, middle), radius, radius)
        text_left = first + 3 * spacing + (26 if wide else 16)
        chevron = 34.0 if wide else 26.0
        room = rect.width() - text_left - chevron
        top_font = fitted_font(self.lines[0], room, 18, QFont.Weight.Bold, 12)
        draw_line(painter, QRectF(text_left, 9, room, 24), self.lines[0], top_font, TEXT)
        low_font = fitted_font(self.lines[1], room, 13, QFont.Weight.Medium, 11)
        draw_line(painter, QRectF(text_left, 33, room, 20), self.lines[1], low_font, TEXT_DIM)
        paint_icon(painter, "chevron", QRectF(rect.width() - chevron + 1, middle - 9, 18, 18), TEXT_DIM)
        painter.end()


class SmallAction(QAbstractButton):
    """Zurück, Wieder, Still: a small icon over a short word."""

    def __init__(self, icon: str, word: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.setText(word)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(word)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(QColor("#2A2A30") if self.isDown() else PANEL)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 12, 12)
        color = QColor(TEXT) if self.isEnabled() else QColor("#55555C")
        icon = 20.0
        paint_icon(painter, self.icon_name, QRectF((rect.width() - icon) / 2, 9, icon, icon), color)
        font = fitted_font(self.text(), rect.width() - 6, 12, QFont.Weight.Bold, 10)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(0, 34, rect.width(), 18), Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class HeaderVolume(VolumeSlider):
    """The volume of the parents' header (mockup L2-02): the same control as on the child page,
    drawn for a 64 px high row: a thicker track, a larger handle, outlined speakers and the
    ceiling as a line with a small lock above it.
    """

    def _track(self) -> QRectF:
        h = self.height()
        left = min(h * 1.02, max(h * 0.75, self.width() * 0.2))  # a narrow header keeps more track
        return QRectF(left, h * 0.5 - h * 0.155, max(1.0, self.width() - 2 * left), h * 0.31)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = self.height()
        track = self._track()
        radius = track.height() / 2
        handle_x = self._x_of(volume_to_position(self.volume))
        reach_x = self._x_of(volume_to_position(self.limit))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SURFACE)
        painter.drawRoundedRect(QRectF(self.rect()), 16, 16)
        painter.setBrush(TRACK)
        painter.drawRoundedRect(track, radius, radius)
        painter.save()
        painter.setClipRect(QRectF(track.left(), track.top(), handle_x - track.left(), track.height()))
        painter.setBrush(FILL)
        painter.drawRoundedRect(track, radius, radius)
        painter.restore()
        if self.limit < 1.0:
            # Above the ceiling: cross-hatched, out of reach.
            blocked = QRectF(reach_x, track.top(), track.right() - reach_x, track.height())
            painter.save()
            painter.setClipRect(blocked)
            painter.setBrush(QColor("#2E2E34"))
            painter.drawRoundedRect(track, radius, radius)
            painter.setPen(QPen(QColor("#45454C"), 2))
            x = blocked.left() - track.height()
            while x < blocked.right() + track.height():
                painter.drawLine(QPointF(x, track.bottom()), QPointF(x + track.height(), track.top()))
                painter.drawLine(QPointF(x, track.top()), QPointF(x + track.height(), track.bottom()))
                x += 9
            painter.restore()
        line = QPen(QColor("#AEAEB2"), 2.5)
        line.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(line)
        painter.drawLine(QPointF(reach_x, h * 0.2), QPointF(reach_x, h * 0.9))
        self._paint_lock(painter, QPointF(reach_x, h * 0.07), h * 0.17)
        painter.setPen(QPen(FILL, 3.5))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(handle_x, track.center().y()), h * 0.33, h * 0.33)
        icon = h * 0.42
        color = TEXT if self.isEnabled() else TEXT_DIM
        paint_icon(painter, "speaker-low", QRectF(h * 0.27, (h - icon) / 2, icon, icon), color)
        right = self.width() - h * 0.27 - icon
        paint_icon(painter, "speaker-high", QRectF(right, (h - icon) / 2, icon, icon), color)
        painter.end()


class HeaderBar(QWidget):
    """The top row of the view, laid out by hand so it matches the mockup at every width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode_switch = ModeSwitch(self)
        self.bar_chip = BarChip(self)
        self.undo_button = SmallAction("rotate-ccw", "Zurück", self)
        self.redo_button = SmallAction("rotate-cw", "Wieder", self)
        self.stop_button = SmallAction("stop", "Still", self)
        self.volume_slider = HeaderVolume(self)
        self.volume_slider.setMinimumSize(VOLUME_WIDTH[0], HEADER_HEIGHT)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        width = self.width()
        wide = width >= WIDE_HEADER
        switch = SWITCH_WIDTH[1] if wide else SWITCH_WIDTH[0]
        chip = CHIP_WIDTH[1] if wide else CHIP_WIDTH[0]
        self.mode_switch.setGeometry(0, 4, switch, 56)
        x = switch + 12
        self.bar_chip.setGeometry(x, 4, chip, 56)
        x += chip + 13
        for button in (self.undo_button, self.redo_button, self.stop_button):
            button.setGeometry(x, 4, ACTION_WIDTH, 56)
            x += ACTION_WIDTH + ACTION_GAP + (1 if button is self.redo_button else 0)
        x += 28 - ACTION_GAP - 1
        volume = max(VOLUME_WIDTH[0], min(VOLUME_WIDTH[1], width - x))
        self.volume_slider.setGeometry(width - volume, 0, volume, HEADER_HEIGHT)


# ---------------------------------------------------------------- tool bar


class ToolButton(QAbstractButton):
    """One tool of the left bar: an icon over its word; "Pads" is lit while the pads are shown."""

    def __init__(self, key: str, icon: str, word: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.icon_name = icon
        self.setText(word)
        self.setCheckable(key == "pads")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(word)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        lit = self.isChecked()
        if lit:
            painter.setPen(QPen(QColor(PARENT_ACCENT), 2))
            painter.setBrush(QColor(ACTIVE_FILL))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)
        elif self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2A2A30"))
            painter.drawRoundedRect(rect, 12, 12)
        icon = 23.0
        top = max(4.0, (rect.height() - icon - 26) / 2)
        paint_icon(painter, self.icon_name, QRectF((rect.width() - icon) / 2, top, icon, icon),
                   TEXT if lit else LABEL)
        weight = QFont.Weight.Bold if lit else QFont.Weight.Medium
        font = fitted_font(self.text(), rect.width() - 4, 13, weight, 10)
        draw_line(painter, QRectF(0, top + icon + 4, rect.width(), 20), self.text(), font,
                  TEXT if lit else LABEL, Qt.AlignmentFlag.AlignCenter)
        painter.end()


class ToolBar(QWidget):
    """The left column: Pads, Verlauf, Sets, Export | Pegel, Geräte, System; "Tasten ?" at the bottom."""

    STEP = 74  # from one tool to the next (mockup)
    ITEM = 66  # height of a tool
    TOP = 14
    BOTTOM = 10
    SEPARATOR = 22

    def __init__(self, with_sets: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons: dict[str, ToolButton] = {}
        for key, icon, word in TOOLS:
            button = ToolButton(key, icon, word, self)
            button.setVisible(key != "sets" or with_sets)
            self.buttons[key] = button
        self.buttons["pads"].setChecked(True)
        self.buttons["pads"].clicked.connect(weak_slot(self._keep_pads_lit))
        self.keys_button = ToolButton("keys", "keyboard", "Tasten ?", self)
        self.keys_button.setCheckable(True)
        self._separator_y: float | None = None

    def _keep_pads_lit(self) -> None:
        self.buttons["pads"].setChecked(True)  # the pads are the page this view shows

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        shown = [b for b in self.buttons.values() if not b.isHidden()]
        keys_height = 64
        extra = self.SEPARATOR - (self.STEP - self.ITEM)  # the separator widens one gap by this much
        room = self.height() - self.TOP - self.BOTTOM - keys_height - extra - 12
        step = min(float(self.STEP), room / max(1, len(shown)))
        side = self.width() - 12
        y = float(self.TOP)
        for button in shown:
            if button.key == "levels":
                self._separator_y = y + extra / 2 - (self.STEP - self.ITEM) / 2
                y += extra
            button.setGeometry(6, round(y), side, round(step - (self.STEP - self.ITEM)))
            y += step
        self.keys_button.setGeometry(6, self.height() - self.BOTTOM - keys_height, side, keys_height)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(PANEL)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 16, 16)
        separator = self._separator_y
        if separator is not None:
            painter.setPen(QPen(QColor("#3A3A41"), 1.5))
            painter.drawLine(QPointF(16, separator), QPointF(self.width() - 16, separator))
        painter.end()


# ------------------------------------------------------------------- tiles


@dataclass(frozen=True)
class TileLook:
    color: str
    filled: bool
    looping: bool
    free: bool
    recording: bool
    selected: bool
    length: str
    wave: TileWave | None


class ParentPadTile(QWidget):
    """A wide pad tile: number, length, mini wave and the state symbol in a start field at the bottom left.

    A tap on the start field (on a free pad: the round middle) acts like a tap on the pad of the child page;
    a tap anywhere else only chooses the pad. ``chosen(index)`` on every press, ``start_down(index)`` and
    ``start_up(index, inside)`` around a press on the start field.
    """

    chosen = Signal(int)
    start_down = Signal(int)
    start_up = Signal(int, bool)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.look = TileLook("white", False, False, False, False, False, "", None)
        self.start_held = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"Pad {index + 1}")

    def set_look(self, look: TileLook) -> None:
        if look != self.look:
            self.look = look
            self.update()

    # ------------------------------------------------------------- geometry

    def body(self) -> QRectF:
        """The visible tile (the widget keeps a margin for the ring of the chosen pad)."""
        rect = QRectF(self.rect()).adjusted(RING, RING, -RING, -RING)
        if self.look.free:
            side = min(rect.width(), rect.height())
            return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        return rect

    def start_field(self) -> QRectF:
        body = self.body()
        if self.look.free:
            reach = body.width() * 0.22
            return QRectF(body.center().x() - reach, body.center().y() - reach, 2 * reach, 2 * reach)
        height = min(28.0, body.height() * 0.2)
        return QRectF(body.left() + 10, body.bottom() - 8 - height, height * 8 / 7, height)

    # ----------------------------------------------------------------- mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.chosen.emit(self.index)
        if self.start_field().adjusted(-6, -6, 6, 6).contains(event.position()):
            self.start_held = True
            self.update()
            self.start_down.emit(self.index)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton or not self.start_held:
            return
        self.start_held = False
        self.update()
        inside = self.start_field().adjusted(-6, -6, 6, 6).contains(event.position())
        self.start_up.emit(self.index, inside)

    def let_go(self) -> None:
        """Forget a press on the start field whose release will not come here (the view changes)."""
        if self.start_held:
            self.start_held = False
            self.update()

    # ----------------------------------------------------------------- paint

    def symbol(self) -> str:
        """The state symbol: record on an empty pad, loop on a running loop, play otherwise."""
        look = self.look
        if look.recording:
            return "stop"
        if not look.filled:
            return "record"
        return "loop" if look.looping else "play"

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        look = self.look
        body = self.body()
        base = QColor(PAD_COLORS[look.color])
        empty = look.color == "white"
        radius = body.width() / 2 if look.free else 12.0
        painter.setPen(QPen(QColor("#D0D0D4") if empty else base.darker(108), 1.5))
        painter.setBrush(base)
        painter.drawRoundedRect(body.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
        if look.selected:
            painter.setPen(QPen(QColor(PARENT_ACCENT), 3.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ring = body.adjusted(-RING + 2, -RING + 2, RING - 2, RING - 2)
            painter.drawRoundedRect(ring, radius + RING - 2, radius + RING - 2)
        ink = QColor("#8E8E93") if empty else QColor(0, 0, 0, 165)
        wave_color = base.darker(145)
        if look.free:
            self._paint_free(painter, body, ink, wave_color)
        else:
            self._paint_wide(painter, body, ink, wave_color, empty)
        painter.end()

    def _paint_wide(self, painter: QPainter, body: QRectF, ink: QColor, wave_color: QColor,
                    empty: bool) -> None:
        look = self.look
        number_px = min(15.0, max(11.0, body.height() * 0.085))
        painter.setFont(_font(number_px))
        painter.setPen(ink)
        painter.drawText(QRectF(body.left() + 14, body.top() + 10, body.width() - 28, number_px * 1.6),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(self.index + 1))
        field = self.start_field()
        if look.wave is not None:
            height = min(body.height() * WAVE_SHARE, WAVE_MOST)
            middle = body.top() + body.height() * WAVE_CENTER
            area = QRectF(body.left() + 16, middle - height / 2, body.width() - 32, height)
            self._paint_wave(painter, area, wave_color)
        # Start field with the state symbol.
        painter.setPen(Qt.PenStyle.NoPen)
        if empty:
            painter.setBrush(QColor("#C4C4C4") if self.start_held else QColor("#D6D6D6"))
        else:
            painter.setBrush(QColor(0, 0, 0, 70 if self.start_held else 30))
        painter.drawRoundedRect(field, 7, 7)
        symbol = self.symbol()
        size = field.height() * (0.75 if symbol == "loop" else 0.62)
        color = QColor("#505050") if empty else QColor(0, 0, 0, 175)
        center = field.center()
        box = QRectF(center.x() - size / 2, center.y() - size / 2, size, size)
        if symbol == "loop":
            paint_icon(painter, "repeat", box, color)  # the loop sign of the parents' tiles (mockup)
        else:
            draw_icon(painter, symbol, box, color)
        if look.length or look.recording:
            text = "nimmt auf" if look.recording else look.length
            painter.setFont(_font(min(13.0, max(10.0, body.height() * 0.07))))
            painter.setPen(ink)
            painter.drawText(QRectF(field.right() + 8, field.top(), body.right() - 14 - field.right() - 8,
                                    field.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_free(self, painter: QPainter, body: QRectF, ink: QColor, wave_color: QColor) -> None:
        look = self.look
        side = body.width()
        painter.setFont(_font(min(15.0, max(11.0, side * 0.08))))
        painter.setPen(ink)
        painter.drawText(QRectF(body.left(), body.top() + side * 0.18, side, side * 0.14),
                         Qt.AlignmentFlag.AlignCenter, str(self.index + 1))
        field = self.start_field()
        if self.start_held:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 40))
            painter.drawEllipse(field)
        icon = side * 0.16
        draw_icon(painter, "stop" if look.recording else "wave",
                  QRectF(body.center().x() - icon / 2, body.center().y() - icon / 2, icon, icon), wave_color)
        text = "nimmt auf" if look.recording else look.length
        painter.setFont(_font(min(13.0, max(10.0, side * 0.07))))
        painter.setPen(ink)
        painter.drawText(QRectF(body.left(), body.top() + side * 0.7, side, side * 0.12),
                         Qt.AlignmentFlag.AlignCenter, text)

    def _paint_wave(self, painter: QPainter, area: QRectF, color: QColor) -> None:
        wave = self.look.wave
        assert wave is not None
        bars = max(1, int(area.width() / WAVE_PITCH))
        groups = np.array_split(wave.peaks, bars)
        middle = area.center().y()
        half = area.height() / 2
        pen = QPen(color, 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for index, group in enumerate(groups):
            level = float(group.max()) if len(group) else 0.0
            reach = max(1.5, half * level)
            x = area.left() + (index + 0.5) * area.width() / bars
            painter.drawLine(QPointF(x, middle - reach), QPointF(x, middle + reach))


class TileGrid(QWidget):
    """The tiles in rows and columns, as wide as the room allows (they are not square)."""

    def __init__(self, rows: int, cols: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows, self.cols = rows, cols
        self.tiles = [ParentPadTile(i, self) for i in range(rows * cols)]

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # The widget reaches RING px past the outer tiles on every side (room for the ring).
        inner_w = self.width() - 2 * RING
        inner_h = self.height() - 2 * RING
        width = (inner_w - (self.cols - 1) * TILE_GAP) / self.cols
        height = (inner_h - (self.rows - 1) * TILE_GAP) / self.rows
        for tile in self.tiles:
            row, col = divmod(tile.index, self.cols)
            left = RING + col * (width + TILE_GAP)
            top = RING + row * (height + TILE_GAP)
            tile.setGeometry(round(left - RING), round(top - RING),
                             round(left + width + RING) - round(left - RING),
                             round(top + height + RING) - round(top - RING))


# ------------------------------------------------------------- detail line


class DetailLine(QWidget):
    """The chosen pad in one folded line: its number, "Pad N" and a line of facts.

    The unfoldable detail panel (loop, pad, recording) follows deliberately in the next step
    (part 3), the tool side panels in part 2; this step is the parents' mode itself.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.number = 0
        self.color = "white"
        self.title = ""
        self.info = ""
        self.help = ""

    def set_content(self, number: int, color: str, title: str, info: str, help_text: str) -> None:
        content = (number, color, title, info, help_text)
        if content != (self.number, self.color, self.title, self.info, self.help):
            self.number, self.color, self.title, self.info, self.help = content
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(PANEL)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 16, 16)
        badge = QRectF(16, (rect.height() - 36) / 2, 36, 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PAD_COLORS[self.color]))
        painter.drawRoundedRect(badge, 8, 8)
        painter.setFont(_font(16))
        painter.setPen(QColor("#111114"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.number))
        left = badge.right() + 16
        help_width = 0.0
        if self.help:
            help_font = fitted_font(self.help, rect.width() * 0.5, 14, QFont.Weight.Medium, 11)
            help_width = min(rect.width() * 0.5, QFontMetrics(help_font).horizontalAdvance(self.help) + 4)
            painter.setFont(help_font)
            painter.setPen(LABEL)
            painter.drawText(QRectF(rect.width() - 20 - help_width, 0, help_width, rect.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.help)
        room = rect.width() - left - 20 - (help_width + 24 if help_width else 0)
        draw_line(painter, QRectF(left, 8, room, 26), self.title, _font(18), TEXT)
        draw_line(painter, QRectF(left, 34, room, 22), self.info, _font(14, QFont.Weight.Normal), TEXT_DIM)
        painter.end()


# -------------------------------------------------------------------- view


class ParentView(QWidget):
    """Header, tool bar, tiles and detail line in one frame of the parents' colour.

    Signals (handled by the main window): ``kids_requested`` (the switch), ``tool_requested(key)``
    (a settings page key, also "tempo" from the bar chip), ``pad_down(index)`` / ``pad_up(index, inside)``
    around a press on a start field, ``undo_requested``, ``redo_requested``, ``stop_requested``.
    """

    kids_requested = Signal()
    tool_requested = Signal(str)
    pad_down = Signal(int)
    pad_up = Signal(int, bool)
    undo_requested = Signal()
    redo_requested = Signal()
    stop_requested = Signal()

    def __init__(self, controller: Controller, waves: WaveCache, with_sets: bool, selected: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.waves = waves
        settings = controller.settings
        self.rows, self.cols = settings.rows, settings.cols
        self.selected = min(max(0, selected), self.rows * self.cols - 1)
        self.header = HeaderBar(self)
        self.toolbar = ToolBar(with_sets, self)
        self.grid = TileGrid(self.rows, self.cols, self)
        self.detail = DetailLine(self)
        self.mode_switch = self.header.mode_switch
        self.bar_chip = self.header.bar_chip
        self.undo_button = self.header.undo_button
        self.redo_button = self.header.redo_button
        self.stop_button = self.header.stop_button
        self.volume_slider = self.header.volume_slider
        self.tiles = self.grid.tiles

        self.mode_switch.kids_button.clicked.connect(self.kids_requested)
        self.bar_chip.clicked.connect(weak_slot(self._tool, "tempo"))
        self.undo_button.clicked.connect(self.undo_requested)
        self.redo_button.clicked.connect(self.redo_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.volume_slider.volumeChanged.connect(controller.set_volume)
        for key, button in self.toolbar.buttons.items():
            if key != "pads":
                button.clicked.connect(weak_slot(self._tool, key))
        self.toolbar.keys_button.toggled.connect(weak_slot(self._show_keys, pass_signal_args=True))
        for tile in self.tiles:
            tile.chosen.connect(weak_slot(self.select, pass_signal_args=True))
            tile.start_down.connect(self.pad_down)
            tile.start_up.connect(self.pad_up)
        self._colors: dict[int, str] = {}

    def _tool(self, key: str) -> None:
        self.tool_requested.emit(key)

    # -------------------------------------------------------------- choice

    def select(self, index: int) -> None:
        if 0 <= index < len(self.tiles) and index != self.selected:
            self.selected = index
            self._update_tiles()

    def move_selection(self, d_row: int, d_col: int) -> None:
        """Arrow keys: one pad further; at the edge the choice stays where it is."""
        row, col = divmod(self.selected, self.cols)
        row = min(self.rows - 1, max(0, row + d_row))
        col = min(self.cols - 1, max(0, col + d_col))
        self.select(row * self.cols + col)

    def let_go(self) -> None:
        for tile in self.tiles:
            tile.let_go()

    def _show_keys(self, _on: bool) -> None:
        self._update_detail()

    # ------------------------------------------------------------ geometry

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        width, height = self.width(), self.height()
        self.toolbar.setGeometry(MARGIN_LEFT, MARGIN_TOP, TOOLBAR_WIDTH, height - MARGIN_TOP - MARGIN_BOTTOM)
        left = MARGIN_LEFT + TOOLBAR_WIDTH + TOOLBAR_GAP
        content = width - left - MARGIN_RIGHT
        self.header.setGeometry(left, HEADER_TOP, content, HEADER_HEIGHT)
        detail_top = height - MARGIN_BOTTOM - DETAIL_HEIGHT
        self.detail.setGeometry(left, detail_top, content, DETAIL_HEIGHT)
        grid_top = HEADER_TOP + HEADER_HEIGHT + HEADER_GRID_GAP
        grid_height = detail_top - DETAIL_GAP - grid_top
        self.grid.setGeometry(left - RING, grid_top - RING, content + 2 * RING, grid_height + 2 * RING)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(1000, 600)

    # ------------------------------------------------------------- refresh

    def refresh(self, colors: dict[int, str], levels: tuple[float, ...]) -> None:
        """Bring the view in line with the controller; ``colors`` are those the child page shows."""
        controller = self.controller
        self._colors = colors
        self.volume_slider.set_state(controller.volume, controller.volume_limit)
        self.undo_button.setEnabled(controller.can_undo() or controller.recording_pad is not None)
        self.redo_button.setEnabled(controller.can_redo())
        self.bar_chip.set_state(levels, bar_lines(controller.grid_info()))
        self._update_tiles()

    def _update_tiles(self) -> None:
        controller = self.controller
        grid = controller.grid_frames()
        rate = controller.sample_rate
        for tile in self.tiles:
            index = tile.index
            state = controller.pad(index)
            wave = (self.waves.get(controller, state.sample, index, state.free, grid)
                    if state.sample is not None else None)
            tile.set_look(TileLook(
                color=self._colors.get(index, "white"),
                filled=state.sample is not None,
                looping=state.looping,
                free=state.free,
                recording=index == controller.recording_pad,
                selected=index == self.selected,
                length=length_text(wave, state.free, grid, rate),
                wave=wave,
            ))
        self._update_detail()

    def _update_detail(self) -> None:
        tile = self.tiles[self.selected]
        look = tile.look
        number = tile.index + 1
        help_text = KEYS_HELP if self.toolbar.keys_button.isChecked() else ""
        self.detail.set_content(number, look.color, f"Pad {number}", self._facts(look), help_text)

    def _facts(self, look: TileLook) -> str:
        if look.recording:
            return "nimmt gerade auf · Symbol tippen beendet die Aufnahme"
        if not look.filled:
            return "leer · Symbol tippen oder R nimmt auf"
        parts = [look.length] if look.length else []
        parts.append("frei" if look.free else ("im Raster" if self.controller.grid_frames() else "ohne Takt"))
        if look.looping:
            parts.append("läuft als Loop")
        elif look.color == "green":
            parts.append("spielt")
        else:
            parts.append("bereit")
        if look.wave is not None and math.isfinite(look.wave.peak_db):
            parts.append(f"Spitze {look.wave.peak_db:.0f} dBFS")
        return " · ".join(parts)

    # --------------------------------------------------------------- paint

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), BACKGROUND)
        painter.setPen(QPen(QColor(PARENT_ACCENT), FRAME_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = FRAME_WIDTH / 2
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(half, half, -half, -half), 22, 22)
        painter.end()
