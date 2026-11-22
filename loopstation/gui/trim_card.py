"""Shortening a loop in the detail panel of the parents' view (mockup L2-03; the child's page gets nothing).

The handles sit in the waveform (``WaveformWidget``); ``TrimBalance`` says what they would make of the
loop (length in seconds and bars) in the line under the wave, snaps the length to whole bars when the
parents want that ("Takt rasten"), plays the shortened version, and keeps it ("Übernehmen") or throws
it away ("Verwerfen"). Logic and arithmetic live in the controller (``check_trim``, ``trim_loop``) and
``loopstation.trim``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import Controller, TrimCheck
from loopstation.gui.grid_panel import format_seconds
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import qicon
from loopstation.gui.settings_panels import ToggleSwitch
from loopstation.gui.waveform import WaveformWidget
from loopstation.gui.widgets import ACCENT_GRAY, BACKGROUND, TEXT, TEXT_DIM, BigButton, big_font, weak_slot

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


class TrimBalance:
    """The controls of a trim: the snap switch, the readout and note under the wave, Verwerfen and Übernehmen.

    It owns its widgets; the detail panel places them. ``message`` takes the place of the readout and the
    note while it says something (``say``); moving a handle brings the readout back. ``idle_hint`` is
    what the note says while the handles are on the ends of the loop.
    """

    def __init__(
        self,
        controller: Controller,
        waveform: WaveformWidget,
        pad: Callable[[], int],
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.controller = controller
        self.waveform = waveform
        self._pad = pad
        self._on_done = on_done
        self.idle_hint = ""
        # What the parents choose when the loop that gives the bar gets shortened; tests replace it.
        self.ask_grid: Callable[[TrimCheck], str | None] | None = None
        self.readout = QLabel("")
        self.readout.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setVisible(False)  # only there while it says something
        self.snap_switch = ToggleSwitch()
        self.snap_switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.snap_switch.setChecked(True)  # on: the trimmed loop stays on the bars
        self.snap_switch.setAccessibleName("Takt rasten")
        self.snap_switch.setToolTip("An: der Loop bleibt auf ganzen Takten. Aus: die gezogene Länge.")
        self.snap_switch.toggled.connect(weak_slot(self._snap_toggled))
        self.discard_button = QPushButton("Verwerfen")
        self.discard_button.setObjectName("secondary")
        self.discard_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.discard_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.discard_button.clicked.connect(weak_slot(self.discard))
        self.apply_button = QPushButton("Übernehmen")
        self.apply_button.setObjectName("primary")  # filled in the accent colour: the one main action
        self.apply_button.setIcon(qicon("check", "#111114", 24))
        self.apply_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.clicked.connect(weak_slot(self.apply))
        self.waveform.trim_changed.connect(weak_slot(self._handles_moved))
        self.refresh()

    # ------------------------------------------------------------------ state

    def check(self) -> TrimCheck:
        start, end = self.waveform.trim_range
        return self.controller.check_trim(self._pad(), start, end, self.snap_switch.isChecked())

    def say(self, text: str, error: bool = False) -> None:
        """``text`` in place of the readout ("" brings the readout back)."""
        color = WARN if error else GOOD
        self.message.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.readout.setVisible(not text)
        self.note.setVisible(not text and bool(self.note.text()))

    def _handles_moved(self) -> None:
        self.say("")
        self.refresh()

    def _snap_toggled(self) -> None:
        if self.waveform.trimmed:
            self.say("")
        self.refresh()

    def refresh(self) -> None:
        """Readout, note and buttons follow the handles (and the snap switch)."""
        controller = self.controller
        rate = controller.sample_rate
        whole = self.waveform.loop_frames
        moved = self.waveform.trimmed
        self.discard_button.setEnabled(moved)
        untouched = "Erst Anfang oder Ende in der Welle ziehen"
        self.discard_button.setToolTip("Die Griffe zurück an die Enden" if moved else untouched)
        if whole == 0:
            self.readout.setText("Noch kein Loop auf diesem Pad")
            self._set_note(self.idle_hint)
            self.apply_button.setEnabled(False)
            self.apply_button.setToolTip("Auf diesem Pad ist noch kein Loop")
            return
        grid = controller.grid_frames()
        before = format_seconds(whole / rate)
        if grid is not None:
            before += f" · {bars_text(whole / grid)}"
        if not moved:
            self.readout.setText(f"Loop {before}")
            self._set_note(self.idle_hint)
            self.apply_button.setEnabled(False)
            self.apply_button.setToolTip(untouched)
            return
        check = self.check()
        plan = check.plan
        if plan is None or plan.frames == 0:
            self.readout.setText(f"Kürzen: Anfang muss vor dem Ende liegen · vorher {before}")
            self._set_note("")
        else:
            bars = "" if plan.bars is None else f" · {bars_text(plan.bars)}"
            self.readout.setText(f"Kürzen: neu {format_seconds(plan.frames / rate)}{bars} · vorher {before}")
            self._set_note(self._note(check))
        can = check.ok or check.decide
        self.apply_button.setEnabled(can)
        self.apply_button.setToolTip("Den Loop so kürzen; Zurück nimmt es zurück" if can
                                     else (check.refusal or "So lässt sich der Loop nicht kürzen"))

    def can_listen(self) -> bool:
        """Can the loop be heard as it would be (the handles on the ends: the whole loop)?"""
        if self.waveform.loop_frames == 0:
            return False
        if not self.waveform.trimmed:
            return True
        check = self.check()
        return check.plan is not None and check.plan.frames > 0 and (check.ok or check.decide)

    def _set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text) and not self.message.isVisible())

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
        """The loop as it would be, once; nothing is saved."""
        start, end = self.waveform.trim_range
        refusal = self.controller.trim_preview(self._pad(), start, end, self.snap_switch.isChecked())
        if refusal is not None:
            self.say(refusal, error=True)

    def discard(self) -> None:
        """"Verwerfen": the handles go back to the ends; nothing was changed."""
        self.waveform.reset_trim()
        self.say("Verworfen. Der Loop ist, wie er war.")

    def apply(self) -> bool:
        """"Übernehmen": shorten the loop; True if it was done (the line says why not)."""
        check = self.check()
        snap, regrid = self.snap_switch.isChecked(), False
        if check.decide:
            ask = self.ask_grid
            choice = ask(check) if ask is not None else ask_grid_choice(check, self.apply_button.window())
            if choice is None:
                self.say("Nichts geändert.", error=True)
                return False
            snap, regrid = choice == SNAP, choice == REGRID
        start, end = self.waveform.trim_range
        refusal = self.controller.trim_loop(self._pad(), start, end, snap=snap, regrid=regrid)
        if refusal is not None:
            self.say(refusal, error=True)
            return False
        if self._on_done is not None:
            self._on_done()
        self.say("Gekürzt. Das Original liegt im Verlauf, Zurück bringt es wieder.")
        return True
