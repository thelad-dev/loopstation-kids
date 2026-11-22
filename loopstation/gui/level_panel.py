"""The level section of the parents' view, the side panel "Pegel" (mockups 09 and L2-05, plan 3.1, 7 and 9).

Three sections, one under the other (the side panel is narrow): the ceiling, the
microphone with its scale, trim and automatic features, and the list of loud recordings.
The controls act at once: ``edited(key, value, final)`` goes to the settings panels, which
hand the value to the controller and write ``settings.toml`` when ``final`` is true (a switch,
the end of a drag, a slider left after arrow keys) or after the pause of a number field.

The panel owns no state of its own. The ceiling, the trim and the switches
show and set the controller's values; the loud recordings come from the
controller's clip log. The volume itself lives in the slider of the header,
the same one source of truth the child's slider uses.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.clips import ClipEvent
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.peak_meter import PeakMeter
from loopstation.gui.widgets import ACCENT_ORANGE, ACCENT_RED, TEXT, TEXT_DIM, weak_slot

if TYPE_CHECKING:
    from loopstation.controller import Controller

# The settings this panel takes over from the generic rows (the beeps are on the panel "System").
PANEL_KEYS = ("volume", "max_level_db", "input_gain_db", "auto_gain", "peak_meter", "soft_seam")

HONESTY_TITLE = "dBFS ist nicht dB am Ohr"
HONESTY_TEXT = "Systemlautstärke und Kopfhörer zählen mit · WHO: 75 dBA, 40 h/Woche"
CLIP_TIP = "Tipp: Trim etwas senken oder Mikro weiter weg."
CLIP_EMPTY = "Noch war nichts zu laut."
CLIP_ROWS = 4  # most recent loud recordings shown

MINUS = "−"


def format_db(value: float, unit: str, signed: bool = False) -> str:
    """``-6`` -> ``−6 dBFS``; one decimal only where the value has one."""
    number = f"{value:+.1f}" if signed else f"{value:.1f}"
    if number.endswith(".0"):
        number = number[:-2]
    if number in ("-0", "+0"):
        number = "0"
    return f"{number} {unit}".replace("-", MINUS).replace(".", ",")


def format_when(at: float, now: datetime | None = None) -> str:
    """``Heute 16:42``, ``Gestern 18:05``, else ``19.11. 07:30``."""
    moment = datetime.fromtimestamp(at)
    today = (now or datetime.now()).date()
    days = (today - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"Heute {clock}"
    if days == 1:
        return f"Gestern {clock}"
    return f"{moment.day}.{moment.month}. {clock}"


def describe_clip(event: ClipEvent) -> str:
    peak = min(0, round(event.peak_db))
    text = f"Pad {event.pad + 1} · Spitze {format_db(peak, 'dBFS')}"
    return text + " · übersteuert" if event.clipped else text


class DbSlider(QWidget):
    """Horizontal slider with the value above the handle and both ends named below (mockup 09)."""

    valueChanged = Signal(float)  # noqa: N815 - Qt API; while dragging or stepping with the keys
    released = Signal(float)  # the drag ended, or the slider was left after the keys moved it

    HEIGHT = 74
    HANDLE = 14.0

    def __init__(
        self, low: float, high: float, step: float, unit: str,
        ends: tuple[str, str], signed: bool = False, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.low, self.high, self.step = low, high, step
        self._unit, self._ends, self._signed = unit, ends, signed
        self._value = low
        self._dragging = False
        self._keyed = False  # moved by keys since the last ``released``
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(396, self.HEIGHT)

    @property
    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        """Show ``value`` (no signal)."""
        value = min(self.high, max(self.low, value))
        if value != self._value:
            self._value = value
            self.update()

    def _snap(self, value: float) -> float:
        value = min(self.high, max(self.low, value))
        return round(round((value - self.low) / self.step) * self.step + self.low, 6)

    def text(self) -> str:
        return format_db(self._value, self._unit, self._signed)

    def _track(self) -> QRectF:
        return QRectF(self.HANDLE, 31, max(1.0, self.width() - 2 * self.HANDLE), 12)

    def _x_of(self, value: float) -> float:
        track = self._track()
        return track.left() + track.width() * (value - self.low) / (self.high - self.low)

    def _set_from_x(self, x: float) -> None:
        track = self._track()
        fraction = min(1.0, max(0.0, (x - track.left()) / track.width()))
        value = self._snap(self.low + fraction * (self.high - self.low))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if self._dragging:
            self._set_from_x(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._keyed = False
            self.released.emit(self._value)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        moves = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1,
                 Qt.Key.Key_PageDown: -5, Qt.Key.Key_PageUp: 5}
        move = moves.get(Qt.Key(event.key()))
        if move is None:
            super().keyPressEvent(event)
            return
        value = self._snap(self._value + move * self.step)
        if value != self._value:
            self._value = value
            self._keyed = True
            self.update()
            self.valueChanged.emit(value)  # saved after the pause, as a number field (or when left)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt API
        super().focusOutEvent(event)
        if self._keyed:
            self._keyed = False
            self.released.emit(self._value)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track()
        x = self._x_of(self._value)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3A3A41"))
        painter.drawRoundedRect(track, 6, 6)
        painter.setBrush(QColor(PARENT_ACCENT))
        painter.save()
        painter.setClipRect(QRectF(track.left(), track.top(), x - track.left(), track.height()))
        painter.drawRoundedRect(track, 6, 6)
        painter.restore()
        painter.setPen(QPen(QColor(PARENT_ACCENT), 4))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(x, track.center().y()), self.HANDLE, self.HANDLE)
        if self.hasFocus():
            painter.setPen(QPen(QColor(TEXT), 1.5, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(x, track.center().y()), self.HANDLE + 4, self.HANDLE + 4)

        bold = QFont()
        bold.setPixelSize(14)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(x - 70, 0, 140, 22), Qt.AlignmentFlag.AlignCenter, self.text())
        small = QFont()
        small.setPixelSize(12)
        painter.setFont(small)
        painter.setPen(QColor(TEXT_DIM))
        painter.drawText(QRectF(0, 52, self.width() / 2, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._ends[0])
        painter.drawText(QRectF(self.width() / 2, 52, self.width() / 2, 20),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._ends[1])
        painter.end()


class WarnIcon(QWidget):
    """Warning triangle with an exclamation mark: the shape that goes with the colour."""

    def __init__(self, color: QColor, size: int = 24, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        pen = QPen(self._color, max(1.6, w * 0.09))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([QPointF(w * 0.5, w * 0.12), QPointF(w * 0.92, w * 0.85),
                                       QPointF(w * 0.08, w * 0.85)]))
        painter.drawLine(QPointF(w * 0.5, w * 0.4), QPointF(w * 0.5, w * 0.58))
        painter.drawPoint(QPointF(w * 0.5, w * 0.72))
        painter.end()


class PanelEditor:
    """What the settings page needs of an editor: ``field``, ``widget`` and ``value()``."""

    def __init__(self, field: Any, widget: QWidget, value: Callable[[], Any]) -> None:
        self.field = field
        self.widget = widget
        self.value = value


class ClipList(QWidget):
    """The remembered loud recordings, newest first (mockup 09, last card)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shown: tuple[Any, ...] | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self.rows: list[QFrame] = []

    def set_events(self, events: list[ClipEvent], now: datetime | None = None) -> None:
        shown = tuple(events[:CLIP_ROWS])
        key = (shown, (now or datetime.now()).date())
        if key == self._shown:
            return
        self._shown = key
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = []
        if not shown:
            empty = QLabel(CLIP_EMPTY)
            empty.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px;")
            self._layout.addWidget(empty)
            return
        for event in shown:
            self.rows.append(self._row(event, now))

    def _row(self, event: ClipEvent, now: datetime | None) -> QFrame:
        row = QFrame()
        row.setObjectName("clip_row")
        row.setStyleSheet("#clip_row { background: #26262B; border-radius: 10px; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(14)
        layout.addWidget(WarnIcon(ACCENT_RED if event.clipped else ACCENT_ORANGE))
        title = QLabel(format_when(event.at, now))
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        detail = QLabel(describe_clip(event))
        detail.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 12.5px;")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(title)
        texts.addWidget(detail)
        layout.addLayout(texts, 1)
        self._layout.addWidget(row)
        return row


class LevelPanel(QWidget):
    """The four cards; takes its values from ``values`` (the keys of ``PANEL_KEYS``)."""

    edited = Signal(str, object, bool)  # key, value, final

    def __init__(self, controller: Controller, values: dict[str, Any], fields: dict[str, Any],
                 switch_factory: Callable[[], Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._switch_factory = switch_factory
        self.editors: dict[str, PanelEditor] = {}
        self.switches: dict[str, Any] = {}

        self.ceiling = DbSlider(-30, 0, 1, "dBFS", (f"{MINUS}30 dBFS", "0 dBFS"))
        self.ceiling.set_value(values["max_level_db"])
        self.trim = DbSlider(-24, 24, 0.5, "dB", (f"{MINUS}24 dB", "+24 dB"), signed=False)
        self.trim.set_value(values["input_gain_db"])
        self.meter = PeakMeter()
        self.clip_list = ClipList()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        for card in (self._ceiling_card(), self._input_card(values), self._clips_card()):
            outer.addWidget(card)

        for slider, key in ((self.ceiling, "max_level_db"), (self.trim, "input_gain_db")):
            slider.valueChanged.connect(weak_slot(self._emit_edited, key, False, pass_signal_args=True))
            slider.released.connect(weak_slot(self._emit_edited, key, True, pass_signal_args=True))
        for key, switch in self.switches.items():
            switch.toggled.connect(weak_slot(self._emit_switched, key, pass_signal_args=True))

        for key, slider in (("max_level_db", self.ceiling), ("input_gain_db", self.trim)):
            self.editors[key] = PanelEditor(fields[key], slider, lambda slider=slider: slider.value)
        for key, switch in self.switches.items():
            self.editors[key] = PanelEditor(fields[key], switch, switch.isChecked)
        controller = self.controller
        self.editors["volume"] = PanelEditor(fields["volume"], self, lambda: controller.volume)
        self.refresh()

    def _emit_edited(self, key: str, final: bool, value: Any) -> None:
        self.edited.emit(key, value, final)

    def _emit_switched(self, key: str, on: Any) -> None:
        self.edited.emit(key, bool(on), True)

    # ------------------------------------------------------------ the cards

    @staticmethod
    def _card(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setWordWrap(True)  # a narrow side panel: the title wraps instead of being cut off
        heading.setStyleSheet("font-size: 17px; font-weight: bold;")
        layout.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setWordWrap(True)
            sub.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13.5px;")
            layout.addWidget(sub)
        return card, layout

    def _switch_row(self, title: str, hint: str, key: str | None, on: bool, pill: str = "",
                    fixed: bool = False) -> QHBoxLayout:
        switch = self._switch_factory()
        switch.setChecked(on)
        if fixed:
            switch.setEnabled(False)
            switch.setCursor(Qt.CursorShape.ArrowCursor)
        if key is not None:
            self.switches[key] = switch
        name = QLabel(title)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16px; font-weight: 600;")
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(name, 1)  # the title keeps the whole width: one line
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addLayout(head)
        note = QLabel(hint)
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        if pill:
            # The badge sits behind the description, so it does not take room from the title.
            badge = QLabel(pill)
            badge.setStyleSheet("background: #3A3A41; color: #AEAEB2; font-size: 12px; font-weight: bold; "
                                "border-radius: 11px; padding: 0px 10px;")
            badge.setFixedHeight(22)
            line = QHBoxLayout()
            line.setSpacing(10)
            line.addWidget(note, 1)
            line.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            texts.addLayout(line)
        else:
            texts.addWidget(note)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        return row

    def _ceiling_card(self) -> QFrame:
        card, layout = self._card("Höchste Lautstärke (nur Eltern)")
        layout.addWidget(self.ceiling)
        layout.addLayout(self._switch_row(
            "Limiter auf die Summe", "immer an · gegen Kratzen bei vielen Loops",
            None, True, fixed=True))
        box = QFrame()
        box.setObjectName("honesty")
        box.setStyleSheet("#honesty { background: rgba(255, 159, 10, 23); border: 1.5px solid "
                          "rgba(255, 159, 10, 102); border-radius: 12px; }")
        inner = QHBoxLayout(box)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(12)
        inner.addWidget(WarnIcon(ACCENT_ORANGE, 24), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(HONESTY_TITLE)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        body = QLabel(HONESTY_TEXT)
        body.setWordWrap(True)
        body.setStyleSheet("color: #C7C7CC; font-size: 12.5px;")
        texts.addWidget(title)
        texts.addWidget(body)
        inner.addLayout(texts, 1)
        layout.addWidget(box)
        return card

    def _input_card(self, values: dict[str, Any]) -> QFrame:
        card, layout = self._card("Mikrofon")
        layout.addWidget(self.meter)
        heading = QLabel("Trim (Reserve statt „so laut wie möglich“)")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(heading)
        layout.addWidget(self.trim)
        layout.addLayout(self._switch_row(
            "Soft-Clip am Eingang", "immer an · ersetzt keine Reserve",
            None, True, fixed=True))
        layout.addLayout(self._switch_row(
            "Pegel automatisch nachziehen",
            "Standard aus · festes Trim ist vorhersehbarer; schützt nicht vor Übersteuerung am Wandler",
            "auto_gain", values["auto_gain"]))
        layout.addLayout(self._switch_row(
            "Naht weich zeichnen", "gegen Klicks am Loop-Ende · Standard an", "soft_seam",
            values["soft_seam"]))
        layout.addLayout(self._switch_row(
            "Pegelanzeige bei Aufnahme",
            "drei Balken am Pad und die Skala hier · das Warnzeichen bleibt immer",
            "peak_meter", values["peak_meter"]))
        return card

    def _clips_card(self) -> QFrame:
        card, layout = self._card("Zu laut gewesen (nur lokal gemerkt)")
        layout.addWidget(self.clip_list)
        tip = QLabel(CLIP_TIP)
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        layout.addWidget(tip)
        return card

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Bring the scale and the list in line with the controller."""
        controller = self.controller
        level, hold = controller.meter_levels()
        self.meter.setEnabled(controller.peak_meter)
        self.meter.set_state(level, hold, controller.input_clipping())
        self.clip_list.set_events(controller.clip_events())
        # The ceiling may have been set elsewhere (the file); the slider follows it.
        if not self.ceiling._dragging:
            self.ceiling.set_value(controller.max_level_db)
