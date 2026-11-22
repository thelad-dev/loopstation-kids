"""Building blocks the parents' pages share: icons, cards and a width-aware card grid.

The pages of the parents' view open as side panels next to the pads (``side_panel``). This module has
the parts they share:

- ``paint_icon``/``qicon``/``IconLabel``: the icons of the mockups,
- ``CardGrid``: cards in two columns on a wide page, in one column on a narrow one (a side panel),
- ``CurrentPageStack``: pages one over the other, only the shown one counts for the size,
- ``card``/``dim_label``/``scrolled``: the small helpers every page uses.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS, TEXT, TEXT_DIM

ACTIVE_FILL = "#2F3550"
CARD_FILL = "#1B1B1F"
CARD_BORDER = "#2C2C31"
WIDE_PAGE = 860  # content width from which cards go side by side

# Icons the shared icon set (``icons.draw_icon``) does not have: the paths of the mockups (24 px grid).
_SVG_ICONS = {
    "sliders": ["M4 21v-7", "M4 10V3", "M12 21v-9", "M12 8V3", "M20 21v-5", "M20 12V3", "M1 14h6", "M9 8h6",
                "M17 16h6"],
    "headphones": ["M3 18v-6a9 9 0 0 1 18 0v6",
                   "M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3z",
                   "M3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"],
    "pulse": ["M22 12h-4l-3 9L9 3l-3 9H2"],
    "mic": ["M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v4",
            "M8 23h8"],
    "info": ["M12 2a10 10 0 1 0 0.01 0", "M12 16v-4", "M12 8h.01"],
    "alert": ["M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z",
              "M12 9v4", "M12 17h.01"],
    # The parents' pad view (mockup L2-02): its tool bar, the mode switch and the bar chip.
    "pads": ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"],
    "gear": ["M12 8.5a3.5 3.5 0 1 0 0.01 0", "M12 2v3", "M12 19v3", "M2 12h3", "M19 12h3",
             "M4.9 4.9l2.1 2.1", "M17 17l2.1 2.1", "M4.9 19.1l2.1-2.1", "M17 7l2.1-2.1"],
    "keyboard": ["M2 6h20v12H2z", "M6 10h.01", "M10 10h.01", "M14 10h.01", "M18 10h.01", "M7 14h10"],
    "person": ["M12 3.5a3.5 3.5 0 1 0 0.01 0", "M5 21v-1.5a7 7 0 0 1 14 0V21"],
    "chevron": ["M6 9l6 6 6-6"],
    "speaker-low": ["M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 0 1 0 7.07"],
    "speaker-high": ["M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 0 1 0 7.07",
                     "M19.07 4.93a10 10 0 0 1 0 14.14"],
    "padlock-open": ["M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z",
                     "M7 11V7a5 5 0 0 1 9.9-1"],
    "rotate-ccw": ["M1 4v6h6", "M3.51 15a9 9 0 1 0 2.13-9.36L1 10"],
    "rotate-cw": ["M23 4v6h-6", "M20.49 15a9 9 0 1 1-2.12-9.36L23 10"],
    "repeat": ["M17 2l4 4-4 4", "M3 11v-1a4 4 0 0 1 4-4h14", "M7 22l-4-4 4-4", "M21 13v1a4 4 0 0 1-4 4H3"],
}
_renderers: dict[tuple[str, str], QSvgRenderer] = {}


def paint_icon(painter: QPainter, name: str, rect: QRectF, color: QColor | str) -> None:
    """Draw icon ``name``: the shared ones with ``draw_icon``, the few extra ones from their path."""
    shade = QColor(color)
    paths = _SVG_ICONS.get(name)
    if paths is None:
        draw_icon(painter, name, rect, shade)
        return
    key = (name, shade.name())
    renderer = _renderers.get(key)
    if renderer is None:
        body = "".join(f'<path d="{d}"/>' for d in paths)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{shade.name()}" stroke-width="2.1" stroke-linecap="round" '
               f'stroke-linejoin="round">{body}</svg>')
        renderer = QSvgRenderer(svg.encode("utf-8"))
        _renderers[key] = renderer
    side = min(rect.width(), rect.height())
    renderer.render(painter, QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side))


def fitted_font(text: str, room: float, pixels: int, weight: QFont.Weight, least: int = 13) -> QFont:
    """The font for ``text`` at ``pixels``, a little smaller if it would not fit into ``room`` px."""
    font = QFont()
    font.setWeight(weight)
    for size in range(pixels, least - 1, -1):
        font.setPixelSize(size)
        if QFontMetrics(font).horizontalAdvance(text) <= room:
            break
    return font


def qicon(name: str, color: QColor | str, size: int = 28) -> QIcon:
    """``paint_icon`` as a ``QIcon`` (for the icon of a push button)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_icon(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    return QIcon(pixmap)


class IconLabel(QWidget):
    """A small icon (any name ``paint_icon`` knows) in a fixed square."""

    def __init__(self, icon: str, color: str, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._color = icon, QColor(color)
        self.setFixedSize(size, size)

    def set_icon(self, icon: str) -> None:
        if icon != self._icon:
            self._icon = icon
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_icon(painter, self._icon, QRectF(self.rect()), self._color)
        painter.end()


def breakable(path: object) -> str:
    """``path`` as text a wrapped label can break after each folder (Qt keeps a Windows path in one piece)."""
    return re.sub(r"([\\/])", "\\1\u200b", str(path))


def dim_label(text: str, size: float = 13, color: str | None = None) -> QLabel:
    """A wrapped, dim hint line."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color or TEXT_DIM.name()}; font-size: {size}px;")
    return label


def card(title: str = "", subtitle: str = "", name: str = "card",
         margins: tuple[int, int, int, int] = (22, 18, 22, 18), spacing: int = 8,
         icon: str = "") -> tuple[QFrame, QVBoxLayout]:
    """A rounded card with a bold title (and a dim line under it); returns the card and its layout.

    ``icon`` puts a small icon in the accent colour in front of the title.
    """
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    if title:
        heading = QLabel(title)
        heading.setWordWrap(True)  # a long title wraps instead of being cut off
        heading.setStyleSheet("font-size: 19px; font-weight: bold;")
        if icon:
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(IconLabel(icon, PARENT_ACCENT, 28))
            row.addWidget(heading, 1)
            layout.addLayout(row)
        else:
            layout.addWidget(heading)
    if subtitle:
        layout.addWidget(dim_label(subtitle, 13.5))
    return frame, layout


def scrolled(inner: QWidget) -> QScrollArea:
    """``inner`` in a vertical scroll area without a frame (the dark scroll bar comes from the page style)."""
    inner.setObjectName("scroll_inner")
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


class CurrentPageStack(QWidget):
    """Pages one over the other of which only the current one is shown and counts for the size.

    A ``QStackedWidget`` is as large as its largest page. Here the other pages are hidden, and a layout
    leaves hidden widgets out. The calls are those of the stacked widget that the pages use.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages: list[QWidget] = []
        self._current: QWidget | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, page: QWidget) -> int:  # noqa: N802 - Qt API
        self._pages.append(page)
        self._layout.addWidget(page)
        page.setVisible(False)
        if self._current is None:
            self.setCurrentWidget(page)
        return len(self._pages) - 1

    def setCurrentWidget(self, page: QWidget) -> None:  # noqa: N802 - Qt API
        for other in self._pages:
            other.setVisible(other is page)
        self._current = page

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt API
        self.setCurrentWidget(self._pages[index])

    def currentWidget(self) -> QWidget | None:  # noqa: N802 - Qt API
        return self._current


class CardGrid(QWidget):
    """Rows of cards. A row of two goes side by side from ``WIDE_PAGE`` px, else everything is stacked.

    ``rows`` is a list of rows, each a list of one widget (full width) or two (left, right);
    ``ratio`` is the width share of the two columns; ``stretch_last`` lets the last row take the spare height.
    The minimum width is that of the widest single card, so
    the page never needs a sideways scroll bar at 1024 px.
    """

    def __init__(self, rows: list[list[QWidget]], ratio: tuple[int, int] = (1, 1), gap: int = 16,
                 spacing: int = 14, stretch_last: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stretch_last = stretch_last
        self._rows = rows
        self._ratio = ratio
        self._wide: bool | None = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(gap)
        self._grid.setVerticalSpacing(spacing)
        self._grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        for row in rows:
            for widget in row:
                widget.setParent(self)
                # The share of the width comes from ``ratio``, not from what a card would like.
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
        self._arrange(False)

    @property
    def wide(self) -> bool:
        return bool(self._wide)

    def _arrange(self, wide: bool) -> None:
        if wide == self._wide:
            return
        self._wide = wide
        grid = self._grid
        while grid.count():
            grid.takeAt(0)
        for column in range(2):
            grid.setColumnStretch(column, 0)
            grid.setColumnMinimumWidth(column, 0)
        for row in range(grid.rowCount()):
            grid.setRowStretch(row, 0)
        index = 0
        for row in self._rows:
            if wide and len(row) == 2:
                grid.addWidget(row[0], index, 0)
                grid.addWidget(row[1], index, 1)
                grid.setRowStretch(index, 0)
                index += 1
            elif wide:
                grid.addWidget(row[0], index, 0, 1, 2)
                index += 1
            else:
                for widget in row:
                    grid.addWidget(widget, index, 0)
                    index += 1
        if wide:
            grid.setColumnStretch(0, self._ratio[0])
            grid.setColumnStretch(1, self._ratio[1])
        else:
            grid.setColumnStretch(0, 1)
        if self._stretch_last:
            grid.setRowStretch(index - 1, 1)
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        self._arrange(event.size().width() >= WIDE_PAGE)
        super().resizeEvent(event)


RADIO_QSS = (
    "QRadioButton::indicator { width: 18px; height: 18px; border-radius: 11px; "
    "border: 2px solid #6E6E75; background: #1B1B1F; } "
    f"QRadioButton::indicator:checked {{ border: 2px solid {PARENT_ACCENT}; "
    "background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, "
    f"stop:0 {PARENT_ACCENT}, stop:0.55 {PARENT_ACCENT}, stop:0.6 #1B1B1F, stop:1 #1B1B1F); }} "
)

# A wider bar whose handle sits right: the cards keep a gap to it when a page scrolls.
SCROLLBAR_GAP_QSS = (
    "QScrollBar:vertical { width: 18px; } "
    "QScrollBar::handle:vertical { margin: 0 0 0 8px; } "
)

PAGE_STYLE = (
    f"QLabel, QRadioButton, QCheckBox {{ color: {TEXT.name()}; font-size: 16px; }} "
    f"#card {{ background: {CARD_FILL}; border: 1.5px solid {CARD_BORDER}; border-radius: 18px; }} "
    "#scroll_inner, QScrollArea { background: transparent; border: none; } "
    + DARK_SCROLLBAR_QSS + SCROLLBAR_GAP_QSS
)
