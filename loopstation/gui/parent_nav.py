"""Building blocks of the parents' area: the left navigation, cards and a width-aware card grid.

The parents' area (mockups 09-16) is one window with a navigation on the left
and one page per area on the right. This module has the parts the pages share:

- ``ParentPage``: one entry of the navigation (the pages themselves are built on first use),
- ``ParentNav``: the left column (back button, the seven areas, save button, footer),
- ``CardGrid``: cards in two columns on a wide window, in one column on a narrow one (1024 px),
- ``card``/``dim_label``/``scrolled``: the small helpers every page uses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
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
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS, TEXT, TEXT_DIM, weak_slot

NAV_WIDTH = 260
NAV_WIDTH_NARROW = 240  # below ``NARROW_WINDOW`` px of window width
NARROW_WINDOW = 1150
NAV_BUTTON_HEIGHT = 60
NAV_GAP = 10
ACTIVE_FILL = "#2F3550"
CARD_FILL = "#1B1B1F"
CARD_BORDER = "#2C2C31"
FOOTER_COLOR = "#6E6E75"
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


@dataclass(frozen=True)
class ParentPage:
    """One area of the parents' area. ``build()`` makes the page widget on its first visit."""

    key: str
    icon: str
    label: str
    build: Callable[[], QWidget]


class BackButton(QAbstractButton):
    """"Zur Kinderseite / Eltern-Modus beenden": the way out, top left (mockups 09-16)."""

    def __init__(self, text: str = "Zur Kinderseite", note: str = "Eltern-Modus beenden",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._note = note
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(NAV_WIDTH, 104)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(NAV_WIDTH_NARROW, 104)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3A3A41") if self.isDown() else QColor("#26262B"))
        painter.drawRoundedRect(QRectF(self.rect()), 20, 20)
        paint_icon(painter, "back", QRectF(20, 36, 32, 32), TEXT)
        painter.setFont(fitted_font(self.text(), self.width() - 64 - 12, 18, QFont.Weight.Bold, 14))
        painter.setPen(TEXT)
        painter.drawText(QRectF(64, 30, self.width() - 70, 26),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        note = QFont()
        note.setPixelSize(13)
        painter.setFont(note)
        painter.setPen(TEXT_DIM)
        painter.drawText(QRectF(64, 58, self.width() - 70, 20),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._note)
        painter.end()


class NavButton(QAbstractButton):
    """One area in the navigation: icon and name; the open area is tinted and framed."""

    def __init__(self, icon: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(NAV_BUTTON_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(NAV_WIDTH, NAV_BUTTON_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(NAV_WIDTH_NARROW, NAV_BUTTON_HEIGHT)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        active = self.isChecked()
        rect = QRectF(self.rect())
        if active:
            painter.setPen(QPen(QColor(PARENT_ACCENT), 2))
            painter.setBrush(QColor(ACTIVE_FILL))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 14, 14)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2A2A30") if self.isDown() else QColor(CARD_FILL))
            painter.drawRoundedRect(rect, 14, 14)
        paint_icon(painter, self.icon_name, QRectF(18, 18, 24, 24), PARENT_ACCENT if active else TEXT_DIM)
        room = self.width() - 56 - 8
        font = fitted_font(self.text(), room, 17, QFont.Weight.Bold if active else QFont.Weight.Medium, 14)
        painter.setFont(font)
        painter.setPen(TEXT if active else QColor("#C7C7CC"))
        text = QFontMetrics(font).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(room))
        painter.drawText(QRectF(56, 0, room, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.end()


class ParentNav(QWidget):
    """The left column: back button, the areas, then (below) a free slot, the save line and the footer."""

    selected = Signal(str)  # key of the area that was chosen

    def __init__(self, back: QWidget, footer: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.buttons: dict[str, NavButton] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(back)
        self._layout.addSpacing(20)
        self._buttons_end = self._layout.count()
        self._layout.addStretch(1)
        self.footer = QLabel(footer)
        self.footer.setWordWrap(True)
        self.footer.setContentsMargins(12, 0, 8, 6)
        self.footer.setStyleSheet(f"color: {FOOTER_COLOR}; font-size: 13px;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.set_narrow(False)

    def add_button(self, key: str, icon: str, label: str) -> NavButton:
        button = NavButton(icon, label)
        button.clicked.connect(weak_slot(self._chosen, key))
        if self.buttons:
            self._layout.insertSpacing(self._buttons_end, NAV_GAP)
            self._buttons_end += 1
        self._layout.insertWidget(self._buttons_end, button)
        self._buttons_end += 1
        self.buttons[key] = button
        return button

    def add_bottom(self, widget: QWidget | QLayout) -> None:
        """Below the areas, above the footer (the save line); called before ``finish``."""
        if isinstance(widget, QLayout):
            self._layout.addLayout(widget)
        else:
            self._layout.addWidget(widget)

    def finish(self) -> None:
        self._layout.addWidget(self.footer)

    def set_current(self, key: str) -> None:
        for name, button in self.buttons.items():
            button.setChecked(name == key)

    def set_narrow(self, narrow: bool) -> None:
        self.setFixedWidth(NAV_WIDTH_NARROW if narrow else NAV_WIDTH)

    def _chosen(self, key: str) -> None:
        self.set_current(key)
        self.selected.emit(key)


class IconLabel(QWidget):
    """A small icon (any name ``paint_icon`` knows) in a fixed square."""

    def __init__(self, icon: str, color: str, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._color = icon, QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_icon(painter, self._icon, QRectF(self.rect()), self._color)
        painter.end()


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
