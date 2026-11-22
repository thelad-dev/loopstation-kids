"""Tempo and metronome cards of the "Takt & Loop" area (mockup 11, plan 2.2 rule 8 and 13).

``TempoCard`` is the parents' correction of the session grid (tempo and time signature win over what
recordings would set); ``MetronomeCard`` shows the beats of the real grid. Both own no state: they read
and set the controller.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation.config import SIGNATURES
from loopstation.controller import Controller
from loopstation.gui.grid_panel import NO_GRID_HINT, format_seconds
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import dim_label
from loopstation.gui.widgets import TEXT, TEXT_DIM, weak_slot

REFRESH_MS = 40  # the metronome strip follows the grid this often
CHIP_FILL = "#2F3550"
CHIP_TEXT = "#111114"
DEFAULT_BPM = 96

CARD_STYLE = (
    "QPushButton#step { color: #F2F2F2; background: #26262B; border: none; border-radius: 12px; "
    "font-size: 28px; font-weight: 700; min-width: 64px; min-height: 56px; } "
    "QPushButton#chip { color: #F2F2F2; background: #26262B; border: 2px solid transparent; "
    "border-radius: 12px; font-size: 18px; font-weight: 700; min-width: 64px; min-height: 48px; } "
    f"QPushButton#chip:checked {{ background: {CHIP_FILL}; border: 2px solid {PARENT_ACCENT}; }} "
    f"QPushButton#primary {{ color: #111114; background: {PARENT_ACCENT}; border: none; "
    "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 48px; padding: 0 22px; } "
    "QPushButton#secondary { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
    "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 48px; padding: 0 22px; } "
    "QPushButton#secondary:disabled { color: #5A5A60; border-color: #2C2C31; } "
    f"QSpinBox {{ color: {TEXT.name()}; background: #26262B; font-size: 26px; font-weight: 800; "
    f"border: 2px solid {PARENT_ACCENT}; border-radius: 12px; padding: 4px 10px; min-height: 44px; }} "
    # The - and + buttons beside the field do the stepping; the spin box keeps no arrows.
    "QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; } "
)


def _heading(text: str, size: int = 15) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: {size}px; font-weight: bold;")
    return label


class MetronomeStrip(QWidget):
    """The beats of one bar: the current one filled, the first one square (colour and shape)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(72)
        self.beats: int | None = None
        self.active: int | None = None

    def set_state(self, beats: int | None, active: int | None) -> None:
        if (beats, active) != (self.beats, self.active):
            self.beats, self.active = beats, active
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(320, 72)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(120, 72)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.beats:
            painter.setPen(TEXT_DIM)
            painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "Kein Takt - kein Metronom")
            painter.end()
            return
        size = min(52.0, self.height() - 12.0, self.width() / self.beats - 14.0)
        slot = self.width() / self.beats
        accent = QColor(PARENT_ACCENT)
        for beat in range(self.beats):
            box = QRectF(slot * (beat + 0.5) - size / 2, (self.height() - size) / 2, size, size)
            on = beat == self.active
            painter.setPen(QPen(accent if on else QColor("#6E6E75"), 3))
            painter.setBrush(accent if on else Qt.BrushStyle.NoBrush)
            if beat == 0:
                painter.drawRoundedRect(box, size * 0.18, size * 0.18)
            else:
                painter.drawEllipse(box)
            painter.setPen(QColor(CHIP_TEXT if on else "#C7C7CC"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(beat + 1))
        painter.end()


class TempoCard(QFrame):
    """"Takt korrigieren (Eltern-BPM)": tempo, time signature, "Übernehmen" and "Gemessenen Takt"."""

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("card")
        self.setStyleSheet(CARD_STYLE)
        low, high = controller.bpm_range()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        head = QLabel("Takt korrigieren (Eltern-BPM)")
        head.setWordWrap(True)
        head.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(head)
        layout.addWidget(dim_label("Hat Vorrang vor dem gemessenen Takt", 13.5))
        layout.addWidget(_heading("Tempo"))
        row = QHBoxLayout()
        row.setSpacing(10)
        minus, plus = QPushButton("−"), QPushButton("+")
        for button in (minus, plus):
            button.setObjectName("step")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(round(low), round(high))
        self.bpm_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bpm_spin.setFixedWidth(120)
        minus.clicked.connect(self.bpm_spin.stepDown)
        plus.clicked.connect(self.bpm_spin.stepUp)
        row.addWidget(minus)
        row.addWidget(self.bpm_spin)
        row.addWidget(plus)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(dim_label(f"BPM ({round(low)}-{round(high)})", 14))
        layout.addSpacing(6)
        layout.addWidget(_heading("Taktart"))
        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.signature_group = QButtonGroup(self)
        self.signature_group.setExclusive(True)
        self.signature_chips: dict[str, QPushButton] = {}
        for signature in SIGNATURES:
            chip = QPushButton(signature)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.signature_group.addButton(chip)
            self.signature_chips[signature] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        layout.addLayout(chips)
        layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.apply_button = QPushButton("Übernehmen")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(weak_slot(self.apply_parent_grid))
        self.measured_button = QPushButton("Gemessenen Takt")
        self.measured_button.setObjectName("secondary")
        self.measured_button.clicked.connect(weak_slot(self.use_measured_grid))
        for button in (self.apply_button, self.measured_button):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            buttons.addWidget(button, 1)
        layout.addLayout(buttons)
        self.tempo_status = dim_label("", 13.5)
        self._tempo_refused = False
        layout.addWidget(self.tempo_status)
        layout.addWidget(dim_label(NO_GRID_HINT))
        layout.addStretch(1)
        self._load_inputs()
        self.refresh()

    def _load_inputs(self) -> None:
        """Start the inputs from the running grid, else from what the parents set, else a calm default."""
        controller = self.controller
        info = controller.grid_info()
        pending = controller.parent_grid()
        if info is not None:
            bpm, signature = info.bpm, info.signature
        elif pending is not None:
            bpm, signature = pending
        else:
            bpm, signature = DEFAULT_BPM, controller.settings.time_signature
        low, high = controller.bpm_range()
        self.bpm_spin.setValue(round(min(high, max(low, bpm))))
        self.signature_chips[signature].setChecked(True)

    @property
    def signature(self) -> str:
        return next(name for name, chip in self.signature_chips.items() if chip.isChecked())

    def apply_parent_grid(self) -> bool:
        """"Übernehmen": the tempo and time signature become the session grid."""
        ok = self.controller.set_parent_grid(float(self.bpm_spin.value()), self.signature)
        self._tempo_refused = not ok
        if not ok:
            self.tempo_status.setText(
                "Das geht gerade nicht: »Loops im Takt halten« muss an sein, und es darf keine "
                "Aufnahme laufen.")
        self.refresh()
        return ok

    def use_measured_grid(self) -> bool:
        """"Gemessenen Takt": the recordings decide the grid again."""
        ok = self.controller.use_measured_grid()
        if ok:
            self._tempo_refused = False
            self._load_inputs()
        self.refresh()
        return ok

    def refresh(self) -> None:
        controller = self.controller
        info = controller.grid_info()
        pending = controller.parent_grid()
        if self._tempo_refused and controller.settings.loop_sync and controller.recording_pad is None:
            self._tempo_refused = False
        self.measured_button.setEnabled(pending is not None)
        if pending is not None:
            bpm, signature = pending
            suffix = "" if info is not None else " · gilt ab der nächsten ersten Aufnahme"
            self.tempo_status.setText(f"Vorgegeben: {round(bpm)} BPM · {signature}{suffix}")
        elif not self._tempo_refused:
            self.tempo_status.setText("")


class MetronomeCard(QFrame):
    """"Metronom": the beats of the real grid, the current one lit (the quiet tick is a switch elsewhere)."""

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        head = QLabel("Metronom")
        head.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(head)
        layout.addWidget(dim_label("Am echten Takt der Sitzung. Die Kinderseite zeigt nur den Puls.", 13.5))
        self.strip = MetronomeStrip()
        layout.addWidget(self.strip)
        self.period_label = dim_label("", 14)
        layout.addWidget(self.period_label)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._timer.start(REFRESH_MS)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        controller = self.controller
        info = controller.grid_info()
        position = controller.beat_position()
        period = controller.metronome_period()
        self.strip.set_state(
            None if info is None else info.beats, None if position is None else int(position))
        self.period_label.setText(
            "" if period is None or info is None
            else f"{round(info.bpm)} BPM · ein Schlag alle {format_seconds(period)}")
