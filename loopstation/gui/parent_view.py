"""The parents' pad view (Loopstation 2, mockups L2-02 and L2-05, variant A): one window, another state.

A header (Kinder|Eltern switch, the bar chip, Zurück / Wieder / Still, the volume), a tool bar on
the left, the pads as wide tiles and the detail panel of the chosen pad below them (``DetailPanel``:
folded one line, unfolded about 45 % of the height; the tiles get flatter and stay playable). A tool
opens its side panel (``SidePanelHost``) to the right of the pads; the pads get narrower and stay
playable. The side panel and the unfolded detail panel take turns: opening one folds or closes the other.

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

from loopstation.gui.detail_panel import DetailPanel
from loopstation.gui.icons import draw_icon
from loopstation.gui.level_panel import format_db
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import ACTIVE_FILL, CARD_BORDER, CARD_FILL, draw_line, fitted_font, paint_icon
from loopstation.gui.pulse_strip import DOT_OFF, DOT_ON
from loopstation.gui.side_panel import SidePanelHost
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
DETAIL_SHARE = 0.44  # of the window height for the unfolded detail panel (352 px at 1280 x 800, mockup L2-03)
DETAIL_LEAST = 200  # the unfolded detail panel is never lower than this
MIN_TILE = 72  # an unfolded detail panel leaves the tiles this high if the window allows it
TILE_FLOOR = 64  # and never less: with many rows in a low window the detail panel scrolls instead
TILE_GAP = 14
RING = TILE_GAP // 2  # room around a tile for the ring of the chosen pad
WIDE_HEADER = 1100  # from this header width on the switch and the bar chip have their full size


@dataclass(frozen=True)
class HeaderSizes:
    """Widths of the header parts: the full ones of the mockup, and the narrow ones of a 1024 px window.

    The narrow ones leave the volume as much track, measured against the width of the content, as the
    full ones at 1280 px (mockup L2-02).
    """

    switch: int
    chip: int
    action: int
    action_gap: int
    chip_gap: int  # between the bar chip and "Zurück"
    volume_gap: int  # between "Still" and the volume


HEADER_SIZES = (HeaderSizes(176, 200, 56, 6, 10, 14), HeaderSizes(220, 290, 65, 7, 13, 27))  # narrow, full
VOLUME_WIDTH = (200, 480)  # least, most
WAVE_COLUMNS = 240  # peaks kept per sample; a tile draws fewer bars from them
WAVE_PITCH = 5.6  # pixels from one bar of the mini wave to the next (as the waveform of the parents' pages)
WAVE_CENTER = 0.565  # the mini wave is centred a little below the middle of the tile (mockup)
WAVE_SHARE = 0.3  # the loudest bar spans this share of the tile height
WAVE_MOST = 110.0  # the mini wave never gets taller than this (large windows)
WAVE_CACHE_SIZE = 256
PANEL_GAP = 24  # between the pads and the side panel
PANEL_TOP = HEADER_TOP + HEADER_HEIGHT + 20
PANEL_SHARE = 0.42  # of the room right of the tool bar (480 px at 1280 x 800, mockup L2-05)
PANEL_WIDTH = (380, 560)  # least, most

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
# The keys of the parents' view (the main window handles them), shown behind "Tasten ?".
KEYS_HELP = ("Pfeile wählen · Leertaste spielt · L Loop · R nimmt auf · Entf löscht · Enter Detailfeld · "
             "M Marker · Esc schließt · Strg+Z zurück · Strg+Y wieder · F1 Kinderseite")

# (tool key, icon, word) of the tool bar; the separator falls before "Pegel".
TOOLS = (
    ("pads", "pads", "Pads"),
    ("changes", "history", "Verlauf"),
    ("sets", "save", "Sets"),
    ("export", "download", "Export"),
    ("levels", "sliders", "Pegel"),
    ("devices", "headphones", "Geräte"),
    ("system", "gear", "System"),
)


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


def short_bar_line(info: GridInfo | None) -> str:
    """The second line of the bar chip for a narrow chip: where the bar came from, without its length."""
    if info is None:
        return "erste Aufnahme setzt ihn"
    return SOURCE_WORDS.get(info.source, info.source)


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


def _font(pixels: float, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, round(pixels)))
    font.setWeight(weight)
    return font


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

    ICON = 20  # the icon in front of the word, and the gap after it
    ICON_GAP = 7

    def label_font(self) -> QFont:
        """The font of the word: 18 px, smaller if icon and word would not fit with 5 px on each side."""
        room = self.width() - self.ICON - self.ICON_GAP - 10
        return fitted_font(self.text(), room, 18, QFont.Weight.Bold, 13)

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
        icon, gap = float(self.ICON), self.ICON_GAP
        font = self.label_font()
        text_width = QFontMetrics(font).horizontalAdvance(self.text())
        left = (rect.width() - icon - gap - text_width) / 2
        paint_icon(painter, self.icon_name, QRectF(left, (rect.height() - icon) / 2 - 1, icon, icon), color)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(left + icon + gap, 0, text_width + 2, rect.height()),
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
        self.short_line = ""  # the second line when the full one does not fit

    def set_state(self, levels: tuple[float, ...], lines: tuple[str, str], short_line: str = "") -> None:
        if (levels, lines, short_line) != (self.levels, self.lines, self.short_line):
            self.levels, self.lines, self.short_line = levels, lines, short_line
            self.setText(lines[0])
            self.setToolTip(f"{lines[0]} · {lines[1]} · Tippen öffnet „Takt“")
            self.update()

    def _metrics(self) -> tuple[bool, float, float, float]:
        """Full size or not, the gap of the beat dots, the first dot and where the text starts."""
        wide = self.width() >= HEADER_SIZES[1].chip
        spacing = 16.0 if wide else 10.0
        first = 22.0 if wide else 15.0
        return wide, spacing, first, first + 3 * spacing + (26 if wide else 13)

    def shown_lines(self) -> tuple[tuple[str, QFont], tuple[str, QFont]]:
        """The two lines as they are drawn, each with its font: the second one shortened if need be."""
        wide, _spacing, _first, text_left = self._metrics()
        room = self.width() - text_left - (34.0 if wide else 24.0)
        top_font = fitted_font(self.lines[0], room, 18, QFont.Weight.Bold, 12)
        low = self.lines[1]
        low_font = fitted_font(low, room, 13, QFont.Weight.Medium, 11)
        if self.short_line and QFontMetrics(low_font).horizontalAdvance(low) > room:
            low = self.short_line
            low_font = fitted_font(low, room, 13, QFont.Weight.Medium, 11)
        top = QFontMetrics(top_font).elidedText(self.lines[0], Qt.TextElideMode.ElideRight, int(room))
        low = QFontMetrics(low_font).elidedText(low, Qt.TextElideMode.ElideRight, int(room))
        return (top, top_font), (low, low_font)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(QPen(BORDER, 1.5))
        painter.setBrush(QColor("#2A2A30") if self.isDown() else PANEL)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 14, 14)
        wide, spacing, first, text_left = self._metrics()
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
        chevron = 34.0 if wide else 24.0
        room = rect.width() - text_left - chevron
        (top, top_font), (low, low_font) = self.shown_lines()
        draw_line(painter, QRectF(text_left, 9, room, 24), top, top_font, TEXT)
        draw_line(painter, QRectF(text_left, 33, room, 20), low, low_font, TEXT_DIM)
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
    ceiling as a line with a small lock above it. ``compact`` (a narrow header): smaller speakers
    and handle, so the track keeps its share of the window.
    """

    compact = False

    def _shape(self) -> tuple[float, float, float]:
        """Margin and size of the speakers and the radius of the handle (as shares of the height)."""
        return (0.19, 0.34, 0.28) if self.compact else (0.27, 0.42, 0.33)

    def _track(self) -> QRectF:
        h = self.height()
        if self.compact:
            margin, icon, handle = self._shape()
            left = h * (margin + icon + handle) + 2  # the handle at the ends just clears the speakers
        else:
            left = min(h * 1.02, max(h * 0.75, self.width() * 0.2))
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
        margin, icon_share, handle = self._shape()
        painter.setPen(QPen(FILL, 3.5))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(handle_x, track.center().y()), h * handle, h * handle)
        icon = h * icon_share
        color = TEXT if self.isEnabled() else TEXT_DIM
        paint_icon(painter, "speaker-low", QRectF(h * margin, (h - icon) / 2, icon, icon), color)
        right = self.width() - h * margin - icon
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
        self.undo_button.setToolTip("Zurück (Strg+Z)")
        self.redo_button.setToolTip("Wiederholen (Strg+Y)")
        self.stop_button.setToolTip("Alles still")
        self.volume_slider = HeaderVolume(self)
        self.volume_slider.setMinimumSize(VOLUME_WIDTH[0], HEADER_HEIGHT)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        width = self.width()
        wide = width >= WIDE_HEADER
        sizes = HEADER_SIZES[1 if wide else 0]
        self.mode_switch.setGeometry(0, 4, sizes.switch, 56)
        x = sizes.switch + 12
        self.bar_chip.setGeometry(x, 4, sizes.chip, 56)
        x += sizes.chip + sizes.chip_gap
        for button in (self.undo_button, self.redo_button, self.stop_button):
            button.setGeometry(x, 4, sizes.action, 56)
            x += sizes.action + (sizes.action_gap + (1 if button is self.redo_button else 0)
                                 if button is not self.stop_button else 0)
        x += sizes.volume_gap
        volume = max(VOLUME_WIDTH[0], min(VOLUME_WIDTH[1], width - x))
        self.volume_slider.compact = not wide
        self.volume_slider.setGeometry(width - volume, 0, volume, HEADER_HEIGHT)


