"""Erweitert page of the parents' area (mockups 11 and 13, plan 3.2).

One loop as a waveform on the beat lines of the session grid, with markers the
parents set (a click on the wave, "Marker setzen") and a stretch between them
that moves each marker to its beat; the parents' tempo and time signature (they
win over what recordings would set, plan 2.2 rule 8) and a visual metronome at
the real grid with an optional quiet tick.
The page owns no state: it reads and sets the controller. The child's page
gets nothing from it except the pulse it already has (plan 3.3).
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QIcon, QPainter, QPaintEvent, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation.config import SIGNATURES
from loopstation.controller import Controller
from loopstation.gui.grid_panel import NO_GRID_HINT, GridPanel, format_seconds
from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT, _IconLabel
from loopstation.gui.settings_page import ToggleSwitch
from loopstation.gui.waveform import WaveformWidget
from loopstation.gui.widgets import ACCENT_GRAY, BACKGROUND, TEXT, TEXT_DIM, BigButton

STRETCH_HINT = "Zwischen Markern strecken: nur bei knapper Abweichung (unter 10 %)"
REFRESH_MS = 40  # the metronome strip follows the grid this often
CHIP_FILL = "#2F3550"
DEFAULT_BPM = 96
# Pad chip colours (mockup 13): empty, has a sound, plays or loops, recording.
CHIP_COLORS = {"white": "#F2F2F2", "yellow": "#FFD60A", "green": "#32D74B", "red": "#FF453A"}
CHIP_TEXT = "#111114"


def loop_title(pad: int, recorded: int | None, played: int | None, grid: int | None, rate: int) -> str:
    """Heading of the waveform card: pad, recorded length, bars, and how it sits on the grid."""
    if recorded is None or played is None:
        return f"Pad {pad + 1} · noch kein Loop"
    parts = [f"Pad {pad + 1}", f"Aufnahme {format_seconds(recorded / rate)}"]
    if grid is None:
        parts.append("freie Länge")
    else:
        bars = max(1, round(played / grid))
        parts.append("1 Takt" if bars == 1 else f"{bars} Takte")
        parts.append("im Raster" if recorded == played else "wird ans Raster angepasst")
    return " · ".join(parts)


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


class AdvancedDialog(QDialog):
    """Waveform of a loop, the parents' tempo and the metronome (parents only)."""

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.pad = next((p for p in range(controller.pad_count) if controller.pad(p).sample), 0)
        self._shown_key: object = None
        self.setWindowTitle("Erweitert")
        self.setModal(True)
        self.setStyleSheet(
            f"AdvancedDialog {{ background: {BACKGROUND.name()}; border: 5px solid {PARENT_ACCENT}; }} "
            "QScrollArea, #advanced_inner { background: transparent; border: none; } "
            f"QLabel {{ color: {TEXT.name()}; font-size: 16px; }} "
            "#card { background: #1B1B1F; border: 1px solid #2C2C31; border-radius: 18px; } "
            "QPushButton#step { color: #F2F2F2; background: #26262B; border: none; border-radius: 12px; "
            "font-size: 28px; font-weight: 700; min-width: 64px; min-height: 56px; } "
            "QPushButton#chip { color: #F2F2F2; background: #26262B; border: 2px solid transparent; "
            "border-radius: 12px; font-size: 18px; font-weight: 700; min-width: 92px; min-height: 48px; } "
            f"QPushButton#chip:checked {{ background: {CHIP_FILL}; border: 2px solid {PARENT_ACCENT}; }} "
            "QPushButton#primary { color: #111114; background: " + PARENT_ACCENT + "; border: none; "
            "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 48px; padding: 0 22px; } "
            "QPushButton#secondary { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
            "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 48px; padding: 0 22px; } "
            "QPushButton#secondary:disabled { color: #5A5A60; border-color: #2C2C31; } "
            f"QSpinBox {{ color: {TEXT.name()}; background: #26262B; font-size: 26px; font-weight: 800; "
            f"border: 2px solid {PARENT_ACCENT}; border-radius: 12px; padding: 4px 10px; "
            "min-height: 44px; } "
            # The - and + buttons beside the field do the stepping; the spin box keeps no arrows.
            "QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; } "
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; } "
            "QScrollBar::handle:vertical { background: #3A3A41; border-radius: 5px; min-height: 24px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; } "
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")

        # Header: back to the child page, the open lock, the title.
        self.close_button = BigButton("back", "Zur Kinderseite", ACCENT_GRAY)
        self.close_button.setToolTip("Eltern-Modus beenden")
        self.close_button.clicked.connect(self.reject)
        title = QLabel("Elternbereich · Erweitert")
        title.setStyleSheet("font-size: 34px; font-weight: bold;")
        subtitle = QLabel("Einen Loop ansehen · Tempo und Taktart korrigieren · Metronom")
        subtitle.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 15px;")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header = QHBoxLayout()
        header.setSpacing(24)
        header.addWidget(self.close_button)
        header.addWidget(_IconLabel("unlock", PARENT_ACCENT, 40))
        header.addLayout(title_box, 1)

        self.grid_panel = GridPanel(controller)
        inner = QWidget()
        inner.setObjectName("advanced_inner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(14)
        inner_layout.addWidget(self.grid_panel)
        inner_layout.addWidget(self._wave_card())
        columns = QHBoxLayout()
        columns.setSpacing(20)
        columns.addWidget(self._tempo_card(), 1)
        columns.addWidget(self._metronome_card(), 1)
        inner_layout.addLayout(columns)
        inner_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        self.resize(1280, 800)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ----------------------------------------------------------- building

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        return card

    @staticmethod
    def _heading(text: str, size: int = 15) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: {size}px; font-weight: bold;")
        return label

    @staticmethod
    def _dim(text: str, size: int = 13) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: {size}px;")
        return label

    def _wave_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        picker = QHBoxLayout()
        picker.setSpacing(8)
        picker.addWidget(self._dim("Pad wählen", 14))
        self.pad_chips: list[QPushButton] = []
        for pad in range(self.controller.pad_count):
            chip = QPushButton(str(pad + 1))
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedSize(60, 40)
            chip.clicked.connect(lambda _checked=False, p=pad: self.choose_pad(p))
            self.pad_chips.append(chip)
            picker.addWidget(chip)
        picker.addStretch(1)
        layout.addLayout(picker)
        self.wave_title = self._heading("", 19)
        layout.addWidget(self.wave_title)
        self.waveform = WaveformWidget()
        layout.addWidget(self.waveform)
        self.waveform.selection_changed.connect(self._update_marker_buttons)
        layout.addLayout(self._marker_row())
        self.marker_status = self._dim(STRETCH_HINT, 13.5)
        layout.addWidget(self.marker_status)
        layout.addWidget(self._dim(
            "Bewusst keine Zeitachse, keine Spuren, keine Automation: die Pads bleiben die Ansicht."))
        return card

    def _marker_row(self) -> QHBoxLayout:
        """Marker setzen / löschen, Anhören and the stretch between the markers (mockup 13)."""
        row = QHBoxLayout()
        row.setSpacing(10)
        self.marker_add = QPushButton("Marker setzen")
        self.marker_add.setToolTip("Erst auf die Wellenform klicken, dann hier setzen")
        self.marker_add.clicked.connect(self.place_marker)
        self.marker_delete = QPushButton("Marker löschen")
        self.marker_delete.setToolTip("Erst einen Marker anklicken")
        self.marker_delete.clicked.connect(self.delete_marker)
        self.listen_button = QPushButton(" Anhören")
        pixmap = QPixmap(30, 30)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        draw_icon(painter, "play", QRectF(0, 0, 30, 30), QColor("#F2F2F2"))
        painter.end()
        self.listen_button.setIcon(QIcon(pixmap))
        self.listen_button.clicked.connect(self.listen)
        self.stretch_button = QPushButton("Zwischen Markern strecken")
        self.stretch_button.setToolTip("Nur bei knapper Abweichung (unter 10 %); Zurück nimmt es zurück")
        self.stretch_button.clicked.connect(self.stretch_markers)
        for button in (self.marker_add, self.marker_delete, self.listen_button, self.stretch_button):
            button.setObjectName("secondary")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.marker_add)
        row.addWidget(self.marker_delete)
        row.addWidget(self.listen_button)
        row.addStretch(1)
        row.addWidget(self.stretch_button)
        return row

    # --------------------------------------------------------------- markers

    def _hint_marker(self) -> None:
        self.marker_status.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13.5px;")
        self.marker_status.setText(STRETCH_HINT)

    def _say_marker(self, text: str, error: bool = False) -> None:
        color = "#FF9F0A" if error else "#32D74B"
        self.marker_status.setStyleSheet(f"color: {color}; font-size: 13.5px; font-weight: bold;")
        self.marker_status.setText(text)

    def place_marker(self) -> bool:
        """"Marker setzen": a marker where the cursor stands."""
        frame = self.waveform.cursor_frame
        if frame is None or not self.controller.add_marker(self.pad, frame):
            return False
        self.waveform.clear_selection()
        self._hint_marker()
        self.refresh()
        return True

    def delete_marker(self) -> bool:
        """"Marker löschen": the selected marker goes."""
        index = self.waveform.selected_marker
        if index is None or not self.controller.remove_marker(self.pad, self.waveform.markers[index]):
            return False
        self.waveform.clear_selection()
        self._hint_marker()
        self.refresh()
        return True

    def listen(self) -> None:
        """"Anhören": the loop once, as it is on the pad."""
        sample = self.controller.pad(self.pad).sample
        if sample is not None:
            self.controller.preview(sample)

    def stretch_markers(self) -> bool:
        """"Zwischen Markern strecken": the markers move to their beats; the page says why if not."""
        refusal = self.controller.stretch_to_markers(self.pad)
        if refusal is not None:
            self._say_marker(refusal, error=True)
            return False
        self.waveform.clear_selection()
        self._say_marker("Gestreckt. Der Loop davor liegt im Verlauf, Zurück bringt ihn wieder.")
        self.refresh()
        return True

    def _update_marker_buttons(self) -> None:
        controller = self.controller
        has_sound = controller.pad(self.pad).sample is not None
        self.marker_add.setEnabled(self.waveform.cursor_frame is not None)
        self.marker_delete.setEnabled(self.waveform.selected_marker is not None)
        self.listen_button.setEnabled(has_sound)
        self.stretch_button.setEnabled(
            has_sound and controller.grid_info() is not None and bool(self.waveform.markers))

    def _tempo_card(self) -> QFrame:
        controller = self.controller
        low, high = controller.bpm_range()
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addWidget(self._heading("Takt korrigieren (Eltern-BPM)", 19))
        layout.addWidget(self._dim("Vorrang vor gemessenem Takt (Regel 8)", 13.5))
        layout.addWidget(self._heading("Tempo"))
        row = QHBoxLayout()
        row.setSpacing(10)
        minus, plus = QPushButton("−"), QPushButton("+")
        for button in (minus, plus):
            button.setObjectName("step")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(round(low), round(high))
        self.bpm_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bpm_spin.setFixedWidth(140)
        minus.clicked.connect(lambda: self.bpm_spin.stepDown())
        plus.clicked.connect(lambda: self.bpm_spin.stepUp())
        row.addWidget(minus)
        row.addWidget(self.bpm_spin)
        row.addWidget(plus)
        row.addWidget(self._dim(f"BPM ({round(low)}-{round(high)})", 14), 1)
        layout.addLayout(row)
        layout.addSpacing(6)
        layout.addWidget(self._heading("Taktart"))
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
        self.apply_button.clicked.connect(self.apply_parent_grid)
        self.measured_button = QPushButton("Gemessenen Takt")
        self.measured_button.setObjectName("secondary")
        self.measured_button.clicked.connect(self.use_measured_grid)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.measured_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.tempo_status = self._dim("", 13.5)
        self._tempo_refused = False
        layout.addWidget(self.tempo_status)
        layout.addWidget(self._dim(NO_GRID_HINT))
        layout.addStretch(1)
        self._load_tempo_inputs()
        return card

    def _metronome_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(self._heading("Metronom", 19))
        layout.addWidget(self._dim("Am echten Takt der Sitzung. Die Kinderseite zeigt nur den Puls.", 13.5))
        self.strip = MetronomeStrip()
        layout.addWidget(self.strip)
        self.period_label = self._dim("", 14)
        layout.addWidget(self.period_label)
        self.tone_switch = ToggleSwitch()
        self.tone_switch.setChecked(self.controller.settings.metronome_tone)
        self.tone_switch.toggled.connect(self.set_tone)
        name = QLabel("Metronom-Ton (leise)")
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(self._dim("Gilt jetzt; dauerhaft mit »Speichern« in den Einstellungen. "
                                  "Läuft durch Lautstärke und Obergrenze."))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self.tone_switch)
        row.addLayout(texts, 1)
        layout.addLayout(row)
        layout.addStretch(1)
        return card

    # ------------------------------------------------------------- actions

    def choose_pad(self, pad: int) -> None:
        """Show the loop on ``pad``."""
        self.pad = pad
        self.waveform.clear_selection()
        self._hint_marker()
        self.refresh()

    def _load_tempo_inputs(self) -> None:
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
            self._load_tempo_inputs()
        self.refresh()
        return ok

    def set_tone(self, on: bool) -> None:
        """Switch the quiet metronome tick for now (the file keeps its value until saved)."""
        settings = self.controller.settings
        if settings.metronome_tone != on:
            self.controller.apply_settings(replace(settings, metronome_tone=on))

    # ------------------------------------------------------------- refresh

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._timer.start(REFRESH_MS)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        controller = self.controller
        self.grid_panel.refresh()
        colors = controller.pad_colors()
        for pad, chip in enumerate(self.pad_chips):
            chip.setChecked(pad == self.pad)
            border = "3px solid #FFFFFF" if pad == self.pad else "3px solid transparent"
            chip.setStyleSheet(
                f"QPushButton {{ color: {CHIP_TEXT}; background: {CHIP_COLORS[colors[pad]]}; "
                f"border: {border}; border-radius: 10px; font-size: 16px; font-weight: 800; }}")
        self._show_loop()
        self._update_marker_buttons()
        info = controller.grid_info()
        position = controller.beat_position()
        period = controller.metronome_period()
        self.strip.set_state(
            None if info is None else info.beats,
            None if position is None else int(position),
        )
        self.period_label.setText(
            "" if period is None or info is None
            else f"{round(info.bpm)} BPM · ein Schlag alle {format_seconds(period)}")
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

    def _show_loop(self) -> None:
        """Redraw the waveform only when the loop, the grid or the pad changed."""
        controller = self.controller
        sample = controller.pad(self.pad).sample
        grid = controller.grid_frames()
        info = controller.grid_info()
        marks = controller.markers(self.pad)
        key = (self.pad, sample, grid, None if info is None else info.beats, tuple(marks))
        if key == self._shown_key:
            return
        self._shown_key = key
        if sample is None:
            self.waveform.set_loop(None, grid, 4)
            self.waveform.set_markers([])
            self.wave_title.setText(loop_title(self.pad, None, None, grid, controller.sample_rate))
            return
        played = controller.loop_audio(sample)
        recorded = controller.sample_audio(sample)
        if played is None or recorded is None:
            self.waveform.set_loop(None, grid, 4)
            self.waveform.set_markers([])
            self.wave_title.setText(loop_title(self.pad, None, None, grid, controller.sample_rate))
            return
        self.waveform.set_loop(played, grid, 4 if info is None else info.beats)
        self.waveform.set_markers([m for m in marks if m < len(played)])
        self.wave_title.setText(
            loop_title(self.pad, len(recorded), len(played), grid, controller.sample_rate))
