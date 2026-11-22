"""Export area of the parents' area (mockup 16): the sum over N bars, and single loops.

Only the parents reach it (behind the parental gate); the files stay on this
computer. The page only collects choices and shows them; the rendering and
the checks live in ``loopstation.export``.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation import export as ex
from loopstation.controller import Controller
from loopstation.gui.parent_gate import PARENT_ACCENT, _IconLabel
from loopstation.gui.parent_nav import SCROLLBAR_GAP_QSS, CardColumn, scrolled
from loopstation.gui.settings_panels import ToggleSwitch
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_GREEN,
    DARK_SCROLLBAR_QSS,
    TEXT,
    TEXT_DIM,
    BigButton,
    weak_slot,
)

NBSP = " "
WORD_JOINER = "\u2060"  # no line break here, e.g. after the hyphen of "Cue-Punkte"
CUE_TITLE = f"Marker als Cue-{WORD_JOINER}Punkte mitschreiben"  # also on the panel "System"
CHIP_FILL = "#2F3550"  # selected chip, as in the parents' area mockups
CUSTOM_BARS = 0  # id of the "..." chip: the number comes from the spin box
EXPORT_FOLDER = ("Loopstation", "Export")


def default_export_dir() -> Path:
    """``Documents/Loopstation/Export`` (the Qt standard place, else the home folder)."""
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(documents or Path.home()).joinpath(*EXPORT_FOLDER)


def german_number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def frames_text(frames: int) -> str:
    return f"{frames:,}".replace(",", NBSP)


def rate_text(rate: int) -> str:
    return f"{german_number(rate / 1000, 1).removesuffix(',0')}{NBSP}kHz"


def level_text(db: float) -> str:
    return f"{german_number(db, 0) if db == int(db) else german_number(db, 1)}{NBSP}dBFS"


def unique_path(folder: Path, name: str) -> Path:
    """``folder/name``, or with ``-2``, ``-3`` ... before the extension if that file exists."""
    path = folder / name
    counter = 2
    while path.exists():
        path = folder / f"{Path(name).stem}-{counter}{Path(name).suffix}"
        counter += 1
    return path


def save_loop(
    controller: Controller, pad: int | None, export_dir: Path, stamp: str,
) -> tuple[Path | None, str, bool]:
    """Write the loop of ``pad`` unchanged as WAV into ``export_dir``.

    Returns ``(path, text, is_error)``: the path (None if it could not be made) and the line to show.
    Shared by the Export area and the detail panel of the pads.
    """
    sample = None if pad is None else controller.pad(pad).sample
    data = None if sample is None else controller.sample_audio(sample)
    if pad is None or data is None:
        return None, "Dieses Pad hat keine lesbare Aufnahme.", True
    path = unique_path(export_dir, f"pad{pad + 1:02d}_{stamp}.wav")
    markers = controller.markers(pad) if controller.settings.export_cue_points else []
    try:
        kept = ex.export_loop(path, data, controller.sample_rate, f"Loopstation Pad {pad + 1}", markers)
    except ex.ExportError as exc:
        return None, str(exc), True
    note = {"cue": " (mit Markern als Cue-Punkten)",
            "sidecar": " (Marker als Begleitdatei daneben)"}.get(kept or "", "")
    return path, f"Gespeichert: {path}{note}", False


class PreviewRows(QWidget):
    """Which pads repeat how often over the bars (green = loop, grey = one-shot at the start)."""

    ROW = 52  # each of the first ``ROOMY_ROWS`` rows
    ROOMY_ROWS = 4
    EXTRA_ROW = 26  # each further row adds this much, so the rows get lower but the preview never shrinks
    BLOCK = 28  # height of a pass block in a roomy row
    LABEL_W = 56
    TOP = 14
    BOTTOM = 18  # the bar axis ("Takt 1 ... N") below the rows

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # (label, pass length in bars, one-shot)
        self.rows: list[tuple[str, float, bool]] = []
        self.bars = 8
        self.setMinimumWidth(220)

    def set_rows(self, rows: list[tuple[str, float, bool]], bars: int) -> None:
        self.rows, self.bars = rows, max(1, bars)
        self.setMinimumHeight(self._height())
        self.updateGeometry()
        self.update()

    @property
    def row_height(self) -> float:
        """52 px for up to four rows; beyond that the rows share the room and get lower (towards 26 px)."""
        count = max(1, len(self.rows))
        extra = max(0, count - self.ROOMY_ROWS)
        return (min(count, self.ROOMY_ROWS) * self.ROW + extra * self.EXTRA_ROW) / count

    def _height(self) -> int:
        """Every row and the axis below them: grows with each row, the page scrolls."""
        return self.TOP + math.ceil(max(1, len(self.rows)) * self.row_height) + self.BOTTOM

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.minimumWidth(), self._height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left, right = self.LABEL_W, self.width() - 4
        bar_w = (right - left) / self.bars
        row_h = self.row_height
        block = min(self.BLOCK, row_h - 8)
        bottom = self.TOP + len(self.rows) * row_h
        small = QFont()
        small.setPointSizeF(8.5)
        label = QFont()
        label.setPointSizeF(9.5)
        label.setBold(True)
        for index, (name, length, one_shot) in enumerate(self.rows):
            top = self.TOP + index * row_h
            painter.setFont(label)
            painter.setPen(TEXT)
            painter.drawText(QRectF(0, top, left - 6, block), Qt.AlignmentFlag.AlignVCenter, name)
            painter.setPen(Qt.PenStyle.NoPen)
            color = QColor("#8E8E93" if one_shot else ACCENT_GREEN.name())
            color.setAlphaF(0.85)
            painter.setBrush(color)
            position = 0.0
            while position < self.bars - 1e-9:
                end = min(self.bars, position + length)
                x0 = left + position * bar_w
                painter.drawRoundedRect(QRectF(x0, top, max(2.0, (end - position) * bar_w - 2), block), 6, 6)
                if one_shot:
                    break
                position += length
        for bar in range(self.bars + 1):
            strong = bar in (0, self.bars) or self.bars <= 8
            line = QColor(255, 255, 255, 90 if bar in (0, self.bars) else 30 if strong else 0)
            if line.alpha() == 0:
                continue
            painter.setPen(QPen(line, 1))
            x = left + bar * bar_w
            painter.drawLine(QPointF(x, self.TOP - 8), QPointF(x, bottom - 8))
        painter.setFont(small)
        painter.setPen(TEXT_DIM)
        painter.drawText(QRectF(left, bottom, 80, 18), Qt.AlignmentFlag.AlignLeft, "Takt 1")
        painter.drawText(QRectF(right - 80, bottom, 80, 18), Qt.AlignmentFlag.AlignRight, str(self.bars))
        painter.end()


class ExportPage(QWidget):
    """Export of the sum over N bars and of single loops as WAV (parents only, local files)."""

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
        self.setWindowTitle("Export")
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            + DARK_SCROLLBAR_QSS + SCROLLBAR_GAP_QSS
            + f"QLabel, QRadioButton {{ color: {TEXT.name()}; font-size: 16px; }} "
            "#card { background: #1B1B1F; border: 1px solid #2C2C31; border-radius: 18px; } "
            "#length_box { background: #141418; border-radius: 14px; } "
            "#info_card { background: rgba(127, 167, 255, 23); border: 1px solid rgba(127, 167, 255, 102); "
            "border-radius: 14px; } "
            "QPushButton#chip { color: #F2F2F2; background: #26262B; border: 2px solid transparent; "
            "border-radius: 14px; font-size: 24px; font-weight: 800; min-height: 60px; } "
            f"QPushButton#chip:checked {{ background: {CHIP_FILL}; border: 2px solid {PARENT_ACCENT}; }} "
            "QPushButton#chip:disabled { color: #5A5A60; background: #1F1F23; } "
            "QPushButton#pad_chip { color: #F2F2F2; background: #26262B; border: 2px solid transparent; "
            "border-radius: 10px; font-size: 15px; font-weight: 700; min-width: 40px; min-height: 28px; } "
            f"QPushButton#pad_chip:checked {{ background: {CHIP_FILL}; border: 2px solid {PARENT_ACCENT}; }} "
            "QPushButton#pad_chip:disabled { color: #5A5A60; background: #1F1F23; } "
            "QRadioButton::indicator { width: 18px; height: 18px; border-radius: 11px; "
            "border: 2px solid #6E6E75; background: #1B1B1F; } "
            f"QRadioButton::indicator:checked {{ border: 2px solid {PARENT_ACCENT}; "
            "background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, "
            f"stop:0 {PARENT_ACCENT}, stop:0.55 {PARENT_ACCENT}, stop:0.6 #1B1B1F, stop:1 #1B1B1F); }} "
            f"QSpinBox {{ color: {TEXT.name()}; background: #26262B; font-size: 18px; "
            f"border: 1px solid {PARENT_ACCENT}; border-radius: 10px; padding: 6px 10px; }}")

        right = QWidget()
        right.setLayout(self._right_column())
        right.layout().setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.addWidget(
            CardColumn([self._sum_card(), right], stretch_last=True), 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scrolled(inner))
        self.refresh()

    # ----------------------------------------------------------- building

    @staticmethod
    def _heading(text: str, size: int = 15) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: {size}px; font-weight: bold;")
        return label

    @staticmethod
    def _dim(text: str, size: int = 13) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: {size}px;")
        return label

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        return card

    def _switch_row(self, switch: ToggleSwitch, title: str, hint: QLabel) -> QHBoxLayout:
        name = QLabel(title)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        name.setWordWrap(True)  # a long title wraps instead of widening the page (1024 px)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(hint)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(switch)
        row.addLayout(texts, 1)
        return row

    def _radio(self, text: str, hint: QLabel, checked: bool = False) -> tuple[QRadioButton, QVBoxLayout]:
        radio = QRadioButton(text)
        radio.setChecked(checked)
        radio.setStyleSheet("font-size: 14.5px; font-weight: bold;")
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(radio)
        hint.setContentsMargins(26, 0, 0, 0)
        box.addWidget(hint)
        return radio, box

    def _sum_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addWidget(self._heading("Summe exportieren", 19))
        self.session_label = self._dim("", 13.5)
        layout.addWidget(self.session_label)

        layout.addSpacing(8)
        layout.addWidget(self._heading("Wie viele Takte?"))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.bar_group = QButtonGroup(self)
        self.bar_group.setExclusive(True)
        self.bar_chips: dict[int, QPushButton] = {}
        for bars in (*ex.BAR_CHOICES, CUSTOM_BARS):
            chip = QPushButton(str(bars) if bars else "…")
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            self.bar_group.addButton(chip, bars)
            self.bar_chips[bars] = chip
            chips.addWidget(chip, 1 if bars else 0)
        self.bar_chips[CUSTOM_BARS].setMinimumWidth(60)
        self.bar_chips[8].setChecked(True)
        self.bar_group.idClicked.connect(self._bars_chosen)
        layout.addLayout(chips)

        self.custom_row = QWidget()
        custom = QHBoxLayout(self.custom_row)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.addWidget(QLabel("Eigene Zahl von Takten:"))
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(1, ex.MAX_BARS)
        self.custom_spin.setValue(12)
        self.custom_spin.valueChanged.connect(weak_slot(self.refresh))
        custom.addWidget(self.custom_spin)
        custom.addStretch(1)
        self.custom_row.hide()
        layout.addWidget(self.custom_row)

        length = QFrame()
        length.setObjectName("length_box")
        length_layout = QGridLayout(length)
        length_layout.setContentsMargins(18, 8, 18, 10)
        length_layout.setVerticalSpacing(0)
        length_layout.addWidget(self._dim("Länge"), 0, 0)
        self.length_label = QLabel("")
        self.length_label.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.length_label.setWordWrap(True)
        self.frames_label = self._dim("")
        self.frames_label.setWordWrap(False)
        self.frames_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        length_layout.addWidget(self.length_label, 1, 0)
        length_layout.addWidget(self.frames_label, 2, 0)
        length_layout.setColumnStretch(0, 1)
        layout.addWidget(length)

        layout.addSpacing(6)
        layout.addWidget(self._heading("Welche Pads?"))
        pads = QVBoxLayout()  # one under the other: the page lives in a narrow side panel
        pads.setSpacing(6)
        self.running_count = self._dim("", 12.5)
        self.all_count = self._dim("", 12.5)
        self.scope_running, box = self._radio("Nur was gerade loopt", self.running_count, True)
        pads.addLayout(box, 1)
        self.scope_all, box = self._radio("Alle belegten Pads als Loop", self.all_count)
        pads.addLayout(box, 1)
        group = QButtonGroup(self)
        group.addButton(self.scope_running)
        group.addButton(self.scope_all)
        self.scope_running.toggled.connect(weak_slot(self.refresh))
        layout.addLayout(pads)

        layout.addSpacing(6)
        self.one_shots = ToggleSwitch()
        self.one_shots.toggled.connect(weak_slot(self.refresh))
        layout.addLayout(self._switch_row(
            self.one_shots, "Einmal-Pads am Anfang einrechnen", self._dim("Standard: weglassen")))
        self.fade_out = ToggleSwitch()
        self.fade_out.setChecked(True)
        self.fade_hint = self._dim("")
        layout.addLayout(self._switch_row(self.fade_out, "Kurzer Ausklang am Ende", self.fade_hint))
        self.stand_in = ToggleSwitch()
        self.stand_in.toggled.connect(weak_slot(self.refresh))
        self.stand_in_widgets = QWidget()
        stand_in_row = self._switch_row(
            self.stand_in, "Notbehelf: N × längstes Sample",
            self._dim("Ohne Takt: der längste Loop zählt als ein Takt. Wird in der Datei vermerkt."))
        stand_in_layout = QVBoxLayout(self.stand_in_widgets)
        stand_in_layout.setContentsMargins(0, 0, 0, 0)
        stand_in_layout.addLayout(stand_in_row)
        layout.addWidget(self.stand_in_widgets)

        layout.addSpacing(6)
        layout.addWidget(self._heading("Format"))
        wav = QRadioButton("WAV")
        wav.setChecked(True)
        wav.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        wav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        wav.setStyleSheet("font-size: 15.5px; font-weight: bold;")
        badge = QLabel("Standard")
        badge.setStyleSheet(
            f"background: {CHIP_FILL}; color: {PARENT_ACCENT}; font-size: 11.5px; font-weight: bold; "
            "border-radius: 10px; padding: 2px 10px;")
        wav_row = QHBoxLayout()
        wav_row.addWidget(wav)
        wav_row.addWidget(badge)
        wav_row.addStretch(1)
        layout.addLayout(wav_row)
        self.format_hint = self._dim("")
        self.format_hint.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(self.format_hint)

        layout.addStretch(1)
        self.sum_message = QLabel("")
        self.sum_message.setWordWrap(True)
        layout.addWidget(self.sum_message)
        self.export_button = BigButton("download", "Summe als WAV exportieren", QColor(PARENT_ACCENT),
                                       checkable=True, min_height=56, font_pt=13)
        self.export_button.setChecked(True)  # filled: the one main action
        self.export_button.clicked.connect(self._export_clicked)
        layout.addWidget(self.export_button)
        return card

    def _right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(12)

        preview = self._card()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(22, 18, 22, 12)
        preview_layout.addWidget(self._heading("Vorschau: was wiederholt wird", 17))
        self.preview = PreviewRows()
        self.preview.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        preview_layout.addWidget(self.preview)  # as tall as its rows ask; the page scrolls
        self.preview_note = self._dim("", 11.5)
        preview_layout.addWidget(self.preview_note)
        preview_layout.addStretch(1)  # spare room goes below the note, not between the axis and the note
        column.addWidget(preview, 1)

        single = self._card()
        single_layout = QVBoxLayout(single)
        single_layout.setContentsMargins(22, 10, 22, 10)
        single_layout.setSpacing(4)
        single_layout.addWidget(self._heading("Einzelnen Loop sichern", 19))
        chips = QGridLayout()
        chips.setSpacing(6)
        self.pad_group = QButtonGroup(self)
        self.pad_group.setExclusive(True)
        self.pad_chips: dict[int, QPushButton] = {}
        cols = max(1, self.controller.settings.cols)
        for pad in range(self.controller.pad_count):
            chip = QPushButton(str(pad + 1))
            chip.setObjectName("pad_chip")
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setEnabled(self.controller.pad(pad).sample is not None)
            self.pad_group.addButton(chip, pad)
            self.pad_chips[pad] = chip
            chips.addWidget(chip, pad // cols, pad % cols)
        first = next((p for p, c in self.pad_chips.items() if c.isEnabled()), None)
        if first is not None:
            self.pad_chips[first].setChecked(True)
        self.pad_group.idClicked.connect(weak_slot(self.refresh))
        single_layout.addLayout(chips)
        self.loop_info = self._dim("", 13)
        single_layout.addWidget(self.loop_info)
        self.cue_switch = ToggleSwitch()
        self.cue_switch.setChecked(self.controller.settings.export_cue_points)
        self.cue_switch.toggled.connect(self.set_cue_points)
        single_layout.addLayout(self._switch_row(
            self.cue_switch, CUE_TITLE,
            self._dim("sonst als Begleitdatei; das Sichern scheitert daran nie", 12)))
        self.loop_message = QLabel("")
        self.loop_message.setWordWrap(True)
        single_layout.addWidget(self.loop_message)
        self.loop_button = BigButton(
            "download", "Loop als WAV sichern", ACCENT_GRAY, min_height=46, font_pt=12)
        self.loop_button.clicked.connect(self._loop_clicked)
        single_layout.addWidget(self.loop_button)
        column.addWidget(single, 0)

        info = QFrame()
        info.setObjectName("info_card")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(16, 10, 16, 10)
        info_layout.addWidget(_IconLabel("check", PARENT_ACCENT, 26), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(self._heading("Eltern-Grenze gilt auch hier", 14))
        self.limit_label = QLabel("")
        self.limit_label.setWordWrap(True)
        self.limit_label.setStyleSheet("color: #C7C7CC; font-size: 14px;")
        texts.addWidget(self.limit_label)
        info_layout.addLayout(texts, 1)
        column.addWidget(info, 0)
        return column

    # -------------------------------------------------------------- state

    def _bars_chosen(self, _id: int) -> None:
        self.custom_row.setVisible(self.bar_group.checkedId() == CUSTOM_BARS)
        self.refresh()

    @property
    def bars(self) -> int:
        chosen = self.bar_group.checkedId()
        return self.custom_spin.value() if chosen == CUSTOM_BARS else chosen

    @property
    def all_pads(self) -> bool:
        return self.scope_all.isChecked()

    def _spec(self, bars: int | None = None) -> ex.SumSpec:
        return ex.build_spec(
            self.controller, self.bars if bars is None else bars, all_pads=self.all_pads,
            include_one_shots=self.one_shots.isChecked(), fade_out=self.fade_out.isChecked(),
            longest_as_bar=self.stand_in.isChecked())

    def selected_loop_pad(self) -> int | None:
        pad = self.pad_group.checkedId()
        return pad if pad >= 0 else None

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        """Each visit chooses the pads from what loops now; a choice on the open page stays.

        The page is built on the first visit and kept. When nothing loops but pads have a sample,
        "only what loops" would export nothing, so every pad with a sample is taken as a loop.
        A window coming back (``spontaneous``) is no new visit.
        """
        super().showEvent(event)
        if event.spontaneous():
            return
        loops, _shots = ex.selected_pads(self.controller, all_pads=False)
        every, _none = ex.selected_pads(self.controller, all_pads=True)
        take_all = not loops and bool(every)
        if self.scope_all.isChecked() == take_all:
            self.refresh()  # the session may have changed since the last visit
        else:
            (self.scope_all if take_all else self.scope_running).setChecked(True)  # refreshes

    def refresh(self) -> None:
        """Bring the texts, the length and the preview in line with the choices and the session."""
        controller = self.controller
        rate = controller.sample_rate
        grid = controller.grid_frames()
        loops, _shots = ex.selected_pads(controller, all_pads=False)
        every, _none = ex.selected_pads(controller, all_pads=True)
        self.running_count.setText(f"{len(loops)} Pad" + ("" if len(loops) == 1 else "s"))
        self.all_count.setText(f"{len(every)} Pad" + ("" if len(every) == 1 else "s"))
        self.stand_in_widgets.setVisible(grid is None)

        if grid is None:
            self.session_label.setText("Sitzung · kein Takt")
        else:
            seconds = german_number(ex.bar_seconds(grid, rate), 2)
            bpm = ex.bpm_of(grid, rate)
            tempo = f" · {german_number(bpm, 0)} BPM · 4/4" if 40 <= bpm <= 200 else ""
            self.session_label.setText(f"Sitzung · Takt {seconds} s{tempo}")
        self.fade_hint.setText(
            f"{round(ex.FADE_OUT_SECONDS * 1000)}{NBSP}ms Fade gegen Knacken")
        self.format_hint.setText(f"mono, 24{NBSP}Bit, {rate_text(rate)}")
        self.limit_label.setText(
            f"Lautstärke + Limiter wie live auf die Summe ({level_text(controller.max_level_db)}).\n"
            "Kein Takt in der Sitzung? Dann Notbehelf \"N × längstes Sample\" ausdrücklich wählen.")

        self.sum_message.setText("")
        rows: list[tuple[str, float, bool]] = []
        try:
            spec = self._spec()
            info = ex.plan_sum(spec)
        except ex.ExportError as exc:
            self.length_label.setText(str(exc))
            self.length_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #FF9F0A;")
            self.frames_label.setText("")
            self.preview.set_rows([], self.bars)
            self.preview_note.setText("")
        else:
            bar_seconds = info.bar_frames / rate
            self.length_label.setStyleSheet("font-size: 18px; font-weight: 800;")
            self.length_label.setText(
                f"{spec.bars} Takte × {german_number(bar_seconds, 2)} s = {german_number(info.seconds, 1)} s")
            self.frames_label.setText(f"{frames_text(info.frames)} Frames · {rate_text(rate)}")
            rows = [(f"Pad {p.pad + 1}", ex.repeats_per_bar(len(p.data), info.bar_frames), False)
                    for p in spec.loops]
            rows += [(f"Pad {p.pad + 1}", ex.repeats_per_bar(len(p.data), info.bar_frames), True)
                     for p in spec.one_shots]
            self.preview.set_rows(rows, spec.bars)
            self.preview_note.setText(
                "Grau = Einmal-Pad, nur am Anfang" if spec.one_shots else
                "Alle Loops starten vorn und wiederholen sich; am Ende wird geschnitten.")

        pad = self.selected_loop_pad()
        self.loop_button.setEnabled(pad is not None)
        if pad is None:
            self.loop_info.setText("Noch kein Pad mit Aufnahme.")
        else:
            self.loop_info.setText(self._loop_text(pad))

    def _loop_text(self, pad: int) -> str:
        sample = self.controller.pad(pad).sample
        data = None if sample is None else self.controller.sample_audio(sample)
        if data is None:
            return f"Pad {pad + 1} · Aufnahme nicht lesbar"
        rate = self.controller.sample_rate
        text = f"Pad {pad + 1} · Aufnahme {german_number(len(data) / rate, 2)} s"
        grid = self.controller.grid_frames()
        if grid is not None and len(data) % grid == 0:
            bars = len(data) // grid
            text += f" · {bars} Takt" + ("" if bars == 1 else "e") + " · im Raster"
        return text

    # ------------------------------------------------------------- export

    def _stamp(self) -> str:
        return datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d_%H%M")

    def _say(self, label: QLabel, text: str, error: bool = False) -> None:
        color = "#FF3B30" if error else "#32D74B"
        label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        label.setText(text)

    def _export_clicked(self) -> None:
        self.export_button.setChecked(True)  # keep it filled after the click toggled it
        self.export_sum()

    def export_sum(self) -> Path | None:
        """Write the sum as WAV; the path, or None (the reason is shown) if it cannot be made."""
        try:
            spec = self._spec()
            path = unique_path(self.export_dir, f"summe_{spec.bars}takte_{self._stamp()}.wav")
            ex.export_sum(path, spec)
        except ex.ExportError as exc:
            self._say(self.sum_message, str(exc), error=True)
            return None
        self.last_path = path
        self._say(self.sum_message, f"Gespeichert: {path}")
        return path

    def set_cue_points(self, on: bool) -> None:
        """Take the markers into the saved loop (until the settings file is saved with another value)."""
        settings = self.controller.settings
        if settings.export_cue_points != on:
            self.controller.apply_settings(replace(settings, export_cue_points=on))

    def _loop_clicked(self) -> None:
        self.export_loop()

    def export_loop(self) -> Path | None:
        """Write the chosen pad's loop unchanged as WAV; the path, or None (the reason is shown)."""
        path, text, error = save_loop(
            self.controller, self.selected_loop_pad(), self.export_dir, self._stamp())
        self._say(self.loop_message, text, error=error)
        if path is not None:
            self.last_path = path
        return path

