"""Per-pad history (mockup 07): a card with one tile per earlier recording of the pad.

Each tile says how long ago the take was recorded ("vor 2 Min.", from the time
stamp in the take's file name) and has two big buttons: listen and take. The
card sits in the middle of the window on a darkened background.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller, HistoryEntry
from loopstation.gui.icons import draw_icon
from loopstation.gui.widgets import (
    ACCENT_GREEN,
    ACCENT_PURPLE,
    SURFACE_PRESSED,
    TEXT,
    TEXT_DIM,
    BigButton,
    big_font,
    weak_slot,
)

CARD_BACKGROUND = "#1F1F24"
TILE_BACKGROUND = "#2B2B31"
TILE_BORDER = "#3A3A41"
CURRENT_FILL = "#1F3A26"
DIM_ALPHA = 158  # 0.62 of black over the window behind (mockup 07)
TILE_WIDTH = 260
TILE_HEIGHT = 250
TILE_GAP = 24
COLUMNS = 3
SCROLL_BAR_SPACE = 30  # the dark bar (22 px) and its gap to the tiles
BUTTON_SIZE = 100
PEEK = 70  # with more than one row of tiles the next row shows this much, so it is clear one can scroll
LABELS = ("Jetzt", "Vorher", "Davor")
LATER = "Früher"


def relative_time(moment: datetime | None, now: datetime) -> str:
    """"vor 2 Min." and so on, "" if the take has no time stamp."""
    if moment is None:
        return ""
    seconds = (now - moment).total_seconds()
    if seconds < 60:
        return "gerade eben"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"vor {minutes} Min."
    hours = minutes // 60
    if hours < 24:
        return f"vor {hours} Std."
    days = hours // 24
    if days < 7:
        return "vor 1 Tag" if days == 1 else f"vor {days} Tagen"
    return moment.strftime("%d.%m.")


class TileButton(QAbstractButton):
    """A big square button with one icon: listen (play) or take (check)."""

    def __init__(self, icon: str, name: str, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.color = QColor(color)
        self.marked = False  # the take that is on the pad now: green frame, nothing to press
        self.setAccessibleName(name)
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(BUTTON_SIZE, BUTTON_SIZE)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.marked:
            painter.setBrush(QColor(CURRENT_FILL))
            painter.setPen(QColor(ACCENT_GREEN))
        else:
            painter.setBrush(SURFACE_PRESSED.lighter(115) if self.isDown() else QColor(TILE_BORDER))
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 20, 20)
        size = BUTTON_SIZE * 0.44
        icon_rect = QRectF((BUTTON_SIZE - size) / 2, (BUTTON_SIZE - size) / 2, size, size)
        draw_icon(painter, self.icon_name, icon_rect, self.color)
        painter.end()


class HistoryDialog(QDialog):
    """Modal card with every version of one pad: the one on the pad first, then the newest earlier ones."""

    def __init__(self, controller: Controller, pad: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.pad = pad
        self.setWindowTitle(f"Verlauf - Pad {pad + 1}")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.take_buttons: dict[str, TileButton] = {}
        self.listen_buttons: dict[str, TileButton] = {}

        current = controller.pad(pad).sample
        entries = controller.history(pad)
        playing = controller.pad(pad).looping
        now = datetime.fromtimestamp(controller.now())
        ordered = self._ordered(entries, current)
        self.tile_labels: list[str] = []

        grid = QGridLayout()
        grid.setSpacing(TILE_GAP)
        grid.setContentsMargins(0, 0, 0, 0)
        earlier = 0
        for position, entry in enumerate(ordered):
            is_current = entry.sample == current
            if is_current:
                label = LABELS[0]
            else:
                label = (LABELS[1:] + (LATER,) * len(ordered))[earlier]
                earlier += 1
            when = "läuft gerade" if is_current and playing else relative_time(entry.recorded_at, now)
            self.tile_labels.append(label)
            row, column = divmod(position, COLUMNS)
            grid.addWidget(self._tile(label, when, entry.sample, is_current), row, column)

        rows = max(1, -(-len(ordered) // COLUMNS))
        container = QWidget()
        container.setLayout(grid)
        container.setStyleSheet("background: transparent;")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(container)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(TILE_HEIGHT + (PEEK + TILE_GAP if rows > 1 else 0))
        grid.setContentsMargins(0, 0, 30 if rows > 1 else 0, 0)  # clear of the scroll bar
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            # A wide, simple dark scroll bar that small fingers can hit.
            "QScrollBar:vertical { background: #17171B; width: 22px; margin: 0; border-radius: 11px; }"
            "QScrollBar::handle:vertical { background: #5A5A62; min-height: 60px; border-radius: 11px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )

        icon = _Icon("history", ACCENT_PURPLE, 40)
        title = QLabel(f"Pad {pad + 1} - frühere Aufnahmen")
        title.setFont(big_font(21))
        title.setStyleSheet(f"color: {TEXT.name()};")
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(icon)
        head.addWidget(title, 1)

        self.close_button = BigButton("close", "Schließen", TEXT, font_pt=15, pad_x=30, min_height=70)
        self.close_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.close_button.clicked.connect(self.reject)

        card = QFrame()
        card.setObjectName("history_card")
        card.setStyleSheet(
            f"#history_card {{ background: {CARD_BACKGROUND}; border: 3px solid {ACCENT_PURPLE.name()};"
            " border-radius: 28px; }")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(36, 30, 36, 30)
        inner.setSpacing(28)
        inner.addLayout(head)
        inner.addWidget(self.scroll)
        inner.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignHCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        scroll_bar = SCROLL_BAR_SPACE if rows > 1 else 0
        card.setFixedWidth(COLUMNS * TILE_WIDTH + (COLUMNS - 1) * TILE_GAP + 2 * 36 + 6 + scroll_bar)

    @staticmethod
    def _ordered(entries: list[HistoryEntry], current: str | None) -> list[HistoryEntry]:
        """The take on the pad first, then the others newest first (the log lists oldest first)."""
        on_pad = [e for e in entries if e.sample == current]
        others = [e for e in reversed(entries) if e.sample != current]
        return on_pad + others

    def _tile(self, label: str, when: str, sample: str, is_current: bool) -> QFrame:
        tile = QFrame()
        tile.setObjectName("history_tile")
        border = f"3px solid {ACCENT_GREEN.name()}" if is_current else f"1.5px solid {TILE_BORDER}"
        tile.setStyleSheet(
            f"#history_tile {{ background: {TILE_BACKGROUND}; border: {border}; border-radius: 22px; }}")
        tile.setFixedSize(TILE_WIDTH, TILE_HEIGHT)
        name = QLabel(label)
        name.setFont(big_font(18))
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name.setStyleSheet(f"color: {TEXT.name()}; background: transparent; border: none;")
        age = QLabel(when)
        age.setStyleSheet(
            f"color: {TEXT_DIM.name()}; background: transparent; border: none; font-size: 15px;")
        age.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        listen = TileButton("play", "Anhören", ACCENT_GREEN)
        listen.clicked.connect(weak_slot(self.controller.preview, sample))
        take = TileButton("check", "Nehmen", TEXT)
        take.clicked.connect(weak_slot(self._take, sample))
        self.listen_buttons[sample] = listen
        self.take_buttons[sample] = take
        mark = None
        if is_current:
            # The take on the pad right now: a green tick in the place of "Nehmen" (nothing to take).
            take.hide()
            mark = TileButton("check", "Jetzt", ACCENT_GREEN)
            mark.marked = True
            mark.setEnabled(False)

        buttons = QGridLayout()
        buttons.setHorizontalSpacing(12)
        buttons.setVerticalSpacing(6)
        buttons.addWidget(listen, 0, 0)
        buttons.addWidget(mark if mark is not None else take, 0, 1)
        for column, word in enumerate(("Anhören", "jetzt" if is_current else "Nehmen")):
            caption = QLabel(word)
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            caption.setStyleSheet(
                f"color: {TEXT_DIM.name()}; background: transparent; border: none; font-size: 14px;"
                " font-weight: 600;")
            buttons.addWidget(caption, 1, column)

        layout = QVBoxLayout(tile)
        layout.setContentsMargins(24, 18, 24, 14)
        layout.setSpacing(2)
        layout.addWidget(name)
        layout.addWidget(age)
        layout.addSpacing(14)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return tile

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        """Cover the window behind, so the card sits in its middle on the darkened page."""
        window = self.parentWidget().window() if self.parentWidget() is not None else None
        if window is not None and window.isVisible():
            self.setGeometry(window.geometry())
        super().showEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, DIM_ALPHA))
        painter.end()

    def _take(self, sample: str) -> None:
        self.controller.restore(self.pad, sample)
        self.accept()

    def done(self, result: int) -> None:
        """Stop a running preview whenever the dialog closes."""
        self.controller.stop_preview()
        super().done(result)


class _Icon(QWidget):
    """A small icon next to the title."""

    def __init__(self, icon: str, color: QColor, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._color = icon, QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        draw_icon(painter, self._icon, QRectF(self.rect()), self._color)
        painter.end()
