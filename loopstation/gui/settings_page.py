"""The parents' area: navigation, the settings pages and the settings file (mockups 09-16).

``SettingsDialog`` is the window of the parents' area. On the left it has the navigation with seven
areas; on the right one page per area. Three pages belong to it: "Lautstärke & Pegel", "Geräte & Audio"
and "Takt & Loop" (they edit ``settings.toml``). The others ("Verlauf & Undo", "Erweitert", "Sets",
"Export") are handed in as ``ParentPage`` entries and built on their first visit.

The fields are a plain list (``FIELDS``). A later package adds a setting to
the page with one entry, no change to this dialog::

    register_field(Field("auto_gain", "Auto-Gain", "bool", hint="Standard: aus."))

(plus the key in ``Settings``, its check in ``parse_settings`` and its comment
in ``config.SETTING_COMMENTS``). A field that no page names goes into the "Allgemein" card.
"""

from __future__ import annotations

import inspect
import sys
import weakref
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation.audio.devices import default_hostapi
from loopstation.audio.effects import beep
from loopstation.audio.stretch import engine_notice
from loopstation.config import (
    RESTART_KEYS,
    SIGNATURES,
    STRETCH_ENGINES,
    ConfigError,
    Settings,
    load_settings,
    parse_settings,
    settings_values,
    write_settings,
)
from loopstation.gui.devices_page import HostApiList, platform_name
from loopstation.gui.grid_panel import GridPanel
from loopstation.gui.level_panel import PANEL_KEYS, LevelPanel
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import (
    NARROW_WINDOW,
    RADIO_QSS,
    SCROLLBAR_GAP_QSS,
    BackButton,
    CardGrid,
    CurrentPageStack,
    IconLabel,
    ParentNav,
    ParentPage,
    card,
    dim_label,
    qicon,
    scrolled,
)
from loopstation.gui.peak_meter import PeakMeter
from loopstation.gui.tempo_card import MetronomeCard, TempoCard
from loopstation.gui.volume_slider import VolumeSlider
from loopstation.gui.widgets import (
    ACCENT_GREEN,
    BACKGROUND,
    DARK_SCROLLBAR_QSS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    BigButton,
    weak_slot,
)

if TYPE_CHECKING:
    from loopstation.controller import Controller

# How often the volume slider, the level scale and the loud-recordings list follow the controller (ms).
LEVEL_REFRESH_MS = 100

# Advice for parents that belongs on the page whatever fields it has
# (plan sections 3.1 and 9.3).
NOTES = (
    "Lautsprecher und Mikrofon zusammen erzeugen Echo: beim Aufnehmen lieber Kopfhörer tragen.",
    "Bluetooth-Kopfhörer sind für das Mitschneiden meist zu träge. Bitte kabelgebundene Kopfhörer benutzen.",
    "Die App begrenzt nur die Amplitude im Rechner (dB(FS)), nicht den Schalldruck am Ohr (dB(SPL)). "
    "Den bestimmen auch Systemlautstärke und Kopfhörer: am besten kabelgebundene Kinderkopfhörer "
    "mit eigener Begrenzung.",
)
# More advice of the "Für gutes Looping" card (mockup 10).
MORE_NOTES = (
    "ASIO4ALL ist nur ein Wrapper, kein echter Treiber.",
    "Gerät fehlt? Der Systemstandard wird genutzt, die Statuszeile sagt es.",
)

RESTART_TEXT = "wirkt nach Neustart"
SUBTITLE = "Änderungen gelten sofort · gespeichert in settings.toml"
FOOTER = "Lokal · ohne Konto · ohne Internet\nNeustart nötig nur für: " + ", ".join(RESTART_KEYS)

# Words in a device name that make a poor recording and playback device (plan 8).
BLUETOOTH_WORDS = ("bluetooth", "airpods", "bt-", "bt ", "a2dp", "hands-free")
BLUETOOTH_WARNING = "⚠ Bluetooth ist für Aufnahmen meist zu langsam."
STANDARD_TEXT = "Systemstandard"
ASIO_WARNING = (
    "ASIO ist für Audio-Interfaces gedacht. Viele Treiber öffnen das Gerät exklusiv: andere Programme "
    "sind dann still. ASIO4ALL ist nur ein Wrapper, kein echter Treiber. Wirkt erst nach einem Neustart.")
TEST_TONE_HZ = 440.0
TEST_TONE_SECONDS = 0.7
TEST_TONE_LEVEL = 0.12  # linear, before the volume and the ceiling (about -18 dBFS)


def _held_weakly(apply: Callable[[Settings], list[str]]) -> Callable[[Settings], list[str]]:
    """``apply`` as the dialog should keep it: a method of the main window is held weakly.

    The main window owns this dialog; if the dialog held the window's method strongly the two would be
    a reference cycle that only the garbage collector frees, at any later time and in any order
    (see ``weak_slot``). A function or lambda is kept as it is.
    """
    if not inspect.ismethod(apply):
        return apply
    target = weakref.WeakMethod(apply)

    def call(settings: Settings) -> list[str]:
        method = target()
        return method(settings) if method is not None else []

    return call


@dataclass(frozen=True)
class Field:
    """One row of the page. ``kind``: ``bool``, ``int``, ``float``, ``auto_float``, ``choice`` or ``text``."""

    key: str
    label: str
    kind: str
    low: float = 0
    high: float = 1000
    hint: str = ""
    suffix: str = ""
    choices: tuple[str, ...] = ()

    @property
    def restart(self) -> bool:
        return self.key in RESTART_KEYS


