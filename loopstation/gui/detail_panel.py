"""The detail panel of the chosen pad (Loopstation 2, variant A; mockups L2-02 folded, L2-03 and L2-04 open).

Folded it is one line under the pads: the pad's badge, "Pad N", a line of facts, the tabs and a button
that unfolds it. Unfolded (a tap on the line, the button, a tab, Enter or a double click on a tile) it
takes about 45 % of the window height and shows the chosen pad in tabs:

- **Loop:** the wave on the beat lines with the trim handles, the markers and the play head; one row of
  actions (Anhören, Marker, Strecken, Export, Takt rasten) and, on the right, Verwerfen and Übernehmen
  for the trim. The line under the wave says what a trim would make of the loop, or why a button waits.
- **Pad:** free mode, start on the bar (a setting for all free pads), the takes of this pad (listen,
  bring back) and the level of the take with its target zone and "zu laut". Name and pad volume need
  the new core: they are shown greyed out.
- **Aufnahme:** the microphone level, the longest recording and the record start tone. The two settings
  are the ones of the panel "System": the same inputs save the same way (``SettingsPanels.mirror``).
- **Effekte (später):** visible, greyed out.

Choosing a pad changes what the panel shows; starting one does not. The panel reads and sets the
controller only. It has no timer of its own: the main window's tick calls ``refresh``.
"""

from __future__ import annotations

import math
import time
import weakref
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from loopstation.controller import NEAR_CLIP_DB, HistoryEntry
from loopstation.gui.export_dialog import default_export_dir, save_loop
from loopstation.gui.grid_panel import format_seconds
from loopstation.gui.history_dialog import LABELS, LATER
from loopstation.gui.level_panel import format_db, format_when
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import (
    ACTIVE_FILL,
    CARD_BORDER,
    CARD_FILL,
    PAGE_STYLE,
    draw_line,
    fitted_font,
    paint_icon,
    qicon,
    scrolled,
)
from loopstation.gui.peak_meter import TARGET_HIGH_DB, TARGET_LOW_DB, PeakMeter
from loopstation.gui.settings_panels import ToggleSwitch
from loopstation.gui.side_panel import FORM_QSS
from loopstation.gui.trim_card import TrimBalance
from loopstation.gui.waveform import FLAG_ROOM, WAVE_COLOR, WaveformWidget, marker_name, peak_columns
from loopstation.gui.widgets import PAD_COLORS, TEXT, TEXT_DIM, weak_slot

if TYPE_CHECKING:
    from loopstation.controller import Controller
    from loopstation.gui.settings_panels import SettingsPanels

HEADER = 64  # the folded panel, and the head of the unfolded one
MARGIN = 16
FOLD_SIZE = QSize(44, 42)
WIDE = 1000  # from this width the tabs and the action row have their full size
INFO_LEAST = 200  # the folded line keeps this much room for "Pad N" and its facts, else the tabs give way
BADGE_END = MARGIN + 36 + 16  # where "Pad N" begins, right of the badge
TABS = (("loop", "Loop"), ("pad", "Pad"), ("record", "Aufnahme"), ("effects", "Effekte (später)"))
NEW_CORE = "kommt mit dem neuen Kern"
LABEL = QColor("#C7C7CC")
OFF = QColor("#55555C")
WARN, LOUD, GOOD = "#FF9F0A", "#FFD60A", "#32D74B"
TAKE_WAVE_BARS = 26

ACTION_QSS = (
    "QPushButton#action {{ color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
    "border-radius: 12px; font-size: {size}px; font-weight: 700; min-height: 44px; max-height: 44px; "
    "padding: 0 {pad}px; }} "
    "QPushButton#action:pressed {{ background: #3A3A41; }} "
    "QPushButton#action:disabled {{ color: #5A5A60; border-color: #2C2C31; }} "
    f"QPushButton#primary {{{{ color: #111114; background: {PARENT_ACCENT}; "
    f"border: 1.5px solid {PARENT_ACCENT}; "
    "border-radius: 12px; font-size: {size}px; font-weight: 800; min-height: 44px; max-height: 44px; "
    "padding: 0 {pad}px; }} "
    "QPushButton#primary:pressed {{ background: #5F87E0; }} "
    "QPushButton#primary:disabled {{ color: #5A5A60; background: #26262B; border-color: #2C2C31; }} "
)
PANEL_QSS = (
    "QPushButton#round { background: #2A2A30; border: 1.5px solid #3A3A41; border-radius: 20px; "
    "min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; } "
    "QPushButton#round:pressed { background: #3A3A41; } "
    f"#take {{ background: {CARD_FILL}; border: 1.5px solid {CARD_BORDER}; border-radius: 12px; }} "
    f"#take_now {{ background: {ACTIVE_FILL}; border: 1.5px solid {PARENT_ACCENT}; border-radius: 12px; }} "
    "#loud { background: rgba(255, 159, 10, 23); border: 1.5px solid rgba(255, 159, 10, 102); "
    "border-radius: 14px; } "
    "QLineEdit:disabled { color: #5A5A60; border: 1.5px solid #2C2C31; } "
    "QSlider::groove:horizontal { height: 8px; background: #2C2C31; border-radius: 4px; } "
    "QSlider::handle:horizontal { width: 22px; margin: -8px 0; border-radius: 11px; background: #48484E; } "
)


def loop_title(recorded: int | None, played: int | None, grid: int | None, rate: int) -> str:
    """The line under "Pad N" while the panel is open: recorded length, bars, how it sits on the grid."""
    if recorded is None or played is None:
        return "noch kein Loop"
    parts = [f"Aufnahme {format_seconds(recorded / rate)}"]
    if grid is None:
        parts.append("freie Länge")
    else:
        bars = max(1, round(played / grid))
        parts.append("1 Takt" if bars == 1 else f"{bars} Takte")
        parts.append("im Raster" if recorded == played else "wird ans Raster angepasst")
    return " · ".join(parts)