# ---------------------------------------------------------------- tool bar


class ToolButton(QAbstractButton):
    """One tool of the left bar: an icon over its word; "Pads" is lit while the pads are shown."""

    def __init__(self, key: str, icon: str, word: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
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
    """The left column: Pads, Verlauf, Sets, Export | Pegel, Geräte, System; "Tasten ?" at the bottom.

    The lit tool is the page shown: "Pads" while no side panel is open, else the tool of the panel.
    """

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
        self.current: str | None = None
        self.keys_button = ToolButton("keys", "keyboard", "Tasten ?", self)
        self._separator_y: float | None = None
        self.set_current(None)

    def set_current(self, key: str | None) -> None:
        """Light the tool ``key`` (None: "Pads"); a tap toggles a button, this sets them all right again."""
        self.current = key
        lit = key or "pads"
        for name, button in self.buttons.items():
            button.setChecked(name == lit)

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
    a tap anywhere else only chooses the pad. ``touched(index)`` on every press, ``chosen(index)`` on a
    press outside the start field (starting a pad does not choose it), ``start_down(index)`` and
    ``start_up(index, inside)`` around a press on the start field, ``opened(index)`` on a double click
    outside the start field (it unfolds the detail panel).
    """

    touched = Signal(int)
    chosen = Signal(int)
    start_down = Signal(int)
    start_up = Signal(int, bool)
    opened = Signal(int)

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
        self.touched.emit(self.index)
        if self.start_field().adjusted(-6, -6, 6, 6).contains(event.position()):
            self.start_held = True
            self.update()
            self.start_down.emit(self.index)
        else:
            self.chosen.emit(self.index)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        # On the start field the second tap of a double click is a tap like any other.
        if event.button() == Qt.MouseButton.LeftButton and not self.start_field().adjusted(
                -6, -6, 6, 6).contains(event.position()):
            self.touched.emit(self.index)
            self.chosen.emit(self.index)
            self.opened.emit(self.index)
            return
        self.mousePressEvent(event)

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


# -------------------------------------------------------------------- view


class ParentView(QWidget):
    """Header, tool bar, tiles, detail panel and (while a tool is open) its side panel in one frame.

    Signals (handled by the main window): ``kids_requested`` (the switch), ``tool_requested(key)``
    (a tool of the bar, also "tempo" from the bar chip; "pads" and the cross of the panel close it),
    ``pads_touched`` (a press on a tile), ``pad_down(index)`` /
    ``pad_up(index, inside)`` around a press on a start field, ``undo_requested``, ``redo_requested``,
    ``stop_requested``.
    """

    kids_requested = Signal()
    tool_requested = Signal(str)
    pads_touched = Signal()
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
        self.detail = DetailPanel(controller, self)
        self.detail.show_pad(self.selected)
        self.detail.fold_changed.connect(weak_slot(self._detail_folded, pass_signal_args=True))
        self.side_panel = SidePanelHost(self)
        self.side_panel.hide()
        self.side_panel.close_requested.connect(weak_slot(self._tool, "pads"))  # as "Pads" does
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
            button.clicked.connect(weak_slot(self._tool, key))
        self.toolbar.keys_button.toggled.connect(weak_slot(self._show_keys, pass_signal_args=True))
        for tile in self.tiles:
            tile.chosen.connect(weak_slot(self.select, pass_signal_args=True))
            tile.touched.connect(self.pads_touched)
            tile.opened.connect(weak_slot(self.open_detail))
            tile.start_down.connect(self.pad_down)
            tile.start_up.connect(self.pad_up)
        self._colors: dict[int, str] = {}

    def _tool(self, key: str) -> None:
        self.toolbar.set_current(self.panel_key)  # the main window lights the tool it opens
        self.tool_requested.emit(key)

    # ---------------------------------------------------------- side panel

    @property
    def panel_key(self) -> str | None:
        """The tool whose side panel is open, or None."""
        return None if self.side_panel.isHidden() else self.side_panel.key

    def open_panel(self, key: str, icon: str, title: str, line: str, widget: QWidget) -> None:
        """Show ``widget`` as the side panel of the tool ``key``; the pads move over, the details fold."""
        self.detail.set_open(False)
        self.side_panel.show_page(key, icon, title, line, widget)
        self.side_panel.show()
        self.toolbar.set_current(key)
        self._layout()

    def close_panel(self) -> None:
        """Close the side panel: the pads take the whole width again."""
        if not self.side_panel.isHidden():
            self.side_panel.hide()
        self.side_panel.key = None
        self.toolbar.set_current(None)
        self._layout()

    # -------------------------------------------------------------- choice

    # -------------------------------------------------------- detail panel

    def open_detail(self) -> None:
        """Unfold the detail panel of the chosen pad (a side panel closes for it)."""
        self.detail.set_open(True)

    def toggle_detail(self) -> None:
        self.detail.set_open(not self.detail.is_open)

    def _detail_folded(self, unfolded: bool) -> None:
        if unfolded and self.panel_key is not None:
            self.close_panel()
        self._layout()

    def select(self, index: int) -> None:
        if 0 <= index < len(self.tiles) and index != self.selected:
            self.selected = index
            self._update_tiles()
            self.detail.show_pad(index)  # the detail panel follows the chosen pad

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
        self._layout()

    def _layout(self) -> None:
        width, height = self.width(), self.height()
        self.toolbar.setGeometry(MARGIN_LEFT, MARGIN_TOP, TOOLBAR_WIDTH, height - MARGIN_TOP - MARGIN_BOTTOM)
        left = MARGIN_LEFT + TOOLBAR_WIDTH + TOOLBAR_GAP
        content = width - left - MARGIN_RIGHT
        self.header.setGeometry(left, HEADER_TOP, content, HEADER_HEIGHT)
        pads = content
        if not self.side_panel.isHidden():
            panel = max(PANEL_WIDTH[0], min(PANEL_WIDTH[1], round(content * PANEL_SHARE)))
            pads = content - panel - PANEL_GAP
            self.side_panel.setGeometry(left + pads + PANEL_GAP, PANEL_TOP, panel,
                                        height - MARGIN_BOTTOM - PANEL_TOP)
        detail_height = self.detail_height(height)
        detail_top = height - MARGIN_BOTTOM - detail_height
        self.detail.setGeometry(left, detail_top, pads, detail_height)
        grid_top = HEADER_TOP + HEADER_HEIGHT + HEADER_GRID_GAP
        grid_height = detail_top - DETAIL_GAP - grid_top
        self.grid.setGeometry(left - RING, grid_top - RING, pads + 2 * RING, grid_height + 2 * RING)

    def detail_height(self, height: int) -> int:
        """The detail panel: one line folded; unfolded about 45 % of ``height``, the tiles still playable."""
        if not self.detail.is_open:
            return DETAIL_HEIGHT
        grid_top = HEADER_TOP + HEADER_HEIGHT + HEADER_GRID_GAP
        free = height - MARGIN_BOTTOM - DETAIL_GAP - grid_top - (self.rows - 1) * TILE_GAP
        wanted = max(DETAIL_LEAST, min(round(height * DETAIL_SHARE), free - self.rows * MIN_TILE))
        return max(DETAIL_HEIGHT, min(wanted, free - self.rows * TILE_FLOOR))

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
        info = controller.grid_info()
        self.bar_chip.set_state(levels, bar_lines(info), short_bar_line(info))
        self._update_tiles()
        self.detail.refresh()

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
            parts.append(f"Spitze {format_db(min(0, round(look.wave.peak_db)), 'dBFS')}")
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