FIELDS: list[Field] = [
    Field("loop_sync", "Loops im Takt halten", "bool",
          hint="Die erste Aufnahme bestimmt die Loop-Länge, alle weiteren passen dazu."),
    Field("soft_seam", "Weiche Loop-Naht", "bool",
          hint="Blendet das Ende jedes Loops kurz aus und den Anfang ganz kurz ein, damit es nicht "
               "knackt. Der erste Schlag bleibt dabei hörbar."),
    Field("sound_effects", "Piepton bei Aufnahme", "bool"),
    Field("record_start_tone", "Aufnahmestart-Ton", "bool",
          hint="Der Ton klingt aus, bevor die Aufnahme beginnt, und ist nie auf ihr zu hören."),
    Field("max_record_seconds", "Längste Aufnahme", "float", 1, 120, suffix=" s"),
    Field("latency_ms", "Latenz Lautsprecher zu Mikrofon", "auto_float", 0, 1000, suffix=" ms",
          hint="Der Auto-Wert hängt vom Gerät ab. Mit Mikrofon und Kopfhörer gegenhören: "
               "klingen neue Loops zu spät, die Zahl erhöhen."),
    Field("volume", "Lautstärke", "float", 0, 1,
          hint="0 ist still, 1 ist die Obergrenze. Der Regler im Fenster stellt dasselbe ein."),
    Field("max_level_db", "Obergrenze", "float", -30, 0, suffix=" dB",
          hint="Die Ausgabe wird nie lauter als dieser Wert."),
    Field("input_gain_db", "Mikrofonpegel", "float", -24, 24, suffix=" dB"),
    Field("auto_gain", "Aufnahmepegel ausgleichen", "bool"),
    Field("peak_meter", "Pegelanzeige bei Aufnahme", "bool"),
    Field("launchpad", "Launchpad benutzen", "bool"),
    Field("fullscreen", "Vollbild", "bool"),
    Field("parent_unlock_minutes", "Schloss offen lassen", "int", 0, 15, suffix=" min",
          hint="So lange darf erneutes Halten des Schlosses die Elternansicht ohne Rechenaufgabe öffnen, "
               "wenn die Eltern es in der Aufgabe einschalten. 0 = immer fragen."),
    Field("parent_idle_minutes", "Zurück zur Kinderseite nach", "int", 0, 240, suffix=" min",
          hint="Ohne Eingabe kehrt die Elternansicht nach dieser Zeit zur Kinderseite zurück. 0 = nie."),
    Field("rows", "Zeilen", "int", 1, 16),
    Field("cols", "Spalten", "int", 1, 16),
    Field("sample_rate", "Abtastrate", "int", 8000, 192000, suffix=" Hz"),
    Field("data_dir", "Datenordner", "text"),
]

# The device section (own cards, see ``SettingsDialog._devices_page``): the audio system, the two
# drop-downs and the ASIO switch. Not part of FIELDS, which are plain rows.
DEVICE_KEYS = ("audio_hostapi", "input_device", "output_device", "asio")

# Which area shows a plain field. The level keys are on "Lautstärke & Pegel" (``PANEL_KEYS``); the latency
# has its own card on "Geräte & Audio"; a field that is in no list goes into the "Allgemein" card.
LOOP_SWITCHES = ("auto_grid", "loop_sync", "stretch_to_grid", "free_pad_on_grid", "metronome_tone")
LOOP_NUMBERS = ("time_signature", "grid_bpm_min", "grid_bpm_max", "metronome_level_db", "max_record_seconds")
LATENCY_KEY = "latency_ms"


def register_field(field: Field, before: str | None = None) -> None:
    """Add ``field`` to the page (at the end, or in front of the field ``before``)."""
    if any(f.key == field.key for f in FIELDS):
        raise ValueError(f"Feld '{field.key}' gibt es schon")
    index = next((i for i, f in enumerate(FIELDS) if f.key == before), len(FIELDS))
    FIELDS.insert(index, field)


