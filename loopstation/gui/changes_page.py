"""History and undo section of the parents' area (mockup 12, plan 6.1 to 6.3 and 10.3).

One page with the global "Zurück" and "Wiederholen" buttons, the list of the
changes on the undo stack (newest first, the undone ones on top greyed out) and
"Alle Pads löschen ...". The page owns no state: every row comes from
``Controller.changes()``, which reads the stacks of the state and the time of
each change from the event log. It listens to the controller (weakly, like the
main window) and rebuilds only when the stacks changed; ``refresh()`` can also
be called when the page is shown.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation import events as ev
from loopstation.controller import ChangeEntry
from loopstation.gui.confirm_dialog import ConfirmDialog
from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS, TEXT, TEXT_DIM, weak_slot

if TYPE_CHECKING:
    from loopstation.controller import Controller

MAX_ROWS = 60  # the newest rows shown; the stack itself can hold 1000 steps
CARD_TITLE = "Änderungen dieser Sitzung"
EMPTY_TEXT = "Noch nichts geändert."
FOOTNOTE = "Ältere Takes eines Pads: Verlauf-Modus auf der Kinderseite."
DELETE_HINTS = ("Fragt nach. Danach mit „Zurück“ umkehrbar.", "Tipp: vorher als Set sichern.")
NOT_LATEST_TIP = "Erst die neueren Änderungen dieses Pads zurücknehmen."

ROW_FILL = "#26262B"
ROW_FILL_DIM = "#1A1A1E"
ROW_FILL_NEXT = "#2F3550"
BUTTON_BORDER = "#3A3A41"
DELETE_FILL = "#3A1F1F"
DELETE_TEXT = "#FF8A80"
DELETE_BORDER = QColor(255, 59, 48, 128)


def seconds_text(seconds: float) -> str:
    return f"{seconds:.1f}".replace(".", ",") + " s"


def steps_text(count: int) -> str:
    return "1 Schritt" if count == 1 else f"{count} Schritte"


def describe_change(entry: ChangeEntry) -> str:
    """``Pad 4 · Aufnahme gelöscht`` for one stack entry (pads are shown 1-based)."""
    if entry.kind == ev.DELETE_ALL:
        count = len(entry.pads)
        return "Alle Pads gelöscht" + (f" ({count} Pads)" if count > 1 else "")
    pads = ", ".join(str(pad + 1) for pad in entry.pads)
    who = f"Pad {pads}" if len(entry.pads) == 1 else f"Pads {pads}"
    if entry.kind == ev.RECORD_STOP:
        duration = entry.detail.get("duration")
        length = f" ({seconds_text(duration)})" if isinstance(duration, int | float) else ""
        return f"{who} · neue Aufnahme{length}" + (" - ersetzt die vorherige" if entry.replaces else "")
    if entry.kind == ev.DELETE_PAD:
        return f"{who} · Aufnahme gelöscht"
    if entry.kind == ev.RESTORE_PAD:
        return f"{who} · älterer Take zurückgeholt"
    if entry.kind == ev.PAD_FREE:
        return f"{who} · freier Modus " + ("an" if entry.detail.get("free", True) else "aus")
    return f"{who} · Änderung"


class ActionButton(QAbstractButton):
    """A flat rounded button with a vector icon and a bold word (mockup 12, top row and bottom)."""

    def __init__(self, icon: str, text: str, fill: str = ROW_FILL, border: str | QColor = BUTTON_BORDER,
                 color: str = TEXT.name(), font_px: float = 19, icon_scale: float = 1.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name = icon
        self.setText(text)
        self._fill, self._border, self._color = QColor(fill), QColor(border), QColor(color)
        self._icon_scale = icon_scale
        font = QFont()
        font.setPixelSize(round(font_px))
        font.setBold(True)
        self.setFont(font)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _icon_size(self) -> float:
        return QFontMetrics(self.font()).height() * self._icon_scale

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = QFontMetrics(self.font())
        width = 2 * 22 + self._icon_size() + 12 + metrics.horizontalAdvance(self.text())
        return QSize(int(width), 64 if self.font().pixelSize() >= 16 else 32)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        enabled = self.isEnabled()
        fill, color = QColor(self._fill), QColor(self._color)
        if self.isDown():
            fill = fill.lighter(125)
        if not enabled:
            color.setAlpha(110)
        radius = 12.0 if self.height() > 40 else 10.0
        painter.setPen(QPen(self._border, 1.5) if enabled else QPen(QColor(BUTTON_BORDER), 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        metrics = QFontMetrics(self.font())
        icon = self._icon_size()
        text_width = metrics.horizontalAdvance(self.text())
        left = rect.center().x() - (icon + 12 + text_width) / 2
        draw_icon(painter, self.icon_name, QRectF(left, rect.center().y() - icon / 2, icon, icon), color)
        painter.setFont(self.font())
        painter.setPen(color)
        painter.drawText(QRectF(left + icon + 12, rect.top(), text_width + 2, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


def _label(text: str, size: float, color: str, weight: str = "400") -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent;")
    return label


class ChangesPage(QWidget):
    """Mockup 12: back / forward, the list of changes, delete all."""

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        # A factory so a test can replace the modal dialog.
        self.confirm_factory: Callable[[QWidget], QDialog] = ConfirmDialog
        self._shown: tuple[object, ...] | None = None
        self.rows: list[QFrame] = []
        self.row_buttons: list[ActionButton | None] = []
        self.row_entries: list[ChangeEntry] = []
        self.setObjectName("changes_page")
        self.setStyleSheet(
            "#changes_card { background: #1B1B1F; border: 1px solid #2C2C31; border-radius: 18px; } "
            "#changes_info { background: #1B1B1F; border: 1px solid #2C2C31; border-radius: 14px; } "
            "#changes_scroll, #changes_inner { background: transparent; border: none; } "
            + DARK_SCROLLBAR_QSS)

        self.back_button = ActionButton("undo", "Zurück")
        self.forward_button = ActionButton("redo", "Wiederholen")
        self.back_button.clicked.connect(weak_slot(self._undo))
        self.forward_button.clicked.connect(weak_slot(self._redo))
        self.back_label = _label("", 15, TEXT.name(), "700")
        self.forward_label = _label("", 13, TEXT_DIM.name())
        self.back_label.setWordWrap(True)
        self.forward_label.setWordWrap(True)  # narrow window: the shortcuts wrap instead of being cut off
        info = QFrame()
        info.setObjectName("changes_info")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(22, 10, 22, 10)
        info_layout.setSpacing(2)
        info_layout.addWidget(self.back_label)
        info_layout.addWidget(self.forward_label)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info.setMinimumHeight(64)
        same = max(self.back_button.sizeHint().width(), self.forward_button.sizeHint().width())
        for button in (self.back_button, self.forward_button):
            button.setMinimumWidth(same)
            # as tall as the info box
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.back_button)
        top.addWidget(self.forward_button)
        top.addWidget(info, 1)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        inner = QWidget()
        inner.setObjectName("changes_inner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addLayout(self._rows_layout)
        inner_layout.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("changes_scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(inner)
        self.scroll.setMinimumHeight(200)

        card = QFrame()
        card.setObjectName("changes_card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 14)
        card_layout.setSpacing(10)
        card_layout.addWidget(_label(CARD_TITLE, 19, TEXT.name(), "700"))
        card_layout.addWidget(self.scroll, 1)
        card_layout.addWidget(_label(FOOTNOTE, 13, TEXT_DIM.name()))

        self.delete_button = ActionButton("trash", "Alle Pads löschen …", DELETE_FILL, DELETE_BORDER,
                                          DELETE_TEXT, font_px=16, icon_scale=1.15)
        self.delete_button.clicked.connect(weak_slot(self.confirm_delete_all))
        hints = QVBoxLayout()
        hints.setSpacing(2)
        for text in DELETE_HINTS:
            hints.addWidget(_label(text, 13.5, TEXT_DIM.name()))
        bottom = QHBoxLayout()
        bottom.setSpacing(20)
        bottom.addWidget(self.delete_button)
        bottom.addLayout(hints, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(top)
        layout.addWidget(card, 1)
        layout.addLayout(bottom)

        controller.add_listener(weak_slot(self.refresh))
        self.refresh()

    # --------------------------------------------------------------- actions

    def _undo(self) -> None:
        self.controller.undo()

    def _redo(self) -> None:
        self.controller.redo()

    def _undo_pad(self, pad: int) -> None:
        self.controller.undo(pad)

    def confirm_delete_all(self) -> bool:
        """Ask yes or no; on yes empty every pad (the stack keeps it, so "Zurück" brings it back)."""
        if self.confirm_factory(self).exec() != QDialog.DialogCode.Accepted:
            return False
        self.controller.delete_all()
        return True

    # ---------------------------------------------------------------- update

    def refresh(self) -> None:
        """Show the current stacks (cheap when nothing changed)."""
        controller = self.controller
        state = controller.store.state
        key = (controller.store.last_seq, len(state.undo_stack), len(state.redo_stack),
               controller.recording_pad)
        if key == self._shown:
            return
        self._shown = key
        undo, redo = controller.undo_depth(), controller.redo_depth()
        self.back_button.setEnabled(controller.can_undo())
        self.forward_button.setEnabled(controller.can_redo())
        self.back_label.setText(
            f"Zurück möglich: {steps_text(undo)}" if undo else "Zurück: nichts mehr möglich")
        self.forward_label.setText(
            (f"Wiederholen möglich: {steps_text(redo)}" if redo else "Wiederholen: nichts zu wiederholen")
            + " · Strg+Z / Strg+Y")
        self._rebuild(controller.changes())

    def _rebuild(self, changes: list[ChangeEntry]) -> None:
        while self._rows_layout.count():
            widget = self._rows_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.rows, self.row_buttons, self.row_entries = [], [], []
        if not changes:
            self._rows_layout.addWidget(_label(EMPTY_TEXT, 14.5, TEXT_DIM.name()))
            return
        touched: set[int] = set()  # pads of the newer undo rows: only the latest row of a pad can step back
        next_undo = True
        for entry in changes[:MAX_ROWS]:
            button_pad = None
            if not entry.undone:
                if len(entry.pads) == 1 and entry.pads[0] not in touched:
                    button_pad = entry.pads[0]
                touched.update(entry.pads)
            row, button = self._row(entry, next_undo and not entry.undone, button_pad)
            if not entry.undone:
                next_undo = False
            self._rows_layout.addWidget(row)
            self.rows.append(row)
            self.row_buttons.append(button)
            self.row_entries.append(entry)
        if len(changes) > MAX_ROWS:
            more = f"… und {len(changes) - MAX_ROWS} ältere Schritte"
            self._rows_layout.addWidget(_label(more, 13, TEXT_DIM.name()))

    def _row(
        self, entry: ChangeEntry, is_next: bool, button_pad: int | None
    ) -> tuple[QFrame, ActionButton | None]:
        row = QFrame()
        row.setObjectName("change_row")
        fill = ROW_FILL_DIM if entry.undone else ROW_FILL_NEXT if is_next else ROW_FILL
        # always 2 px wide, so the text of the next row does not move
        border = f"2px solid {PARENT_ACCENT if is_next else 'transparent'}"
        row.setStyleSheet(f"#change_row {{ background: {fill}; border: {border}; border-radius: 10px; }}")
        row.setFixedHeight(48)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(22, 0, 14, 0)
        layout.setSpacing(24)

        stamp = _label(entry.when.strftime("%H:%M") if entry.when else "", 14, TEXT_DIM.name(), "600")
        stamp.setFixedWidth(44)
        text_color = TEXT_DIM.name() if entry.undone else TEXT.name()
        text = _label(describe_change(entry), 15.5, text_color, "700" if is_next else "500")
        text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(stamp)
        layout.addWidget(text, 1)

        button = None
        if entry.undone:
            chip = _label("wiederholbar", 12, "#AEAEB2", "700")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFixedSize(130, 28)
            chip.setStyleSheet(chip.styleSheet() + " background: #3A3A41; border-radius: 14px;")
            layout.addWidget(chip)
        elif len(entry.pads) == 1:
            button = ActionButton(
                "undo", "nur dieses Pad", "#3A3A41", "#3A3A41", font_px=12.5, icon_scale=1.1)
            button.setFixedSize(136, 32)
            if button_pad is not None and self.controller.can_undo(button_pad):
                button.clicked.connect(weak_slot(self._undo_pad, button_pad))
            else:
                button.setEnabled(False)
                button.setToolTip(NOT_LATEST_TIP)
            layout.addWidget(button)
        return row, button