def take_labels(entries: list[HistoryEntry], current: str | None) -> list[tuple[str, HistoryEntry]]:
    """The take on the pad first ("Jetzt"), then the others newest first ("Vorher", "Davor", "Früher")."""
    ordered = [e for e in entries if e.sample == current]
    ordered += [e for e in reversed(entries) if e.sample != current]
    named, earlier = [], 0
    for entry in ordered:
        if entry.sample == current:
            named.append((LABELS[0], entry))
        else:
            named.append(((LABELS[1:] + (LATER,) * len(ordered))[earlier], entry))
            earlier += 1
    return named


def _font(pixels: float, weight: QFont.Weight = QFont.Weight.Bold) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, round(pixels)))
    font.setWeight(weight)
    return font


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {LABEL.name()}; font-size: 14px; font-weight: bold;")
    return label


def _dim(text: str, size: float = 13, color: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color or TEXT_DIM.name()}; font-size: {size}px;")
    return label


def _switch_row(switch: QWidget, title: str, hint: QLabel) -> QWidget:
    """A switch beside its title and a dim line under it."""
    name = QLabel(title)
    name.setWordWrap(True)  # a narrow column breaks the title instead of cutting it
    name.setStyleSheet("font-size: 16px; font-weight: 600;")
    texts = QVBoxLayout()
    texts.setContentsMargins(0, 0, 0, 0)
    texts.setSpacing(0)
    texts.addWidget(name)
    texts.addWidget(hint)
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)
    layout.addLayout(texts, 1)
    return row


def _column(*items: QWidget, spacing: int = 8) -> QWidget:
    """``items`` one under the other at the top of a scroll area (a short window scrolls, never cuts)."""
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 12, 0)  # room for the scroll bar
    layout.setSpacing(spacing)
    for item in items:
        layout.addWidget(item)
    layout.addStretch(1)
    area = scrolled(inner)
    area.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # a tap on empty room leaves the keys to the pads
    return area