class ToggleSwitch(QAbstractButton):
    """On/off switch (green and knob right = on), as in the parents' area mockup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(QSize(64, 36))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT_GREEN) if self.isChecked() else QColor("#48484E"))
        painter.drawRoundedRect(QRectF(self.rect()), 18, 18)
        knob_x = self.width() - 32 if self.isChecked() else 4
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(knob_x, 4, 28, 28))
        painter.end()


class _ChoiceEditor:
    """A drop-down of (label, value) pairs; ``value()`` is the stored text ("" = system default)."""

    def __init__(self, field: Field, value: str) -> None:
        self.field = field
        self.box = QComboBox()
        self.widget: QWidget = self.box
        self.set_choices([], value)

    def set_choices(self, choices: list[tuple[str, str]], selected: str) -> None:
        """Show ``choices`` after the standard entry; an unlisted ``selected`` value stays (marked)."""
        entries = [(STANDARD_TEXT, ""), *choices]
        if selected and all(value != selected for _label, value in entries):
            entries.append((f"{selected} (nicht gefunden)", selected))
        self.box.blockSignals(True)
        self.box.clear()
        for label, value in entries:
            self.box.addItem(label, value)
        self.box.setCurrentIndex(max(0, self.box.findData(selected)))
        self.box.blockSignals(False)

    def value(self) -> str:
        return str(self.box.currentData() or "")

    def others(self) -> list[str]:
        """The labels of the entries that are not the chosen one."""
        current = self.box.currentIndex()
        return [self.box.itemText(i) for i in range(self.box.count()) if i != current]


class _HostApiEditor:
    """The audio system as a radio list (``HostApiList``) with the editor interface of the page."""

    def __init__(self, field: Field, value: str) -> None:
        self.field = field
        self.list = HostApiList(value)
        self.widget: QWidget = self.list

    def set_choices(self, choices: list[tuple[str, str]], selected: str) -> None:
        self.list.set_choices(choices, selected)

    def value(self) -> str:
        return self.list.value()


class _Editor:
    """The input widget of one field and how to read and set its value."""

    def __init__(self, field: Field, value: Any) -> None:
        self.field = field
        self.widget: QWidget
        self._auto: QRadioButton | None = None
        self.auto_note: QLabel | None = None
        kind = field.kind
        if kind == "bool":
            self._box = ToggleSwitch()
            self._box.setChecked(bool(value))
            self.widget = self._box
        elif kind == "choice":
            self._combo = QComboBox()
            self._combo.addItems(list(field.choices))
            self._combo.setCurrentText(str(value))
            self.widget = self._combo
        elif kind == "text":
            self._edit = QLineEdit(str(value))
            self.widget = self._edit
        elif kind == "int":
            self._spin = QSpinBox()
            self._spin.setRange(int(field.low), int(field.high))
            self._spin.setValue(int(value))
            self._spin.setSuffix(field.suffix)
            self.widget = self._spin
        else:  # float, auto_float
            self._dspin = QDoubleSpinBox()
            self._dspin.setRange(field.low, field.high)
            self._dspin.setDecimals(1)
            self._dspin.setSuffix(field.suffix)
            self._dspin.setValue(float(value) if value is not None else field.low)
            self.widget = self._dspin
            if kind == "auto_float":
                self._dspin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
                self._dspin.setFixedWidth(120)
                self._dspin.setAlignment(Qt.AlignmentFlag.AlignRight)
            if kind == "auto_float":
                self._build_auto(value)

    def _build_auto(self, value: Any) -> None:
        """"Automatisch" (recommended) or "Von Hand" with a number (mockup 10, card "Verzögerung")."""
        self._auto = QRadioButton("Automatisch")
        self._manual = QRadioButton("Von Hand")
        group = QButtonGroup(self._auto)
        group.addButton(self._auto)
        group.addButton(self._manual)
        self._auto.setChecked(value is None)
        self._manual.setChecked(value is not None)
        self._dspin.setEnabled(value is not None)
        self._manual.toggled.connect(self._dspin.setEnabled)
        for radio in (self._auto, self._manual):
            radio.setStyleSheet("font-size: 16px; font-weight: 500;")
        badge = QLabel("empfohlen")
        badge.setStyleSheet(f"color: {PARENT_ACCENT}; background: #2E3355; font-size: 11.5px; "
                            "font-weight: bold; border-radius: 10px; padding: 2px 10px;")
        first = QHBoxLayout()
        first.setSpacing(10)
        first.addWidget(self._auto)
        first.addWidget(badge)
        first.addStretch(1)
        self.auto_note = dim_label("", 13)
        self.auto_note.setContentsMargins(30, 0, 0, 0)
        second = QHBoxLayout()
        second.setSpacing(16)
        second.addWidget(self._manual)
        second.addWidget(self._dspin)
        second.addStretch(1)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addLayout(first)
        column.addWidget(self.auto_note)
        column.addSpacing(4)
        column.addLayout(second)
        self.widget = holder

    def value(self) -> Any:
        kind = self.field.kind
        if kind == "bool":
            return self._box.isChecked()
        if kind == "choice":
            return self._combo.currentText()
        if kind == "text":
            return self._edit.text()
        if kind == "int":
            return self._spin.value()
        if self._auto is not None and self._auto.isChecked():
            return "auto"
        return self._dspin.value()


class SettingsDialog(QDialog):
    """The parents' area: navigation and pages; edits ``settings.toml`` and hands the result to ``apply``.

    ``apply(settings)`` takes over the live values and returns the keys that
    need a restart. A refused value is shown in the dialog and nothing is written.

    With a ``controller`` (or a parent window that has one) the page also has
    the volume slider at the top right, the level section (``LevelPanel``), the current bar and the
    tempo correction; the level controls act at once, the rest of the settings waits for "Speichern".
    ``pages`` are the further areas (history, Erweitert, sets, export), built on their first visit; a page
    with a ``done(bool)`` signal can end the visit (``True`` ends the parents' area, ``False`` goes back).
    """

    def __init__(
        self,
        config_path: Path,
        running: Settings,
        apply: Callable[[Settings], list[str]],
        template: str | None = None,
        parent: QWidget | None = None,
        pages: Sequence[ParentPage] = (),
        controller: Controller | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.running = running
        self._apply = _held_weakly(apply)
        self._template = template
        self._applied = running  # what the controller runs now (live values)
        self.saved = False
        self.setWindowTitle("Elternbereich")
        self.setModal(True)
        self.setStyleSheet(
            f"SettingsDialog {{ background: {BACKGROUND.name()}; border: 5px solid {PARENT_ACCENT}; }} "
            f"QScrollArea, #scroll_inner, QStackedWidget {{ background: transparent; border: none; }} "
            f"QLabel, QCheckBox, QRadioButton {{ color: {TEXT.name()}; font-size: 16px; }} "
            "#card { background: #1B1B1F; border: 1.5px solid #2C2C31; border-radius: 18px; } "
            f"QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {{ color: {TEXT.name()}; "
            f"background: {SURFACE.name()}; "
            f"font-size: 16px; border: 1px solid {PARENT_ACCENT}; border-radius: 10px; padding: 6px 10px; }} "
            "QComboBox { border: 1.5px solid #3A3A41; border-radius: 14px; padding: 12px 16px; "
            "font-weight: 600; } "
            "QComboBox::drop-down { border: none; width: 28px; } "
            f"QComboBox QAbstractItemView {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
            f"selection-background-color: {PARENT_ACCENT}; selection-color: #000000; font-size: 16px; }} "
            "QSpinBox:disabled, QDoubleSpinBox:disabled { color: #5A5A60; border-color: #3A3A41; } "
            "QCheckBox::indicator { width: 22px; height: 22px; border-radius: 5px; "
            f"background: {SURFACE.name()}; border: 1px solid #5A5A60; }} "
            f"QCheckBox::indicator:checked {{ background: {ACCENT_GREEN.name()}; }} "
            "QPushButton#secondary { color: #F2F2F2; background: #26262B; border: 1.5px solid #3A3A41; "
            "border-radius: 12px; font-size: 16px; font-weight: 700; min-height: 44px; padding: 0 22px; } "
            "QPushButton#secondary:pressed { background: #3A3A41; } "
            + RADIO_QSS + DARK_SCROLLBAR_QSS + SCROLLBAR_GAP_QSS)

        # Header: the lock, the title, what the page does (or what the last action did), the volume.
        self.close_button = BackButton()
        self.close_button.setToolTip("Eltern-Modus beenden")
        self.close_button.clicked.connect(self.reject)
        title = QLabel("Elternbereich")
        title.setStyleSheet("font-size: 30px; font-weight: 800;")
        self.subtitle = QLabel(SUBTITLE)
        self.subtitle.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px;")
        self.subtitle.setWordWrap(True)  # wraps in a narrow window instead of widening it
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.hide()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addStretch(1)
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        title_box.addWidget(self.message)
        title_box.addStretch(1)
        lock = QVBoxLayout()
        lock.addSpacing(26)
        lock.addWidget(IconLabel("unlock", PARENT_ACCENT, 34))
        lock.addStretch(1)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addLayout(lock)
        header.addLayout(title_box, 1)

        self.editors: dict[str, Any] = {}
        shown = self._file_settings()
        values = settings_values(shown)
        self.controller = controller if controller is not None else getattr(parent, "controller", None)
        self.panel: LevelPanel | None = None
        self.grid_panel: GridPanel | None = None
        self.tempo_card: TempoCard | None = None
        self.metronome_card: MetronomeCard | None = None
        self.mic_meter: PeakMeter | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_levels)
        self.volume_slider: VolumeSlider | None = None
        if self.controller is not None:
            self.volume_slider = VolumeSlider(captions=True)
            self.volume_slider.setMinimumWidth(260)
            self.volume_slider.setMaximumWidth(384)
            self.volume_slider.volumeChanged.connect(self.controller.set_volume)
            header.addWidget(self.volume_slider, 0)
            self.grid_panel = GridPanel(self.controller)
            self.tempo_card = TempoCard(self.controller)
            self.metronome_card = MetronomeCard(self.controller)
            panel_fields = {f.key: f for f in FIELDS if f.key in PANEL_KEYS}
            self.panel = LevelPanel(self.controller, values, panel_fields, ToggleSwitch)
            self.panel.edited.connect(self._level_edited)
            self.editors.update(self.panel.editors)
        self._pending = [f.label for f in FIELDS if f.restart and values[f.key] != getattr(running, f.key)]
        self._source = getattr(parent, "audio_devices", None)
        self._applied = running
        self._placed: set[str] = set(self.editors)  # fields that already have their row on a page
        for field in FIELDS:
            if field.key not in self.editors:
                self.editors[field.key] = _Editor(field, values[field.key])

        # The navigation and the pages.
        self.stack = CurrentPageStack()
        self._widgets: dict[str, QWidget] = {}
        self._builders: dict[str, ParentPage] = {}
        self.nav = ParentNav(self.close_button, FOOTER)
        self.nav.selected.connect(weak_slot(self.show_page, pass_signal_args=True))
        # The devices page comes last: its "Allgemein" card takes every field no other page has.
        levels, tempo = self._levels_page(), self._tempo_page()
        devices = self._devices_page(values)
        own = (
            ("levels", "sliders", "Lautstärke & Pegel", levels),
            ("devices", "headphones", "Geräte & Audio", devices),
            ("tempo", "pulse", "Takt & Loop", tempo),
        )
        for key, icon, label, widget in own:
            self.nav.add_button(key, icon, label)
            self._widgets[key] = widget
            self.stack.addWidget(widget)
        for page in pages:
            self.nav.add_button(page.key, page.icon, page.label)
            self._builders[page.key] = page
        self.save_button = BigButton(
            "check", "Speichern", QColor(PARENT_ACCENT), checkable=True, font_pt=13, pad_x=16, min_height=48)
        self.save_button.setChecked(True)  # filled: the one main action
        self.save_button.clicked.connect(self._save_clicked)
        self.nav.add_bottom(self.save_button)
        self.nav.add_bottom(self._spacer(10))
        self.nav.finish()
        self.page_keys = [key for key, *_ in own] + [page.key for page in pages]

        right = QVBoxLayout()
        right.setSpacing(20)
        header_box = QWidget()
        header_box.setFixedHeight(104)
        header_box.setLayout(header)
        header.setContentsMargins(0, 0, 0, 0)
        right.addWidget(header_box)
        right.addWidget(self.stack, 1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(24)
        layout.addWidget(self.nav)
        layout.addLayout(right, 1)
        self.resize(1280, 800)
        tone = self.editors.get("metronome_tone")
        if self.controller is not None and tone is not None:
            # The quiet metronome tick acts at once (the file keeps its value until "Speichern").
            tone._box.toggled.connect(weak_slot(self._tone_toggled, pass_signal_args=True))
        self.show_page("levels")
        if self._pending:
            self._say(f"Gespeichert, {RESTART_TEXT}: " + ", ".join(self._pending), warning=True)

    def _tone_toggled(self, on: bool) -> None:
        controller = self.controller
        if controller is not None and controller.settings.metronome_tone != on:
            controller.apply_settings(replace(controller.settings, metronome_tone=on))

    @staticmethod
    def _spacer(height: int) -> QWidget:
        spacer = QWidget()
        spacer.setFixedHeight(height)
        return spacer

    # ------------------------------------------------------------------ pages

    def show_page(self, key: str) -> None:
        """Show the area ``key``; an area handed in by ``pages`` is built now if this is its first visit."""
        widget = self.page(key)
        self.nav.set_current(key)
        self.stack.setCurrentWidget(widget)

    def page(self, key: str) -> QWidget:
        """The widget of the area ``key``, built (not shown) if it was not yet."""
        widget = self._widgets.get(key)
        if widget is None:
            widget = self._builders[key].build()
            self._widgets[key] = widget
            self.stack.addWidget(widget)
            done = getattr(widget, "done", None)
            if done is not None:
                done.connect(weak_slot(self._page_done, pass_signal_args=True))
        return widget

    def current_key(self) -> str:
        return next(key for key, widget in self._widgets.items() if widget is self.stack.currentWidget())

    def _page_done(self, opened: bool) -> None:
        """An area is finished: a set was opened (leave the parents' area), or the visit was cancelled."""
        if opened:
            self.accept()
        else:
            self.show_page(self.page_keys[0])

    def _fields_of(self, keys: Iterable[str]) -> list[Field]:
        """The plain fields among ``keys`` that have no row yet, in the order of ``FIELDS``."""
        by_key = {f.key: f for f in FIELDS}
        found = [by_key[key] for key in dict.fromkeys(keys) if key in by_key and key not in self._placed]
        self._placed.update(f.key for f in found)
        return found

    def _rows(self, fields: Iterable[Field]) -> tuple[QVBoxLayout, QFormLayout]:
        """Switches as switch rows, everything else as form rows."""
        switches, numbers = QVBoxLayout(), QFormLayout()
        switches.setSpacing(14)
        numbers.setHorizontalSpacing(24)
        numbers.setVerticalSpacing(12)
        for field in fields:
            editor = self.editors[field.key]
            label = field.label + (f" ({RESTART_TEXT})" if field.restart else "")
            if field.kind == "bool":
                switches.addLayout(self._switch_row(editor, label, field.hint))
            else:
                row = QVBoxLayout()
                row.setSpacing(2)
                row.addWidget(editor.widget)
                if field.hint:
                    row.addWidget(self._hint(field.hint))
                if field.key == "stretch_engine":
                    self._engine_hint = self._hint("")
                    editor._combo.currentTextChanged.connect(self._update_engine_hint)
                    self._update_engine_hint(editor.value())
                    row.addWidget(self._engine_hint)
                numbers.addRow(label, row)
        return switches, numbers

    def _rows_card(self, title: str, fields: list[Field], subtitle: str = "") -> QFrame:
        """A card with the rows of ``fields`` (switches above, number rows below)."""
        frame, layout = card(title, subtitle)
        switches, numbers = self._rows(fields)
        if switches.count():
            layout.addLayout(switches)
        if numbers.rowCount():
            layout.addLayout(numbers)
        return frame

    @staticmethod
    def _page(*widgets: QWidget) -> QWidget:
        """A page: the cards one under the other, in a scroll area."""
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return scrolled(inner)

    def _levels_page(self) -> QWidget:
        if self.panel is not None:
            return self._page(self.panel)
        return self._page(self._rows_card("Lautstärke und Pegel", self._fields_of(PANEL_KEYS)))

    def _tempo_page(self) -> QWidget:
        switches = self._rows_card("Loop-Verhalten", self._fields_of(LOOP_SWITCHES))
        numbers = self._rows_card("Zahlenwerte", self._fields_of(LOOP_NUMBERS))
        if self.controller is None or self.grid_panel is None or self.tempo_card is None:
            return self._page(switches, numbers)
        assert self.metronome_card is not None
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self.grid_panel)
        layout.addWidget(CardGrid([[self.tempo_card, switches]], ratio=(1, 1), gap=20, stretch_last=True))
        layout.addWidget(self.metronome_card)
        layout.addWidget(numbers)
        layout.addStretch(1)
        return scrolled(inner)

    # -------------------------------------------------- devices and audio system

    def _devices_page(self, values: dict[str, Any]) -> QWidget:
        """Microphone and speaker, audio system, latency, advice, and the plain "Allgemein" fields."""
        fields = {
            "audio_hostapi": Field("audio_hostapi", "Audio-System", "choice"),
            "input_device": Field("input_device", "Mikrofon (Eingang)", "choice"),
            "output_device": Field("output_device", "Lautsprecher / Kopfhörer (Ausgang)", "choice"),
        }
        self.editors["audio_hostapi"] = _HostApiEditor(fields["audio_hostapi"], str(values["audio_hostapi"]))
        for key in ("input_device", "output_device"):
            self.editors[key] = _ChoiceEditor(fields[key], str(values[key]))
        self._asio = _Editor(Field("asio", "ASIO zulassen (nur Windows)", "bool"), values["asio"])
        self.editors["asio"] = self._asio
        self._placed.update(DEVICE_KEYS)
        self.editors["audio_hostapi"].list.changed.connect(weak_slot(self._hostapi_changed))
        for key in ("input_device", "output_device"):
            self._choice(key).box.currentIndexChanged.connect(weak_slot(self._update_device_hints))

        self.device_hint = dim_label("", 13, "#FF9F0A")
        mic, mic_layout = card("Mikrofon (Eingang)", icon="mic", spacing=10)
        mic_layout.addWidget(self.editors["input_device"].widget)
        self.mic_others = dim_label("", 13)
        if self.controller is not None:
            mic_layout.addWidget(dim_label(
                "Pegel der letzten Aufnahme (das Mikrofon ist nur beim Aufnehmen offen)", 13))
            self.mic_meter = PeakMeter()
            mic_layout.addWidget(self.mic_meter)
        mic_layout.addWidget(self.mic_others)
        mic_layout.addStretch(1)

        out, out_layout = card("Lautsprecher / Kopfhörer (Ausgang)", icon="headphones", spacing=10)
        out_layout.addWidget(self.editors["output_device"].widget)
        self.tone_button: QPushButton | None = None
        if self.controller is not None:
            self.tone_button = QPushButton(" Testton abspielen")
            self.tone_button.setIcon(qicon("play", TEXT, 24))
            self.tone_button.setObjectName("secondary")
            self.tone_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tone_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.tone_button.setToolTip("Ein kurzer, leiser Ton auf dem Ausgang, der gerade läuft")
            self.tone_button.clicked.connect(weak_slot(self.play_test_tone))
            out_layout.addWidget(self.tone_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.out_others = dim_label("", 13)
        out_layout.addWidget(self.out_others)
        out_layout.addWidget(self.device_hint)
        out_layout.addStretch(1)

        system = platform_name()
        audio, audio_layout = card("Audio-System" + (f" ({system})" if system else ""),
                                   "Nur ändern, wenn nötig. Stream startet kurz neu.", spacing=8)
        audio_layout.addWidget(self.editors["audio_hostapi"].widget)
        self._asio_row = QWidget()
        asio_layout = QVBoxLayout(self._asio_row)
        asio_layout.setContentsMargins(0, 6, 0, 0)
        asio_layout.addLayout(self._switch_row(
            self._asio, "ASIO zulassen (nur Windows, " + RESTART_TEXT + ")", ASIO_WARNING))
        self._asio_row.setVisible(sys.platform.startswith("win"))  # ASIO exists on Windows only
        audio_layout.addWidget(self._asio_row)
        audio_layout.addStretch(1)
        audio_layout.addWidget(dim_label(
            "Der Wechsel gilt sofort, die Audio-Streams starten dafür kurz neu. "
            "Fehlt ein Gerät, wird der Systemstandard genutzt (Hinweis in der Statuszeile). "
            "Für ein und aus am besten dasselbe Interface wählen: zwei Geräte können gegeneinander driften."))

        latency_field = next((f for f in FIELDS if f.key == LATENCY_KEY), None)
        right_cards: list[QWidget] = []
        if latency_field is not None:
            self._placed.add(LATENCY_KEY)
            latency, latency_layout = card("Verzögerung (Latenz)", spacing=6)
            editor = self.editors[LATENCY_KEY]
            latency_layout.addWidget(editor.widget)
            self.latency_hint = editor.auto_note or dim_label("", 13)
            latency_layout.addWidget(dim_label(
                "Wird nach Geräte-/System-Wechsel neu berechnet. " + latency_field.hint, 13))
            right_cards.append(latency)
        else:
            self.latency_hint = dim_label("", 13)
        notes_card = QFrame()
        notes_card.setObjectName("notes")
        notes_card.setStyleSheet("#notes { background: rgba(255, 159, 10, 23); border: 1.5px solid "
                                 "rgba(255, 159, 10, 102); border-radius: 18px; }")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(22, 16, 22, 16)
        notes_layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconLabel("alert", "#FF9F0A", 26))
        title = QLabel("Für gutes Looping")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        head.addWidget(title, 1)
        notes_layout.addLayout(head)
        for text in (*NOTES, *MORE_NOTES):
            note = self._hint("• " + text)
            note.setStyleSheet(f"color: {TEXT.name()}; font-size: 14px;")
            notes_layout.addWidget(note)
        right_cards.append(notes_card)
        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(14)
        for widget in right_cards:
            right_column.addWidget(widget)
        right_column.addStretch(1)

        general = self._rows_card("Allgemein", self._general_fields())
        self._fill_devices()
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(CardGrid([[mic, out], [audio, right]], ratio=(1, 1), gap=20, spacing=14))
        layout.addWidget(general)
        layout.addStretch(1)
        return scrolled(inner)

    def _general_fields(self) -> list[Field]:
        """Every plain field no other area has taken (rows, cols, launchpad, data folder, ...)."""
        return self._fields_of(f.key for f in FIELDS)

    def play_test_tone(self) -> None:
        """A short quiet tone on the running output, through the same volume and ceiling as the loops."""
        if self.controller is None:
            return
        tone = beep(TEST_TONE_HZ, TEST_TONE_SECONDS, self.controller.sample_rate, TEST_TONE_LEVEL)
        self.controller.audio.play_effect(tone)

    def _choice(self, key: str) -> _ChoiceEditor:
        return self.editors[key]  # type: ignore[return-value]

    def _hostapi_changed(self) -> None:
        self._fill_devices(reset_devices=True)

    def _fill_devices(self, reset_devices: bool = False) -> None:
        """Fill the audio systems and, for the chosen one, the microphone and speaker lists.

        ``reset_devices``: the audio system was just changed, so a device that
        the new one does not offer goes back to the system default.
        """
        hostapi = self.editors["audio_hostapi"].value()
        source = self._source
        if source is None:
            self.editors["audio_hostapi"].set_choices([], hostapi)
            for key in ("input_device", "output_device"):
                self._choice(key).set_choices([], self._choice(key).value())
            self._update_device_hints()
            return
        groups = {"input": source.device_groups("input"), "output": source.device_groups("output")}
        names = list(dict.fromkeys(g.name for kind in groups.values() for g in kind))
        self.editors["audio_hostapi"].set_choices([(name, name) for name in names], hostapi)
        shown = self.editors["audio_hostapi"].value()
        for key, kind in (("input_device", "input"), ("output_device", "output")):
            listed = shown or default_hostapi([g.name for g in groups[kind]], sys.platform)
            members = [d.name for g in groups[kind] if g.name == listed for d in g.devices]
            editor = self._choice(key)
            current = editor.value()
            if reset_devices and current not in members:
                current = ""
            editor.set_choices([(n, n) for n in dict.fromkeys(members)], current)
        self._update_device_hints()

    def _update_device_hints(self) -> None:
        warn = []
        for key in ("input_device", "output_device"):
            name = self._choice(key).value().lower()
            if any(word in name for word in BLUETOOTH_WORDS):
                warn.append(BLUETOOTH_WARNING)
                break
        self.device_hint.setText(" ".join(warn))
        for key, label in (("input_device", self.mic_others), ("output_device", self.out_others)):
            others = self._choice(key).others()
            label.setText("Andere: " + " · ".join(others) if others else "")
        latency = getattr(self._source, "reported_latency_ms", lambda: None)()
        self.latency_hint.setText("" if latency is None else f"aus den Geräten ermittelt: {latency:.0f} ms")

    def _update_engine_hint(self, choice: str) -> None:
        """Which stretch engine runs for ``choice``, and why (Rubber Band missing or not)."""
        self._engine_hint.setText(engine_notice(choice))

    @staticmethod
    def _hint(text: str) -> QLabel:
        return dim_label(text, 13)

    def _switch_row(self, editor: _Editor, label: str, hint: str) -> QHBoxLayout:
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        texts.addWidget(name)
        if hint:
            texts.addWidget(self._hint(hint))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(editor.widget, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        return row

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self.controller is not None:
            self.refresh_levels()
            self._timer.start(LEVEL_REFRESH_MS)
        # Fill the window it was opened from, like the page in the mockup.
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            self.setGeometry(parent.geometry())

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        self.nav.set_narrow(event.size().width() < NARROW_WINDOW)
        super().resizeEvent(event)

    def refresh_levels(self) -> None:
        """Let the volume slider, the level scale and the loud-recordings list follow the controller."""
        if self.controller is None or self.volume_slider is None or self.panel is None:
            return
        self.volume_slider.set_state(self.controller.volume, self.controller.volume_limit)
        self.panel.refresh()
        if self.grid_panel is not None:
            self.grid_panel.refresh()
        if self.tempo_card is not None:
            self.tempo_card.refresh()
        if self.mic_meter is not None:
            level, hold = self.controller.meter_levels()
            self.mic_meter.setEnabled(self.controller.peak_meter)
            self.mic_meter.set_state(level, hold, self.controller.input_clipping())



    def _level_edited(self, key: str, value: Any, final: bool) -> None:
        """A control of the level section changed: the controller takes it over at once.

        ``settings.toml`` is written when ``final`` is true (a switch, the end
        of a drag, a key press); the other fields of the page stay as they are
        until "Speichern".
        """
        live = replace(self._applied, **{key: value})
        if not final:
            # While dragging only the level setter acts; the page-wide takeover waits for the release.
            setter = {"max_level_db": "set_max_level_db", "input_gain_db": "set_input_gain_db"}.get(key)
            if setter is not None and self.controller is not None:
                getattr(self.controller, setter)(value)
                self._applied = live
                self.refresh_levels()
                return
        else:
            try:
                # A damaged file is never overwritten from here; a missing one is written new.
                base = load_settings(self.config_path) if self.config_path.exists() else self._applied
                changes = {key: value, "volume": self.editors["volume"].value()}
                write_settings(self.config_path, replace(base, **changes), self._template)
            except (ConfigError, OSError) as exc:
                self._say(str(exc), error=True)
                return
            self._say("Pegelwert übernommen und gespeichert.")
        self._applied = live
        self._apply(live)
        self.refresh_levels()

    def _file_settings(self) -> Settings:
        """What the file says now (it may hold restart values not running yet), else the running ones."""
        try:
            return load_settings(self.config_path)
        except ConfigError:
            return self.running

    def _say(self, text: str, warning: bool = False, error: bool = False) -> None:
        """Show ``text`` in the place of the subtitle (green: done, orange: needs a restart, red: refused)."""
        color = "#FF3B30" if error else "#FF9F0A" if warning else "#32D74B"
        self.message.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.subtitle.setVisible(not text)

    def _save_clicked(self) -> None:
        self.save_button.setChecked(True)  # keep it filled after the click toggled it
        self.save()

    def collect(self) -> Settings:
        """The settings the widgets show, checked like the loader checks the file."""
        raw = {key: editor.value() for key, editor in self.editors.items()}
        return parse_settings(raw, str(self.config_path))

    def save(self) -> bool:
        """Check, write the file, take over the live values. False (and nothing written) if refused."""
        try:
            new = self.collect()
            write_settings(self.config_path, new, self._template)
        except (ConfigError, OSError) as exc:
            self._say(str(exc), error=True)
            return False
        restart = self._apply(new)
        switched = any(getattr(new, key) != getattr(self._applied, key)
                       for key in ("input_device", "output_device", "audio_hostapi"))
        self.saved = True
        labels = {f.key: f.label for f in FIELDS}
        labels["asio"] = "ASIO"
        self._applied = new
        if restart:
            names = ", ".join(labels.get(key, key) for key in restart)
            self._say(f"Gespeichert, {RESTART_TEXT}: {names}", warning=True)
        elif switched:
            hint = str(getattr(self._source, "device_notice", "") or "")
            self._say("Gespeichert, Audio wurde kurz neu gestartet." + (f" {hint}" if hint else ""),
                      warning=bool(hint))
            self._update_device_hints()
        else:
            self._say("Gespeichert und übernommen.")
        return True


# --- Onset grid (W2-ONSET-GRID) ---
register_field(Field("auto_grid", "Takt aus Klatschen erkennen", "bool",
                     hint="Onset/Auto-Grid: die erste Aufnahme beginnt beim ersten Schlag und kann ihren "
                          "Takt aus dem Abstand der Schläge bekommen. Aus = Aufnahmelänge wird Takt."),
               before="soft_seam")
register_field(Field("time_signature", "Taktart", "choice", choices=tuple(SIGNATURES),
                     hint="Ein Takt besteht aus so vielen Schlägen wie die Taktart (4/4 = 4). "
                          "Gilt ab der nächsten ersten Aufnahme."),
               before="latency_ms")
register_field(Field("snap_markers", "Marker auf Transienten einrasten", "bool",
                     hint="Ein gesetzter Marker rastet auf den nächsten Schlag in der Nähe ein; ohne Schlag "
                          "bleibt er, wo er ist."),
               before="latency_ms")
register_field(Field("grid_bpm_min", "Langsamstes Tempo für den Takt", "float", 20, 300, suffix=" BPM"),
               before="latency_ms")
register_field(Field("grid_bpm_max", "Schnellstes Tempo für den Takt", "float", 20, 300, suffix=" BPM",
                     hint="Außerhalb dieses Fensters entsteht kein Takt aus Schlägen."),
               before="latency_ms")


# --- Stretch into the grid (W3-STRETCH-INT) ---
register_field(Field("stretch_to_grid", "Aufnahmen weich in den Takt ziehen", "bool",
                     hint="Knapp neben einem ganzen Takt: auf den Takt ziehen statt auffüllen oder "
                          "schneiden. Aufnahmen über laufenden Loops werden nur geschnitten oder "
                          "aufgefüllt, nie gestreckt. Aus = immer auffüllen oder schneiden."),
               before="soft_seam")


# --- Stretch engine (W3-RUBBERBAND) ---
register_field(Field("stretch_engine", "Stretch-Engine", "choice", choices=STRETCH_ENGINES,
                     hint="auto = Rubber Band, wenn vorhanden (sauberer), sonst still der einfache Stretch. "
                          "rubberband = Rubber Band gewünscht, fehlt es, steht hier ein Hinweis. "
                          "simple = immer der einfache."),
               before="latency_ms")


# --- Metronome (W3-ERWEITERT) ---
register_field(Field("metronome_tone", "Metronom-Ton (leise)", "bool",
                     hint="Ein leiser Ton auf jedem Schlag des Takts. Während einer Aufnahme "
                          "schweigt er, damit er nie auf der Aufnahme landet."),
               before="latency_ms")
register_field(Field("metronome_level_db", "Pegel des Metronom-Tons", "float", -40, -6, suffix=" dB",
                     hint="Vor Lautstärke und Obergrenze; leise gewählt, damit er nie scharf klickt."),
               before="latency_ms")
# --- Free pad mode (W4-FREI) ---
register_field(Field("free_pad_on_grid", "Freie Pads am Takt-Punkt starten", "bool",
                     hint="Ein freies Pad behält seine eigene Länge. An: es beginnt am nächsten Loop-Anfang, "
                          "aus: sofort."),
               before="soft_seam")


# --- Markers (W4-MARKER) ---
register_field(Field("export_cue_points", "Marker als Cue-Punkte mitschreiben", "bool",
                     hint="Beim Sichern eines einzelnen Loops: Marker in die WAV-Datei schreiben, sonst "
                          "als Begleitdatei daneben. Das Sichern scheitert daran nie."),
               before="latency_ms")
