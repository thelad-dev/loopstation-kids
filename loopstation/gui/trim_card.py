"""The card "Loop kürzen" on the Erweitert page (parents only; the child's page gets nothing from it).

The handles sit in the waveform (``WaveformWidget``); this card shows what they would make of the
loop (length in seconds and bars), snaps the length to whole bars when the parents want that, plays
the shortened version, and keeps or throws it away. Logic and arithmetic live in the controller
(``check_trim``, ``trim_loop``) and ``loopstation.trim``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller, TrimCheck
from loopstation.gui.grid_panel import format_seconds
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import dim_label
from loopstation.gui.settings_panels import ToggleSwitch
from loopstation.gui.waveform import WaveformWidget
from loopstation.gui.widgets import ACCENT_GRAY, BACKGROUND, TEXT, TEXT_DIM, BigButton, big_font, weak_slot

HINT = ("Zieh Anfang und Ende in der Wellenform. Das Original bleibt im Verlauf, "
        "Zurück nimmt das Kürzen zurück.")
GOOD, WARN = "#32D74B", "#FF9F0A"
REGRID, SNAP = "regrid", "snap"  # what the parents choose when the loop that gives the bar gets shortened


def bars_text(bars: float | None) -> str:
    """``1 Takt``, ``2 Takte``, ``0,75 Takte``: a bar count as the parents read it."""
    if bars is None:
        return "freie Länge"
    if abs(bars - round(bars)) < 0.005:
        whole = round(bars)
        return "1 Takt" if whole == 1 else f"{whole} Takte"
    return f"{bars:.2f}".replace(".", ",") + " Takte"


class GridChoiceDialog(QDialog):
    """The loop gives the bar and would no longer fit it: set the bar anew, snap, or leave it."""

    def __init__(self, check: TrimCheck, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("Dieser Loop gibt den Takt vor")
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {BACKGROUND.name()}; }}")
        plan = check.plan
        seconds = format_seconds(check.seconds)
        title = QLabel("Dieser Loop gibt den Takt vor")
        title.setFont(big_font(26))
        title.setStyleSheet(f"color: {TEXT.name()};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bars = bars_text(None if plan is None else plan.bars)
        hint = QLabel(
            f"Gekürzt wäre er {seconds} lang ({bars}).\n"
            "Raster neu setzen: Diese Länge ist der neue Takt, die anderen Loops passen sich an.\n"
            "Auf Takt rasten: Der Loop wird auf ganze Takte gesetzt, der Takt bleibt.")
        hint.setFont(big_font(16, bold=False))
        hint.setStyleSheet(f"color: {TEXT_DIM.name()};")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        regrid = BigButton("check", "Raster neu setzen", QColor(PARENT_ACCENT), checkable=True)
        regrid.setChecked(True)  # filled: the main choice
        regrid.clicked.connect(weak_slot(self._pick, REGRID))
        snap = BigButton("check", "Auf Takt rasten", ACCENT_GRAY)
        snap.clicked.connect(weak_slot(self._pick, SNAP))
        cancel = BigButton("close", "Abbrechen", ACCENT_GRAY)
        cancel.clicked.connect(self.reject)
        self.regrid_button, self.snap_button, self.cancel_button = regrid, snap, cancel
        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        for button in (cancel, snap, regrid):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 34, 40, 34)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addSpacing(12)
        layout.addLayout(buttons)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()


def ask_grid_choice(check: TrimCheck, parent: QWidget | None = None) -> str | None:
    """Show the dialog; ``"regrid"``, ``"snap"`` or None (cancelled)."""
    dialog = GridChoiceDialog(check, parent)
    dialog.exec()
    return dialog.choice


class TrimCard(QFrame):
    """Readout, snap switch and the buttons "Gekürzt anhören", "Verwerfen" and "Übernehmen"."""

    def __init__(
        self,
        controller: Controller,
        waveform: WaveformWidget,
        pad: Callable[[], int],
        parent: QWidget | None = None,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.waveform = waveform
        self._pad = pad
        self._on_done = on_done
        # What the parents choose when the loop that gives the bar gets shortened; tests replace it.
        self.ask_grid: Callable[[TrimCheck], str | None] | None = None
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 18)
        layout.setSpacing(8)
        heading = QLabel("Loop kürzen")
        heading.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(heading)
        layout.addWidget(dim_label(HINT, 13.5))
        self.readout = QLabel("")
        self.readout.setWordWrap(True)
        self.readout.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(self.readout)
        self.note = dim_label("", 13.5)
        layout.addWidget(self.note)

        self.snap_switch = ToggleSwitch()
        self.snap_switch.setChecked(True)  # on: the trimmed loop stays on the bars
        self.snap_switch.toggled.connect(weak_slot(self.refresh))
        name = QLabel("Auf Taktraster rasten")
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(dim_label("ganze Takte, der Loop bleibt im Raster (aus: gezogene Länge)", 13))
        snap_row = QHBoxLayout()
        snap_row.setSpacing(16)
        snap_row.addWidget(self.snap_switch, 0, Qt.AlignmentFlag.AlignTop)
        snap_row.addLayout(texts, 1)
        layout.addLayout(snap_row)

        self.listen_button = self._button("Gekürzt anhören")
        self.listen_button.clicked.connect(weak_slot(self.listen))
        self.discard_button = self._button("Verwerfen")
        self.discard_button.clicked.connect(weak_slot(self.discard))
        self.apply_button = BigButton("check", "Übernehmen", QColor(PARENT_ACCENT), checkable=True,
                                      min_height=56, font_pt=13)
        self.apply_button.setChecked(True)  # filled: the one main action
        self.apply_button.clicked.connect(weak_slot(self._apply_clicked))
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        for button in (self.listen_button, self.discard_button):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        buttons.addWidget(self.listen_button, 1)
        buttons.addWidget(self.discard_button, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.apply_button)  # below the two: the card sits in a narrow side panel
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setVisible(False)  # only there while it says something
        layout.addWidget(self.message)
        self.waveform.trim_changed.connect(weak_slot(self.refresh))
        self.refresh()

    @staticmethod
    def _button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("secondary")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    # ------------------------------------------------------------------ state

    def check(self) -> TrimCheck:
        start, end = self.waveform.trim_range
        return self.controller.check_trim(self._pad(), start, end, self.snap_switch.isChecked())

    def say(self, text: str, error: bool = False) -> None:
        color = WARN if error else GOOD
        self.message.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def refresh(self) -> None:
        """Readout, note and buttons follow the handles (and the snap switch)."""
        controller = self.controller
        rate = controller.sample_rate
        whole = self.waveform.loop_frames
        moved = self.waveform.trimmed
        self.discard_button.setEnabled(moved)
        if whole == 0:
            self.readout.setText("Noch kein Loop auf diesem Pad")
            self.note.setText("")
            self.listen_button.setEnabled(False)
            self.apply_button.setEnabled(False)
            return
        grid = controller.grid_frames()
        before = f"vorher {format_seconds(whole / rate)}"
        if grid is not None:
            before += f" · {bars_text(whole / grid)}"
        check = self.check()
        plan = check.plan
        if plan is None or plan.frames == 0:
            self.readout.setText(f"Neu: Anfang muss vor dem Ende liegen  ({before})")
            self.note.setText("")
        else:
            bars = "" if plan.bars is None else f" · {bars_text(plan.bars)}"
            self.readout.setText(f"Neu: {format_seconds(plan.frames / rate)}{bars}  ({before})")
            self.note.setText(self._note(check))
        can_play = plan is not None and plan.frames > 0 and (check.ok or check.decide or not moved)
        self.listen_button.setEnabled(can_play)
        self.apply_button.setEnabled(moved and (check.ok or check.decide))

    def _note(self, check: TrimCheck) -> str:
        plan = check.plan
        if plan is None:
            return ""
        if check.refusal is not None and not check.decide:
            return check.refusal
        if check.decide:
            return "Dieser Loop gibt den Takt vor: Beim Übernehmen legst du fest, was mit dem Takt geschieht."
        if plan.snapped:
            rest = " (der Rest ist Stille)" if plan.end - plan.start < plan.frames else ""
            return f"Rastet auf ganze Takte: der Loop bleibt im Raster{rest}."
        if plan.played is not None and check.grid_frames is not None and plan.played != plan.frames:
            return f"Spielt als {bars_text(plan.played / check.grid_frames)}, der Rest ist Stille."
        return ""

    # ---------------------------------------------------------------- actions

    def listen(self) -> None:
        """"Gekürzt anhören": the loop as it would be, once; nothing is saved."""
        start, end = self.waveform.trim_range
        refusal = self.controller.trim_preview(self._pad(), start, end, self.snap_switch.isChecked())
        if refusal is not None:
            self.say(refusal, error=True)

    def discard(self) -> None:
        """"Verwerfen": the handles go back to the ends; nothing was changed."""
        self.waveform.reset_trim()
        self.say("Verworfen. Der Loop ist, wie er war.")

    def _apply_clicked(self) -> None:
        self.apply_button.setChecked(True)  # keep it filled after the click toggled it
        self.apply()

    def apply(self) -> bool:
        """"Übernehmen": shorten the loop; True if it was done (the card says why not)."""
        check = self.check()
        snap, regrid = self.snap_switch.isChecked(), False
        if check.decide:
            choice = self.ask_grid(check) if self.ask_grid is not None else ask_grid_choice(check, self)
            if choice is None:
                self.say("Nichts geändert.", error=True)
                return False
            snap, regrid = choice == SNAP, choice == REGRID
        start, end = self.waveform.trim_range
        refusal = self.controller.trim_loop(self._pad(), start, end, snap=snap, regrid=regrid)
        if refusal is not None:
            self.say(refusal, error=True)
            return False
        self.say("Gekürzt. Das Original liegt im Verlauf, Zurück bringt es wieder.")
        if self._on_done is not None:
            self._on_done()
        return True