def _round_button(icon: str, name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName("round")
    button.setIcon(qicon(icon, TEXT, 22))
    button.setAccessibleName(name)
    button.setToolTip(name)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


# ------------------------------------------------------------------ head


class TabButton(QAbstractButton):
    """One tab in the head of the panel; lit while its page is shown."""

    def __init__(self, key: str, word: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.pixels = 17
        self.setText(word)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(word)

    def width_for(self, pixels: int, padding: int) -> int:
        return QFontMetrics(_font(pixels)).horizontalAdvance(self.text()) + 2 * padding

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        color = LABEL
        if self.isChecked():
            painter.setPen(QPen(QColor(PARENT_ACCENT), 2))
            painter.setBrush(QColor(ACTIVE_FILL))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 11, 11)
            color = QColor(PARENT_ACCENT)
        elif self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2A2A30"))
            painter.drawRoundedRect(rect, 11, 11)
        if not self.isEnabled():
            color = OFF
        painter.setFont(_font(self.pixels))
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class FoldButton(QAbstractButton):
    """The chevron at the right of the head: up unfolds the panel, down folds it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.unfolded = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_unfolded(False)

    def set_unfolded(self, unfolded: bool) -> None:
        self.unfolded = unfolded
        word = "Detailfeld zuklappen" if unfolded else "Detailfeld aufklappen"
        self.setAccessibleName(word)
        self.setToolTip(word + " (Enter)")
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setPen(QPen(QColor("#3A3A41"), 1.5))
        painter.setBrush(QColor("#2A2A30") if self.isDown() else QColor("#1F1F24"))
        painter.drawRoundedRect(rect, 12, 12)
        middle = rect.center()
        painter.translate(middle)
        if not self.unfolded:
            painter.rotate(180)  # the chevron points up: there is more above
        paint_icon(painter, "chevron", QRectF(-11, -11, 22, 22), TEXT)
        painter.end()


# ------------------------------------------------------------------ tab "Loop"


class LoopTab(QWidget):
    """Wave, markers, play head and the action row of the chosen pad's loop."""

    def __init__(self, panel: DetailPanel) -> None:
        super().__init__()
        self.controller = panel.controller
        self._panel = weakref.ref(panel)
        self.pad = panel.pad
        self._loop_key: object = None
        self._marker_key: object = None
        self._play: tuple[float, int, int] | None = None  # (start time, first frame, frames) while it plays
        self._tip_stamp = ""  # the minute the tooltip of "Export" was made for
        self.waveform = WaveformWidget()
        self.waveform.setMinimumHeight(FLAG_ROOM + 56)  # a low panel scrolls rather than flatten the wave
        self.waveform.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.waveform.bar_labels = True
        self.waveform.selection_changed.connect(weak_slot(self._selection_changed))
        tab = weakref.ref(self)
        self.trim = TrimBalance(self.controller, self.waveform, lambda: _pad_of(tab),
                                on_done=weak_slot(self.reload))
        self.waveform.trim_changed.connect(weak_slot(self._update_buttons))
        self.trim.snap_switch.toggled.connect(weak_slot(self._update_buttons))

        self.listen_button = self._action("play", "Anhören", self.listen)
        self.marker_button = self._action("flag", "Marker", self.marker_clicked)
        self.stretch_button = self._action("stretch", "Strecken", self.stretch_markers)
        self.export_button = self._action("download", "Export", self.export_loop)
        self.trim.discard_button.setObjectName("action")
        snap_label = QLabel("Takt rasten")
        snap_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.snap_label = snap_label

        line = QHBoxLayout()
        line.setContentsMargins(4, 0, 4, 0)
        line.setSpacing(10)
        line.addWidget(self.trim.readout)
        line.addWidget(self.trim.note, 1)
        line.addWidget(self.trim.message, 1)
        row = self.action_row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for button in (self.listen_button, self.marker_button, self.stretch_button, self.export_button):
            row.addWidget(button)
        row.addSpacing(14)
        row.addWidget(self.trim.snap_switch)
        row.addWidget(snap_label)
        row.addStretch(1)
        row.addWidget(self.trim.discard_button)
        row.addSpacing(8)
        row.addWidget(self.trim.apply_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(6)
        layout.addWidget(self.waveform, 1)
        layout.addLayout(line)
        layout.addSpacing(4)
        layout.addLayout(row)
        layout.addStretch(0)  # what the wave leaves (a tall window) stays below the row
        self._wide: bool | None = None
        self._fit(True)
        self.refresh()

    def _action(self, icon: str, word: str, slot: Callable[[], object]) -> QPushButton:
        button = QPushButton(word)
        button.setObjectName("action")
        button.setIcon(qicon(icon, TEXT, 24))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(weak_slot(slot))
        return button

    def _fit(self, wide: bool) -> None:
        """Full size from ``WIDE`` px of the tab on, a little smaller below (the row fits 1024 px windows)."""
        if wide == self._wide:
            return
        self._wide = wide
        size, pad, icon = (15, 13, 20) if wide else (13, 8, 18)
        self.setStyleSheet(ACTION_QSS.format(size=size, pad=pad))
        for button in (self.listen_button, self.marker_button, self.stretch_button, self.export_button,
                       self.trim.apply_button):
            button.setIconSize(QSize(icon, icon))
        self.snap_label.setStyleSheet(f"font-size: {size}px; font-weight: 700;")
        self.action_row.setSpacing(10 if wide else 7)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit(self.width() >= WIDE)
        # The wave takes about 60 % of the tab (mockup L2-03), the rest is the line and the row.
        self.waveform.setMaximumHeight(max(self.waveform.minimumHeight(), round(self.height() * 0.6)))

    # ------------------------------------------------------------- state

    def show_pad(self, pad: int) -> None:
        """Show the loop on ``pad``: no cursor, no message, the handles on the ends."""
        self.pad = pad
        self.waveform.clear_selection()
        self.trim.say("")
        self.stop_listening()
        self.reload()

    def reload(self) -> None:
        """Read the markers again (a trimmed or stretched loop is a new sample: the wave follows it)."""
        self._marker_key = None
        self.refresh()

    def refresh(self) -> None:
        self._show_loop()
        self._update_head()
        if self._stamp() != self._tip_stamp:
            self._update_buttons()  # the file name in the tooltip of "Export" has the minute in it

    def _show_loop(self) -> None:
        """Put the loop in the wave only when the loop or the grid changed (the handles stay otherwise)."""
        controller = self.controller
        pad = self.pad
        state = controller.pad(pad)
        sample = state.sample
        grid = None if state.free else controller.grid_frames()
        info = controller.grid_info()
        beats = 4 if info is None else info.beats
        key = (pad, sample, grid, beats)
        if key != self._loop_key:
            self._loop_key = key
            played = None if sample is None else controller.loop_audio(sample, pad)
            self.waveform.set_loop(played, grid, beats)
            self._marker_key = None
        marks = controller.markers(pad) if sample is not None else []
        marker_key = (key, tuple(marks), controller.recording_pad is None)
        if marker_key != self._marker_key:
            self._marker_key = marker_key
            frames = self.waveform.loop_frames
            self.waveform.set_markers([m for m in marks if m < frames])
            self.trim.idle_hint = self._hint()
            self.trim.refresh()
            self._update_buttons()

    def _hint(self) -> str:
        """What the line under the wave says while nothing is trimmed: what to do, or why a button waits."""
        controller = self.controller
        state = controller.pad(self.pad)
        if state.sample is None:
            return "Auf diesem Pad ist noch kein Loop: Symbol tippen oder R nimmt auf."
        if controller.recording_pad is not None:
            return "Es läuft gerade eine Aufnahme: Strecken wartet, bis sie fertig ist."
        if state.free:
            return "Freies Pad: eigene Länge ohne Schlaglinien, Strecken gibt es hier nicht."
        if controller.grid_info() is None:
            return "Ohne Takt gibt es keine Schlaglinien: Strecken geht erst mit einem Takt."
        if not self.waveform.markers:
            return "In die Welle tippen, dann Marker (oder M): Strecken braucht mindestens einen Marker."
        return "Strecken setzt jeden Marker auf seinen Schlag · Griffe Anfang und Ende kürzen den Loop."

    def _stretch_reason(self) -> str | None:
        controller = self.controller
        state = controller.pad(self.pad)
        if state.sample is None:
            return "Auf diesem Pad ist noch kein Loop"
        if controller.recording_pad is not None:
            return "Es läuft gerade eine Aufnahme"
        if state.free:
            return "Ein freies Pad hat keine Schlaglinien"
        if controller.grid_info() is None:
            return "Erst braucht die Sitzung einen Takt"
        if not self.waveform.markers:
            return "Erst einen Marker setzen"
        return None

    def _selection_changed(self) -> None:
        self.trim.say("")
        self._update_buttons()

    def _update_buttons(self) -> None:
        controller = self.controller
        wave = self.waveform
        has_sound = controller.pad(self.pad).sample is not None
        listen = self.trim.can_listen()
        self.listen_button.setEnabled(listen or self._play is not None)
        self.listen_button.setToolTip(
            ("Den gekürzten Loop einmal anhören" if wave.trimmed else "Den Loop einmal anhören") if listen
            else "Auf diesem Pad ist noch kein Loop" if not has_sound
            else "So gekürzt lässt sich der Loop nicht anhören")
        if wave.selected_marker is not None:
            self.marker_button.setText("Marker löschen")
            self.marker_button.setEnabled(True)
            self.marker_button.setToolTip(f"{marker_name(wave.selected_marker)} löschen")
        else:
            self.marker_button.setText("Marker")
            self.marker_button.setEnabled(wave.cursor_frame is not None)
            self.marker_button.setToolTip(
                "Einen Marker am Cursor setzen (M)" if wave.cursor_frame is not None
                else "Erst in die Welle tippen, dann Marker setzen (oder M)")
        reason = self._stretch_reason()
        self.stretch_button.setEnabled(reason is None)
        self.stretch_button.setToolTip("Jeder Marker wandert auf seinen Schlag; Zurück nimmt es zurück"
                                       if reason is None else reason)
        self.export_button.setEnabled(has_sound)
        self._tip_stamp = self._stamp()
        target = self.export_dir / f"pad{self.pad + 1:02d}_{self._tip_stamp}.wav"
        self.export_button.setToolTip(f"Diesen Loop als WAV sichern · Ziel: {target}" if has_sound
                                      else "Auf diesem Pad ist noch kein Loop")

    # ------------------------------------------------------------ play head

    def _update_head(self) -> None:
        play = self._play
        if play is None:
            return
        start, first, frames = play
        done = round((self.controller.now() - start) * self.controller.sample_rate)
        if done >= frames:
            self._stop_head()
            return
        self.waveform.set_play_frame(min(self.waveform.loop_frames, first + done))

    def _stop_head(self) -> None:
        if self._play is not None:
            self._play = None
            self.listen_button.setText("Anhören")
            self.listen_button.setIcon(qicon("play", TEXT, 24))
        self.waveform.set_play_frame(None)
        self._update_buttons()

    def stop_listening(self) -> None:
        """Stop the loop being heard (another pad or tab is shown)."""
        if self._play is not None:
            self.controller.stop_preview()
        self._stop_head()

    def listen(self) -> None:
        """"Anhören": the loop once as it plays on the pad (shortened, while the handles are moved); again
        stops it."""
        controller = self.controller
        if self._play is not None:
            self.stop_listening()
            return
        sample = controller.pad(self.pad).sample
        if sample is None:
            return
        wave = self.waveform
        if wave.trimmed:
            self.trim.listen()
            if self.trim.message.isVisible():
                return  # refused: the line says why
            plan = self.trim.check().plan
            first, frames = wave.trim_range[0], (0 if plan is None else plan.frames)
        else:
            # The loop as on the pad (fitted to the bars), so the play head matches what is heard.
            if controller.trim_preview(self.pad, 0, wave.loop_frames, snap=False) is not None:
                controller.preview(sample)
            first, frames = 0, wave.loop_frames
        self._play = (controller.now(), first, frames)
        self.listen_button.setText("Stopp")
        self.listen_button.setIcon(qicon("stop", TEXT, 24))
        self.listen_button.setEnabled(True)
        self._update_head()

    # -------------------------------------------------------------- markers

    def marker_clicked(self) -> None:
        if self.waveform.selected_marker is not None:
            self.delete_marker()
        else:
            self.place_marker()

    def place_marker(self) -> bool:
        """A marker where the cursor stands (snapped to a hit if the parents want that)."""
        frame = self.waveform.cursor_frame
        controller = self.controller
        if frame is None or not controller.add_marker(self.pad, controller.snap_marker(self.pad, frame)):
            return False
        self.waveform.clear_selection()
        self.reload()
        return True

    def delete_marker(self) -> bool:
        """The selected marker goes."""
        index = self.waveform.selected_marker
        if index is None or not self.controller.remove_marker(self.pad, self.waveform.markers[index]):
            return False
        self.waveform.clear_selection()
        self.reload()
        return True

    def stretch_markers(self) -> bool:
        """"Strecken": the markers move to their beats; the line says why if not."""
        refusal = self.controller.stretch_to_markers(self.pad)
        if refusal is not None:
            self.trim.say(refusal, error=True)
            return False
        self.waveform.clear_selection()
        self.reload()
        self.trim.say("Gestreckt. Der Loop davor liegt im Verlauf, Zurück bringt ihn wieder.")
        return True

    # --------------------------------------------------------------- export

    @property
    def export_dir(self) -> Path:
        panel = self._panel()
        return panel.export_dir if panel is not None else default_export_dir()

    def _stamp(self) -> str:
        panel = self._panel()
        now = panel.clock() if panel is not None else time.time()
        return time.strftime("%Y-%m-%d_%H%M", time.localtime(now))

    def export_loop(self) -> Path | None:
        """Write the loop of the pad as WAV; the path, or None (the line says why)."""
        path, text, error = save_loop(self.controller, self.pad, self.export_dir, self._stamp())
        self.trim.say(text, error=error)
        panel = self._panel()
        if path is not None and panel is not None:
            panel.last_path = path
        return path


def _pad_of(tab: weakref.ref[LoopTab]) -> int:
    shown = tab()
    return shown.pad if shown is not None else 0


# ------------------------------------------------------------------ tab "Pad"


class MiniWave(QWidget):
    """The small wave of a take."""

    def __init__(self, peaks: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.peaks = peaks
        self.setMinimumSize(56, 30)  # narrower in a narrow window, never wider than 86 px
        self.setMaximumSize(86, 30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(WAVE_COLOR), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        count = max(1, len(self.peaks))
        middle, half = self.height() / 2, self.height() / 2 - 2
        for index, peak in enumerate(self.peaks):
            x = 2 + (index + 0.5) * (self.width() - 4) / count
            reach = max(1.0, float(peak) * half)
            painter.drawLine(QPointF(x, middle - reach), QPointF(x, middle + reach))
        painter.end()


class TakeRow(QFrame):
    """One take of the pad: its wave, "Jetzt"/"Vorher"/..., length and time, Anhören and Zurückholen."""

    def __init__(self, label: str, when: str, peaks: np.ndarray, current: bool) -> None:
        super().__init__()
        self.setObjectName("take_now" if current else "take")
        self.label = label
        name = QLabel(label)
        name.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent; border: none;")
        sub = QLabel(when)
        sub.setWordWrap(True)  # length and time break into two lines in a narrow window
        sub.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px; background: transparent; "
                          "border: none;")
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        texts.addWidget(name)
        texts.addWidget(sub)
        self.listen_button = _round_button("play", "Anhören")
        self.restore_button: QPushButton | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 10, 6)
        layout.setSpacing(12)
        layout.addWidget(MiniWave(peaks))
        layout.addLayout(texts, 1)
        layout.addWidget(self.listen_button)
        if not current:
            self.restore_button = _round_button("rotate-ccw", "Zurückholen")
            layout.addWidget(self.restore_button)


class PadTab(QWidget):
    """Free mode, start on the bar, the takes of the pad and the level of its take."""

    def __init__(self, panel: DetailPanel) -> None:
        super().__init__()
        self.controller = panel.controller
        self.pad = panel.pad
        self._takes_key: object = None
        self._level_key: object = None
        self._take_cache: dict[str, tuple[np.ndarray, int, float]] = {}  # sample -> (peaks, frames, peak)
        self.take_rows: dict[str, TakeRow] = {}

        # Left: name, free mode, start on the bar, pad volume.
        self.name_edit = QLineEdit()
        self.name_edit.setEnabled(False)
        self.name_edit.setToolTip(f"Der Name eines Pads {NEW_CORE}")
        self.free_switch = ToggleSwitch()
        self.free_switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.free_switch.setAccessibleName("Freier Modus")
        self.free_switch.toggled.connect(weak_slot(self.set_free, pass_signal_args=True))
        self.free_hint = _dim("eigene Länge, nie gestreckt")
        free_row = _switch_row(self.free_switch, "Freier Modus", self.free_hint)
        source = panel.settings()
        self.on_grid_switch = source.mirror("free_pad_on_grid") if source is not None else None
        self.on_grid_hint = _dim("")
        on_grid_row: QWidget
        if self.on_grid_switch is not None:
            self.on_grid_switch.setAccessibleName("Start am Takt")
            on_grid_row = _switch_row(self.on_grid_switch, "Start am Takt", self.on_grid_hint)
        else:
            on_grid_row = _dim("„Start am Takt“ gibt es in der Leiste „Takt“.")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setEnabled(False)
        self.volume_slider.setValue(70)
        self.volume_slider.setToolTip(f"Die Lautstärke je Pad {NEW_CORE}")
        left = _column(_heading("Name"), self.name_edit, _dim(NEW_CORE, 12.5), free_row, on_grid_row,
                       _heading("Pad-Lautstärke"), self.volume_slider, _dim(NEW_CORE, 12.5), spacing=10)

        # Middle: the takes.
        self.takes_box = QWidget()
        self.takes_layout = QVBoxLayout(self.takes_box)
        self.takes_layout.setContentsMargins(0, 0, 0, 0)
        self.takes_layout.setSpacing(8)
        self.no_takes = _dim("Noch keine Aufnahme auf diesem Pad.")
        middle = _column(_heading("Takes dieses Pads"), self.takes_box, self.no_takes)

        # Right: the level of the take.
        self.meter = PeakMeter()
        self.meter.setAccessibleName("Pegel der Aufnahme")
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.loud_box = QFrame()
        self.loud_box.setObjectName("loud")
        self.loud_title = QLabel("")
        self.loud_title.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        self.loud_line = QLabel("")
        self.loud_line.setWordWrap(True)
        self.loud_line.setStyleSheet("font-size: 13.5px; background: transparent;")
        tip = _dim("Tipp: Mikro weiter weg oder Trim senken", 13)
        tip.setStyleSheet(tip.styleSheet() + " background: transparent;")
        box = QVBoxLayout(self.loud_box)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_AlertIcon())
        head.addWidget(self.loud_title, 1)
        box.addLayout(head)
        box.addWidget(self.loud_line)
        box.addWidget(tip)
        right = _column(_heading("Pegel der Aufnahme"), self.meter, self.verdict,
                        _dim("Mikrofon-Trim und Grenze: Werkzeug „Pegel“"), self.loud_box)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(28)
        layout.addWidget(left, 30)
        layout.addWidget(middle, 36)
        layout.addWidget(right, 35)
        self.refresh()

    def show_pad(self, pad: int) -> None:
        self.pad = pad
        self.refresh()

    def set_free(self, free: bool) -> None:
        """The switch "Freier Modus": the pad keeps its own length (one step on the Zurück stack)."""
        self.controller.set_free(self.pad, free)
        self.refresh()

    def refresh(self) -> None:
        controller = self.controller
        state = controller.pad(self.pad)
        recording = controller.recording_pad is not None
        self.free_switch.blockSignals(True)
        self.free_switch.setChecked(state.free)
        self.free_switch.blockSignals(False)
        self.free_switch.setEnabled(not recording)
        self.free_hint.setText("nicht während einer Aufnahme" if recording else "eigene Länge, nie gestreckt")
        if self.on_grid_switch is not None:
            self.on_grid_switch.setEnabled(state.free)
            self.on_grid_hint.setText(
                "wartet auf den nächsten Takt · gilt für alle freien Pads" if state.free
                else "wirkt nur bei einem freien Pad · gilt für alle freien Pads")
        self._update_takes()
        self._update_level()

    # ----------------------------------------------------------------- takes

    def _take(self, sample: str) -> tuple[np.ndarray, int, float]:
        """Peaks, length and loudest value of a take, read once."""
        known = self._take_cache.get(sample)
        if known is None:
            data = self.controller.sample_audio(sample)
            if data is None or not len(data):
                known = (np.zeros(TAKE_WAVE_BARS, dtype=np.float32), 0, 0.0)
            else:
                known = (peak_columns(data, TAKE_WAVE_BARS), len(data), float(np.max(np.abs(data))))
            self._take_cache[sample] = known
        return known

    def _update_takes(self) -> None:
        controller = self.controller
        state = controller.pad(self.pad)
        key = (self.pad, tuple(state.history), state.sample)
        if key == self._takes_key:
            return
        self._takes_key = key
        while self.takes_layout.count():
            item = self.takes_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.take_rows = {}
        now = datetime.fromtimestamp(controller.now())
        rate = controller.sample_rate
        for label, entry in take_labels(controller.history(self.pad), state.sample):
            peaks, frames, _peak = self._take(entry.sample)
            parts = [format_seconds(frames / rate)] if frames else []
            if entry.recorded_at is not None:
                when = format_when(entry.recorded_at.timestamp(), now)
                parts.append(when[:1].lower() + when[1:] if when[:1] in "HG" else when)
            row = TakeRow(label, " · ".join(parts), peaks, entry.sample == state.sample)
            row.listen_button.clicked.connect(weak_slot(self.listen_take, entry.sample))
            if row.restore_button is not None:
                row.restore_button.clicked.connect(weak_slot(self.restore_take, entry.sample))
            self.take_rows[entry.sample] = row
            self.takes_layout.addWidget(row)
        self.no_takes.setVisible(not self.take_rows)

    def listen_take(self, sample: str) -> None:
        """Play a take once."""
        self.controller.preview(sample)

    def restore_take(self, sample: str) -> None:
        """Put an earlier take back on the pad (one step on the Zurück stack)."""
        self.controller.restore(self.pad, sample)
        self.refresh()

    # ----------------------------------------------------------------- level

    def _loud_events(self) -> list:
        return [e for e in self.controller.clip_events() if e.pad == self.pad]

    def _take_of_event(self, at: float) -> str | None:
        """The label of the take a loud recording made ("Jetzt", "Davor" ...), None if none matches."""
        controller = self.controller
        state = controller.pad(self.pad)
        rate = controller.sample_rate
        for label, entry in take_labels(controller.history(self.pad), state.sample):
            if entry.recorded_at is None:
                continue
            seconds = self._take(entry.sample)[1] / rate
            if abs(entry.recorded_at.timestamp() - at) <= seconds + 5:
                return label
        return None

    def _update_level(self) -> None:
        controller = self.controller
        sample = controller.pad(self.pad).sample
        events = self._loud_events()
        key = (self.pad, sample, tuple((e.at, e.peak_db) for e in events))
        if key == self._level_key:
            return
        self._level_key = key
        labels = [self._take_of_event(e.at) for e in events]
        if sample is None:
            self.meter.setEnabled(False)
            self.meter.set_state(0.0, 0.0)
            self._say("Noch keine Aufnahme auf diesem Pad.", TEXT_DIM.name(), False)
        else:
            peak = self._take(sample)[2]
            peak_db = 20 * math.log10(peak) if peak > 0 else -120.0
            if LABELS[0] in labels:  # the microphone of this take was louder than what was kept
                peak_db = max(peak_db, events[labels.index(LABELS[0])].peak_db)
                peak = 10 ** (peak_db / 20)
            loud_now = LABELS[0] in labels or peak_db >= NEAR_CLIP_DB
            self.meter.setEnabled(True)
            self.meter.set_state(peak, peak, loud_now)
            rounded = min(0, round(peak_db))  # the verdict follows the number shown (-12.04 reads -12)
            shown = f"Spitze {format_db(rounded, 'dBFS')}" if peak > 0 else "Stille"
            if loud_now:
                self._say(f"{shown} · zu laut", WARN, True)
            elif rounded > TARGET_HIGH_DB:
                self._say(f"{shown} · etwas laut", LOUD, True)
            elif rounded >= TARGET_LOW_DB:
                self._say(f"{shown} · im Ziel", GOOD, True)
            else:
                self._say(f"{shown} · leise", TEXT_DIM.name(), True)
        self.loud_box.setVisible(bool(events))
        if events:
            newest, label = events[0], labels[0]
            count = len(events)
            self.loud_title.setText("Zu laut gewesen: " + ("einmal" if count == 1 else f"{count}-mal"))
            now = datetime.fromtimestamp(controller.now())
            where = f"Take „{label}“" if label is not None else format_when(newest.at, now)
            peak_text = format_db(min(0, round(newest.peak_db)), "dBFS")
            clipped = " · übersteuert" if newest.clipped else ""
            self.loud_line.setText(f"{where} · Spitze {peak_text}{clipped}")

    def _say(self, text: str, color: str, bold: bool) -> None:
        weight = "bold" if bold else "normal"
        self.verdict.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: {weight};")
        self.verdict.setText(text)


class _AlertIcon(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(22, 22)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_icon(painter, "alert", QRectF(self.rect()), WARN)
        painter.end()


# ------------------------------------------------------------------ tab "Aufnahme"


class RecordTab(QWidget):
    """The microphone level, the longest recording and the record start tone."""

    def __init__(self, panel: DetailPanel) -> None:
        super().__init__()
        self.controller = panel.controller
        self.meter = PeakMeter()
        self.meter.setAccessibleName("Mikrofonpegel")
        mic = _column(_heading("Mikrofonpegel"), self.meter, _dim(
            "Live beim Aufnehmen, sonst die Spitze der letzten Aufnahme · Trim und Grenze: Werkzeug „Pegel“"))
        source = panel.settings()
        self.longest: QWidget | None = None
        self.tone_switch: QWidget | None = None
        if source is not None:
            self.longest = source.mirror("max_record_seconds")
            self.longest.setAccessibleName("Längste Aufnahme")
            longest = _column(_heading("Längste Aufnahme"), self.longest, _dim(
                "Danach endet eine Aufnahme von selbst. Dieselbe Einstellung wie in der Leiste „System“."))
            longest.setMinimumWidth(self.longest.sizeHint().width() + 16)  # the stepper is never cut
            self.tone_switch = source.mirror("record_start_tone")
            self.tone_switch.setAccessibleName("Aufnahmestart-Ton")
            row = _switch_row(self.tone_switch, "Aufnahmestart-Ton", _dim(
                "Der Ton klingt aus, bevor die Aufnahme beginnt, und ist nie auf ihr zu hören."))
            tone = _column(_heading("Beim Start"), row)
        else:
            longest = _column(_dim("„Längste Aufnahme“ gibt es in der Leiste „System“."))
            tone = _column(_dim("„Aufnahmestart-Ton“ gibt es in der Leiste „System“."))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(28)
        layout.addWidget(mic, 34)
        layout.addWidget(longest, 26)
        layout.addWidget(tone, 40)
        self.refresh()

    def show_pad(self, _pad: int) -> None:
        pass  # the same for every pad

    def refresh(self) -> None:
        controller = self.controller
        level, hold = controller.meter_levels()
        self.meter.setEnabled(controller.peak_meter)
        self.meter.set_state(level, hold, controller.input_clipping())


# ------------------------------------------------------------------ the panel


class DetailPanel(QWidget):
    """The chosen pad folded in one line or unfolded with its tabs.

    ``fold_changed(open)`` when it unfolds or folds (the view lays the pads out anew). ``settings``
    hands out the settings panels (their ``mirror`` inputs), or None: the two settings tabs then point
    to the panels instead.
    """

    fold_changed = Signal(bool)

    def __init__(
        self,
        controller: Controller,
        parent: QWidget | None = None,
        export_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
        settings: Callable[[], SettingsPanels | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.export_dir = export_dir if export_dir is not None else default_export_dir()
        self.clock = clock
        self.settings_source = settings
        self.last_path: Path | None = None
        self.pad = 0
        self.is_open = False
        self.tab = "loop"
        self.number, self.color, self.title, self.info, self.help = 0, "white", "", "", ""
        self.open_info = ""
        self._info_key: object = None
        self._tabs_left = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Detailfeld des Pads")
        self.setStyleSheet(PAGE_STYLE + FORM_QSS + PANEL_QSS)
        self.tab_buttons: dict[str, TabButton] = {}
        for key, word in TABS:
            button = TabButton(key, word, self)
            if key == "effects":
                button.setEnabled(False)
                button.setToolTip(f"Effekte {NEW_CORE}")
            else:
                button.clicked.connect(weak_slot(self.open_tab, key))
            self.tab_buttons[key] = button
        self.fold_button = FoldButton(self)
        self.fold_button.clicked.connect(weak_slot(self.toggle))
        self.stack = QStackedWidget(self)
        self.stack.setCursor(Qt.CursorShape.ArrowCursor)
        self.stack.hide()
        # What the settings say about a value of the tabs (saved, refused), under the head.
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.hide()
        self.pages: dict[str, QWidget] = {}
        self._holders: dict[str, QWidget] = {}  # what the stack shows for a tab: the page or its scroll area

    # ---------------------------------------------------------------- tabs

    def settings(self) -> SettingsPanels | None:
        return self.settings_source() if self.settings_source is not None else None

    def page(self, key: str) -> QWidget:
        """The page of the tab ``key``, built on its first visit."""
        widget = self.pages.get(key)
        if widget is None:
            builder = {"loop": LoopTab, "pad": PadTab, "record": RecordTab}[key]
            widget = builder(self)
            self.pages[key] = widget
            holder = widget
            if key == "loop":
                # Wave, line and action row scroll together in a low panel (many rows in a low window);
                # the columns of the other tabs scroll on their own.
                # The width is the panel's (the row fits itself to it), never more: no sideways scrolling.
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
                holder = scrolled(widget)
                holder.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._holders[key] = holder
            self.stack.addWidget(holder)
        return widget

    def holder(self, key: str) -> QWidget:
        """What the stack shows for the tab ``key``: its page, or the scroll area around it."""
        self.page(key)
        return self._holders[key]

    @property
    def loop_tab(self) -> LoopTab:
        return self.page("loop")  # type: ignore[return-value]

    @property
    def pad_tab(self) -> PadTab:
        return self.page("pad")  # type: ignore[return-value]

    @property
    def record_tab(self) -> RecordTab:
        return self.page("record")  # type: ignore[return-value]

    def open_tab(self, key: str) -> None:
        """Show the tab ``key`` (the panel unfolds)."""
        if key not in self.tab_buttons or not self.tab_buttons[key].isEnabled():
            return
        loop = self.pages.get("loop")
        if key != self.tab and isinstance(loop, LoopTab):
            loop.stop_listening()  # its play head would run on unseen
        self.tab = key
        self.stack.setCurrentWidget(self.holder(key))
        if self.is_open:
            self._light_tabs()
            self.refresh()
        else:
            self.set_open(True)

    def _light_tabs(self) -> None:
        for key, button in self.tab_buttons.items():
            button.setChecked(self.is_open and key == self.tab)

    # ---------------------------------------------------------------- fold

    def set_open(self, unfolded: bool) -> None:
        if unfolded == self.is_open:
            return
        self.is_open = unfolded
        if unfolded:
            self.stack.setCurrentWidget(self.holder(self.tab))
        self.stack.setVisible(unfolded)
        self.message.setVisible(unfolded and bool(self.message.text()))
        self.fold_button.set_unfolded(unfolded)
        self._light_tabs()
        self._place()
        self.refresh()
        self.update()
        self.fold_changed.emit(unfolded)

    def toggle(self) -> None:
        self.set_open(not self.is_open)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.header_height():
            self.toggle()

    # ---------------------------------------------------------------- pad

    def set_content(self, number: int, color: str, title: str, info: str, help_text: str) -> None:
        """Badge number and colour, "Pad N", the line of facts (folded) and the key help."""
        content = (number, color, title, info, help_text)
        if content != (self.number, self.color, self.title, self.info, self.help):
            relayout = help_text != self.help
            self.number, self.color, self.title, self.info, self.help = content
            if relayout:
                self._place()
            self.update()

    def show_pad(self, pad: int) -> None:
        """Show ``pad`` in every tab (a pad was chosen)."""
        if pad == self.pad:
            return
        self.pad = pad
        self._info_key = None
        for page in self.pages.values():
            page.show_pad(pad)  # type: ignore[attr-defined]
        self.refresh()

    def place_marker(self) -> bool:
        """The key M: a marker at the cursor of the wave (only while the tab "Loop" is shown)."""
        if self.is_open and self.tab == "loop":
            return self.loop_tab.place_marker()
        return False

    def refresh(self) -> None:
        """Follow the controller (called on every tick of the main window; cheap when nothing changed)."""
        if not self.is_open:
            return
        self._update_info()
        page = self.pages.get(self.tab)
        if page is not None:
            page.refresh()  # type: ignore[attr-defined]

    def _update_info(self) -> None:
        controller = self.controller
        state = controller.pad(self.pad)
        grid = None if state.free else controller.grid_frames()
        key = (self.pad, state.sample, grid)
        if key == self._info_key:
            return
        self._info_key = key
        recorded = played = None
        if state.sample is not None:
            raw = controller.sample_audio(state.sample)
            loop = controller.loop_audio(state.sample, self.pad)
            if raw is not None and loop is not None:
                recorded, played = len(raw), len(loop)
        self.open_info = loop_title(recorded, played, grid, controller.sample_rate)
        self.update()

    # ---------------------------------------------------------------- geometry

    def help_lines(self, room: float) -> tuple[list[str], QFont]:
        """The key help in one line, or in two or three when it does not fit ``room`` px."""
        parts = self.help.split(" · ")
        lines: list[str] = [self.help]
        font = _font(14, QFont.Weight.Medium)
        # One line at 14 px, else two at 13, else three at 12 (each may give one pixel); the last way
        # shrinks the three lines further rather than cut them.
        for count, pixels, least in ((1, 14, 13), (2, 13, 12), (3, 12, 11), (3, 11, 10)):
            size = -(-len(parts) // count)  # parts per line, rounded up
            lines = [" · ".join(parts[i:i + size]) for i in range(0, len(parts), size)]
            longest = max(lines, key=QFontMetrics(_font(pixels, QFont.Weight.Medium)).horizontalAdvance)
            font = fitted_font(longest, room, pixels, QFont.Weight.Medium, least)
            if QFontMetrics(font).horizontalAdvance(longest) <= room:
                return lines, font
        metrics = QFontMetrics(font)
        return [metrics.elidedText(line, Qt.TextElideMode.ElideRight, int(room)) for line in lines], font

    def _help_strip(self) -> tuple[list[str], QFont, int]:
        """The key help under the head of the open panel: its lines, font and height."""
        if not (self.is_open and self.help):
            return [], QFont(), 0
        lines, font = self.help_lines(self.width() - 2 * MARGIN - 8)
        return lines, font, QFontMetrics(font).height() * len(lines) + 6

    def say(self, text: str, level: str = "ok") -> None:
        """``text`` under the head of the open panel, in place of the facts in the folded line ("" takes
        it away); a refused value in red."""
        color = {"ok": GOOD, "warning": WARN, "error": "#FF3B30"}.get(level, TEXT_DIM.name())
        self.message.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.message.setProperty("color", color)
        self.message.setText(text)
        self.message.setVisible(bool(text) and self.is_open)
        self._place()
        self.update()

    def shown_info(self) -> tuple[str, QColor]:
        """The line under "Pad N" as it is drawn: the facts, or (folded) a message of the settings."""
        if self.is_open:
            return self.open_info, TEXT_DIM
        if self.message.text():
            return self.message.text(), QColor(str(self.message.property("color")))
        return self.info, TEXT_DIM

    def _message_height(self) -> int:
        if self.message.isHidden():
            return 0
        return self.message.heightForWidth(max(1, self.width() - 2 * MARGIN)) + 4

    def header_height(self) -> int:
        return HEADER + self._help_strip()[2] + self._message_height()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        width = self.width()
        wide = width >= WIDE
        fold = QRectF(width - MARGIN - FOLD_SIZE.width(), (HEADER - FOLD_SIZE.height()) / 2,
                      FOLD_SIZE.width(), FOLD_SIZE.height())
        self.fold_button.setGeometry(fold.toRect())
        pixels, padding, gap = (17, 14, 48) if wide else (15, 10, 20)
        folded_help = bool(self.help) and not self.is_open
        right = fold.left() - gap
        for key, _word in reversed(TABS):
            button = self.tab_buttons[key]
            button.pixels = pixels
            tab_width = button.width_for(pixels, padding)
            right -= tab_width
            button.setGeometry(round(right), 13, tab_width, 38)
            right -= 6
        self._tabs_left = right + 6
        # Folded beside a side panel the line is narrow: the facts stay readable, a tap on the line unfolds.
        crowded = not self.is_open and self._tabs_left - 16 - BADGE_END < INFO_LEAST
        for button in self.tab_buttons.values():
            button.setVisible(not (folded_help or crowded))
        if crowded:
            self._tabs_left = fold.left() - 8
        help_height = self._help_strip()[2]
        self.message.setGeometry(MARGIN, HEADER + help_height, max(1, width - 2 * MARGIN),
                                 self._message_height())
        top = self.header_height()
        self.stack.setGeometry(MARGIN, top, max(0, width - 2 * MARGIN), max(0, self.height() - top - 14))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(400, HEADER)

    # ---------------------------------------------------------------- paint

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setPen(QPen(QColor(CARD_BORDER), 1.5))
        painter.setBrush(QColor(CARD_FILL))
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 16, 16)
        badge = QRectF(MARGIN, (HEADER - 36) / 2, 36, 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PAD_COLORS[self.color]))
        painter.drawRoundedRect(badge, 8, 8)
        painter.setFont(_font(16))
        painter.setPen(QColor("#111114"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.number))
        left = badge.right() + 16
        right = self._tabs_left - 16
        if self.help and not self.is_open:
            # Folded with the key help: the help takes the place of the tabs.
            lines, help_font = self.help_lines(rect.width() * 0.5)
            metrics = QFontMetrics(help_font)
            help_width = max(metrics.horizontalAdvance(line) for line in lines) + 4
            painter.setFont(help_font)
            painter.setPen(LABEL)
            height = metrics.height()
            top = (HEADER - height * len(lines)) / 2
            end = self.fold_button.x() - 16
            for number, line in enumerate(lines):
                box = QRectF(end - help_width, top + number * height, help_width, height)
                painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, line)
            right = end - help_width - 24
        room = max(10.0, right - left)
        draw_line(painter, QRectF(left, 8, room, 26), self.title, _font(18), TEXT)
        info, color = self.shown_info()
        said = not self.is_open and bool(self.message.text())  # a message of the settings, in bold
        weight = QFont.Weight.Bold if said else QFont.Weight.Normal
        draw_line(painter, QRectF(left, 34, room, 22), info, fitted_font(info, room, 14, weight, 12), color)
        lines, help_font, _height = self._help_strip()
        if lines:
            painter.setFont(help_font)
            painter.setPen(LABEL)
            height = QFontMetrics(help_font).height()
            for number, line in enumerate(lines):
                box = QRectF(MARGIN, HEADER - 2 + number * height, rect.width() - 2 * MARGIN, height)
                painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        painter.end()
