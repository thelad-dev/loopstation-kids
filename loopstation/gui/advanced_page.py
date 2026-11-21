"""Erweitert area of the parents' area (mockup 13, plan 3.2).

One loop as a waveform on the beat lines of the session grid, with markers the parents set (a click on
the wave, "Marker setzen") and a stretch between them that moves each marker to its beat, and a card that
saves this loop as WAV. The tempo correction and the metronome are on the "Takt & Loop" area
(``tempo_card``). The page owns no state: it reads and sets the controller. The child's page gets
nothing from it (plan 3.3).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QIcon, QPainter, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller
from loopstation.gui.export_dialog import CUE_TITLE, default_export_dir, save_loop
from loopstation.gui.grid_panel import format_seconds
from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import PAGE_STYLE, CardGrid, dim_label, scrolled
from loopstation.gui.settings_panels import ToggleSwitch
from loopstation.gui.trim_card import TrimCard
from loopstation.gui.waveform import WaveformWidget
from loopstation.gui.widgets import TEXT_DIM, BigButton, weak_slot

STRETCH_HINT = "Zwischen Markern strecken: jeder Marker wandert auf seinen Schlag, Zurück nimmt es zurück"
REFRESH_MS = 100  # the waveform follows the controller this often (it redraws only when something changed)
CHIP_FILL = "#2F3550"
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


class AdvancedPage(QWidget):
    """Waveform of a loop, markers and the single-loop export (parents only)."""

    def __init__(
        self,
        controller: Controller,
        parent: QWidget | None = None,
        export_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.export_dir = export_dir if export_dir is not None else default_export_dir()
        self._clock = clock
        self.last_path: Path | None = None
        self.pad = next((p for p in range(controller.pad_count) if controller.pad(p).sample), 0)
        self._shown_key: object = None
        self.setWindowTitle("Erweitert")
        self.setStyleSheet(
            PAGE_STYLE
            + "QPushButton#secondary { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
            "border-radius: 12px; font-size: 15px; font-weight: 700; min-height: 48px; padding: 0 8px; } "
            "QPushButton#secondary:disabled { color: #5A5A60; border-color: #2C2C31; } "
            "QRadioButton::indicator { width: 18px; height: 18px; border-radius: 11px; "
            "border: 2px solid #6E6E75; background: #1B1B1F; } "
            f"QRadioButton::indicator:checked {{ border: 2px solid {PARENT_ACCENT}; "
            "background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, "
            f"stop:0 {PARENT_ACCENT}, stop:0.55 {PARENT_ACCENT}, stop:0.6 #1B1B1F, stop:1 #1B1B1F); }} ")

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(14)
        inner_layout.addLayout(self._picker())
        inner_layout.addWidget(self._wave_card())
        self.trim_card = TrimCard(controller, self.waveform, lambda: self.pad, on_done=self.refresh)
        inner_layout.addWidget(self.trim_card)
        inner_layout.addWidget(self._export_card())
        inner_layout.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scrolled(inner))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ----------------------------------------------------------- building

    @staticmethod
    def _heading(text: str, size: int = 15) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)  # the page lives in a narrow side panel
        label.setStyleSheet(f"font-size: {size}px; font-weight: bold;")
        return label

    @staticmethod
    def _dim(text: str, size: float = 13) -> QLabel:
        return dim_label(text, size)

    def _picker(self) -> QHBoxLayout:
        """"Pad wählen" and one chip per pad, coloured like the pads."""
        picker = QHBoxLayout()
        picker.setSpacing(10)
        label = QLabel("Pad wählen")
        label.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px; font-weight: bold;")
        self.picker_label = label
        picker.addWidget(label)
        self.pad_chips: list[QPushButton] = []
        for pad in range(self.controller.pad_count):
            chip = QPushButton(str(pad + 1))
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setMinimumWidth(34)
            chip.setMaximumWidth(60)
            chip.setFixedHeight(40)
            chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            chip.clicked.connect(weak_slot(self.choose_pad, pad))
            self.pad_chips.append(chip)
            picker.addWidget(chip, 1)
        picker.addStretch(0)
        return picker

    def _wave_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 14, 22, 18)
        layout.setSpacing(8)
        self.wave_title = self._heading("", 19)
        layout.addWidget(self.wave_title)
        self.waveform = WaveformWidget()
        layout.addWidget(self.waveform)
        self.waveform.selection_changed.connect(self._update_marker_buttons)
        layout.addWidget(self._marker_row())
        layout.addWidget(self._snap_row())
        self.marker_status = self._dim(STRETCH_HINT, 13.5)
        layout.addWidget(self.marker_status)
        layout.addWidget(self._dim(
            "Bewusst keine Zeitachse, keine Spuren, keine Automation: die Pads bleiben die Ansicht."))
        return card

    def _marker_row(self) -> QWidget:
        """Marker setzen / löschen, Anhören and the stretch between the markers (mockup 13)."""
        self.marker_add = QPushButton("Marker setzen")
        self.marker_add.setToolTip("Erst auf die Wellenform klicken, dann hier setzen")
        self.marker_add.clicked.connect(weak_slot(self.place_marker))
        self.marker_delete = QPushButton("Marker löschen")
        self.marker_delete.setToolTip("Erst einen Marker anklicken")
        self.marker_delete.clicked.connect(weak_slot(self.delete_marker))
        self.listen_button = QPushButton(" Anhören")
        pixmap = QPixmap(30, 30)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        draw_icon(painter, "play", QRectF(0, 0, 30, 30), QColor("#F2F2F2"))
        painter.end()
        self.listen_button.setIcon(QIcon(pixmap))
        self.listen_button.clicked.connect(weak_slot(self.listen))
        self.stretch_button = QPushButton("Zwischen Markern strecken")
        self.stretch_button.setToolTip("Jeder Marker wandert auf seinen Schlag; Zurück nimmt es zurück")
        self.stretch_button.clicked.connect(weak_slot(self.stretch_markers))
        for button in (self.marker_add, self.marker_delete, self.listen_button, self.stretch_button):
            button.setObjectName("secondary")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Rows of two: the page lives in a side panel next to the pads.
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self.marker_add, 0, 0)
        grid.addWidget(self.marker_delete, 0, 1)
        grid.addWidget(self.listen_button, 1, 0)
        grid.addWidget(self.stretch_button, 2, 0, 1, 2)  # the longest word gets the whole row
        for button in (self.marker_add, self.marker_delete, self.listen_button, self.stretch_button):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return holder

    def _snap_row(self) -> QWidget:
        """Switch: a marker snaps to the nearest real transient when it is set (mockup 13)."""
        self.snap_switch = ToggleSwitch()
        self.snap_switch.setChecked(self.controller.settings.snap_markers)
        self.snap_switch.toggled.connect(weak_slot(self.set_snap_markers, pass_signal_args=True))
        name = QLabel("Marker auf Transiente einrasten")
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(self._dim(
            "rastet auf den nächsten Schlag in der Nähe ein; ohne Schlag bleibt der Marker, wo er ist"))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self.snap_switch, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        widget = QWidget()
        widget.setLayout(row)
        return widget

    def _export_card(self) -> QFrame:
        """"Diesen Loop exportieren": the loop of the chosen pad as WAV (the logic of the Export area)."""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addWidget(self._heading("Diesen Loop exportieren", 19))
        layout.addWidget(self._dim("Lokal auf diesem Rechner · kein Upload, kein Teilen", 13.5))
        layout.addWidget(self._heading("Format"))
        wav = QRadioButton("WAV")
        wav.setChecked(True)
        wav.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        wav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        wav.setStyleSheet("font-size: 15.5px; font-weight: bold;")
        wav_hint = self._dim("unverändert, Standard")
        wav_hint.setContentsMargins(26, 0, 0, 0)
        format_box = QVBoxLayout()
        format_box.setSpacing(0)
        format_box.addWidget(wav)
        format_box.addWidget(wav_hint)
        self.cue_switch = ToggleSwitch()
        self.cue_switch.setChecked(self.controller.settings.export_cue_points)
        self.cue_switch.toggled.connect(weak_slot(self.set_cue_points, pass_signal_args=True))
        cue_name = QLabel(CUE_TITLE)
        cue_name.setWordWrap(True)
        cue_name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        cue_texts = QVBoxLayout()
        cue_texts.setSpacing(0)
        cue_texts.addWidget(cue_name)
        cue_texts.addWidget(self._dim("wenn das Format es zuverlässig kann (sonst Begleitdatei)"))
        cue_row = QHBoxLayout()
        cue_row.setSpacing(16)
        cue_row.addWidget(self.cue_switch, 0, Qt.AlignmentFlag.AlignTop)
        cue_row.addLayout(cue_texts, 1)
        format_widget, cue_widget = QWidget(), QWidget()
        format_widget.setLayout(format_box)
        cue_widget.setLayout(cue_row)
        layout.addWidget(CardGrid([[format_widget, cue_widget]], ratio=(1, 1), gap=20, spacing=8))
        self.target_label = self._dim("")
        layout.addWidget(self.target_label)
        self.loop_message = QLabel("")
        self.loop_message.setWordWrap(True)
        layout.addWidget(self.loop_message)
        self.save_button = BigButton("download", "Als WAV sichern", QColor(PARENT_ACCENT), checkable=True,
                                     min_height=56, font_pt=13)
        self.save_button.setChecked(True)  # filled: the one main action
        self.save_button.clicked.connect(weak_slot(self._save_clicked))
        layout.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignRight)
        return card

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
        if frame is None:
            return False
        if not self.controller.add_marker(self.pad, self.controller.snap_marker(self.pad, frame)):
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

    # ------------------------------------------------------------- the loop export

    def _stamp(self) -> str:
        return time.strftime("%Y-%m-%d_%H%M", time.localtime(self._clock()))

    def set_cue_points(self, on: bool) -> None:
        """Take the markers into the saved loop (until the settings file is saved with another value)."""
        settings = self.controller.settings
        if settings.export_cue_points != on:
            self.controller.apply_settings(replace(settings, export_cue_points=on))

    def set_snap_markers(self, on: bool) -> None:
        """Snap new markers to transients (until the settings file is saved with another value)."""
        settings = self.controller.settings
        if settings.snap_markers != on:
            self.controller.apply_settings(replace(settings, snap_markers=on))

    def _save_clicked(self) -> None:
        self.save_button.setChecked(True)  # keep it filled after the click toggled it
        self.export_loop()

    def export_loop(self) -> Path | None:
        """Write the loop of the shown pad as WAV; the path, or None (the reason is shown)."""
        path, text, error = save_loop(self.controller, self.pad, self.export_dir, self._stamp())
        color = "#FF3B30" if error else "#32D74B"
        self.loop_message.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.loop_message.setText(text)
        if path is not None:
            self.last_path = path
        return path

    # ------------------------------------------------------------- actions

    def set_picker_visible(self, visible: bool) -> None:
        """Show or hide "Pad wählen" (the side panel "Loop" follows the pad chosen in the parents' view)."""
        self.picker_label.setVisible(visible)
        for chip in self.pad_chips:
            chip.setVisible(visible)

    def choose_pad(self, pad: int) -> None:
        """Show the loop on ``pad``."""
        self.pad = pad
        self.waveform.clear_selection()
        self._hint_marker()
        self.trim_card.say("")
        self.refresh()

    # ------------------------------------------------------------- refresh

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._timer.start(REFRESH_MS)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        controller = self.controller
        colors = controller.pad_colors()
        for pad, chip in enumerate(self.pad_chips):
            chip.setChecked(pad == self.pad)
            border = "3px solid #FFFFFF" if pad == self.pad else "3px solid transparent"
            chip.setStyleSheet(
                f"QPushButton {{ color: {CHIP_TEXT}; background: {CHIP_COLORS[colors[pad]]}; "
                f"border: {border}; border-radius: 10px; font-size: 16px; font-weight: 800; }}")
        self._show_loop()
        self._update_marker_buttons()
        self.trim_card.refresh()
        stamp = self._stamp()
        self.target_label.setText(f"Ziel: {self.export_dir / f'pad{self.pad + 1:02d}_{stamp}.wav'}")
        self.save_button.setEnabled(controller.pad(self.pad).sample is not None)

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
        played = controller.loop_audio(sample, self.pad)
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


# The page used to be a dialog of its own; the name stays for code that still imports it.
AdvancedDialog = AdvancedPage
