"""The settings of the parents' view as side panels: "Pegel", "Geräte", "Takt" and "System" (mockup L2-05).

``SettingsPanels`` builds the page of each of the four panels on its first visit. There is one way of
saving: every change acts at once and is written to ``settings.toml`` at once. A switch or a drop-down
saves on every change, a number field when it is left or 600 ms after the last change, a text field
when it is left or on Enter. Each change is checked as the loader checks the file (``parse_settings``),
written (``write_settings``; a damaged file is never overwritten) and handed to ``apply`` (the main
window takes the live values over). A refused value is not written: the panel says why in red, and the
field keeps the value until it is corrected. Fields that act only after a restart say so at the field.

The fields are a plain list (``FIELDS``). A later package adds a setting with one entry::

    register_field(Field("auto_gain", "Auto-Gain", "bool", hint="Standard: aus."))

(plus the key in ``Settings``, its check in ``parse_settings`` and its comment in
``config.SETTING_COMMENTS``). A field that no panel names goes onto the panel "System".
"""

from __future__ import annotations

import inspect
import re
import sys
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QLocale, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
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
from shiboken6 import isValid

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
from loopstation.gui.parent_nav import IconLabel, breakable, card, dim_label, qicon, scrolled
from loopstation.gui.peak_meter import PeakMeter
from loopstation.gui.side_panel import flatten_cards
from loopstation.gui.tempo_card import MetronomeCard, TempoCard
from loopstation.gui.widgets import ACCENT_GREEN, TEXT, weak_slot

if TYPE_CHECKING:
    from loopstation.controller import Controller

# How often the level scale, the bar and the loud-recordings list follow the controller (ms).
LEVEL_REFRESH_MS = 100
# A number field is saved this long after its last change (or when it is left).
NUMBER_PAUSE_MS = 600
# A "Gespeichert" message goes back to the normal line after this long.
MESSAGE_MS = 4000

# Advice for parents that belongs on the page whatever fields it has (plan sections 3.1 and 9.3).
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
RESTART_NOTE = "wirkt erst nach einem Neustart"
LOCAL_NOTE = "Lokal · ohne Konto · ohne Internet"

# Words in a device name that make a poor recording and playback device (plan 8).
BLUETOOTH_WORDS = ("bluetooth", "airpods", "bt-", "bt ", "a2dp", "hands-free")
BLUETOOTH_WARNING = "⚠ Bluetooth ist für Aufnahmen meist zu langsam."
STANDARD_TEXT = "Systemstandard"
ASIO_WARNING = (
    "ASIO ist für Audio-Interfaces gedacht. Viele Treiber öffnen das Gerät exklusiv: andere Programme "
    "sind dann still. ASIO4ALL ist nur ein Wrapper, kein echter Treiber.")
TEST_TONE_HZ = 440.0
TEST_TONE_SECONDS = 0.7
TEST_TONE_LEVEL = 0.12  # linear, before the volume and the ceiling (about -18 dBFS)


def _held_weakly(apply: Callable[[Settings], list[str]]) -> Callable[[Settings], list[str]]:
    """``apply`` as the panels should keep it: a method of the main window is held weakly.

    The main window owns the parents' view and with it these panels; if they held the window's method
    strongly the two would be a reference cycle that only the garbage collector frees, at any later time
    and in any order (see ``weak_slot``). A function or lambda is kept as it is.
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
    """One row of a panel. ``kind``: ``bool``, ``int``, ``float``, ``auto_float``, ``choice`` or ``text``.

    ``labels`` are the words shown for ``choices`` (the same order); without them the values are shown.
    """

    key: str
    label: str
    kind: str
    low: float = 0
    high: float = 1000
    hint: str = ""
    suffix: str = ""
    choices: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    @property
    def restart(self) -> bool:
        return self.key in RESTART_KEYS


FIELDS: list[Field] = [
    Field("loop_sync", "Loops im Takt halten", "bool",
          hint="Die erste Aufnahme bestimmt die Loop-Länge, alle weiteren passen dazu."),
    Field("soft_seam", "Weiche Loop-Naht", "bool",
          hint="Blendet das Ende jedes Loops kurz aus und den Anfang ganz kurz ein, damit es nicht "
               "knackt. Der erste Schlag bleibt dabei hörbar."),
    Field("sound_effects", "Piepton bei Aufnahme", "bool",
          hint="Ein kurzer Ton am Start und am Ende, durch dieselbe Grenze wie die Loops."),
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

# The device section (own cards, see ``SettingsPanels._devices_page``): the audio system, the two
# drop-downs and the ASIO switch. Not part of FIELDS, which are plain rows.
DEVICE_KEYS = ("audio_hostapi", "input_device", "output_device", "asio")
DEVICE_LABELS = {"audio_hostapi": "Audio-System", "input_device": "Mikrofon", "output_device": "Ausgang",
                 "asio": "ASIO"}

# Which panel shows a plain field. The level keys are on "Pegel" (``PANEL_KEYS``); the latency has its
# own card on "Geräte"; a field that is in no list goes onto "System".
LOOP_SWITCHES = ("auto_grid", "loop_sync", "stretch_to_grid", "free_pad_on_grid", "metronome_tone")
LOOP_NUMBERS = ("time_signature", "grid_bpm_min", "grid_bpm_max", "metronome_level_db")
LATENCY_KEY = "latency_ms"
# The sections of "System"; a field registered later that no panel names goes into the last one.
SYSTEM_SECTIONS = (
    ("Bedienung", ("launchpad", "fullscreen")),
    ("Aufnahme", ("max_record_seconds", "sound_effects", "record_start_tone")),
    ("Bearbeiten und Sichern", ("stretch_engine", "snap_markers", "export_cue_points")),
    ("Elternansicht", ("parent_unlock_minutes", "parent_idle_minutes")),
    ("Raster, Klang und Ordner", ("rows", "cols", "sample_rate", "data_dir")),
)
SETTINGS_PANELS = ("levels", "devices", "tempo", "system")


def register_field(field: Field, before: str | None = None) -> None:
    """Add ``field`` to the panels (at the end, or in front of the field ``before``)."""
    if any(f.key == field.key for f in FIELDS):
        raise ValueError(f"Feld '{field.key}' gibt es schon")
    index = next((i for i, f in enumerate(FIELDS) if f.key == before), len(FIELDS))
    FIELDS.insert(index, field)


def panel_of(key: str) -> str:
    """The panel that shows the setting ``key``."""
    if key in PANEL_KEYS:
        return "levels"
    if key in DEVICE_KEYS or key == LATENCY_KEY:
        return "devices"
    if key in LOOP_SWITCHES or key in LOOP_NUMBERS:
        return "tempo"
    return "system"


def field_labels() -> dict[str, str]:
    """The words of every setting, as the panels show them."""
    labels = {f.key: f.label for f in FIELDS}
    labels.update(DEVICE_LABELS)
    return labels


def readable_error(exc: Exception, path: Path, labels: dict[str, str]) -> str:
    """The message of a refused value without the file path and with the words of the fields, not the keys."""
    text = str(exc)
    for prefix in (f"{path}: ", f"{path.name}: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.startswith("ungültiges TOML"):
        return f"{path.name} ist beschädigt ({text}). Nichts gesichert, bitte die Datei prüfen."

    def word(match: re.Match[str]) -> str:
        key = match.group(1)
        return f"„{labels[key]}“" if key in labels else match.group(0)

    text = re.sub(r"(?:Schlüssel )?'([A-Za-z_][A-Za-z0-9_]*)'", word, text)
    return text[:1].upper() + text[1:]


def _file_raw(settings: Settings) -> dict[str, Any]:
    """``settings`` as the raw values of a file, the way ``parse_settings`` reads them."""
    raw = settings_values(settings)
    raw["data_dir"] = str(settings.data_dir)
    if raw["latency_ms"] is None:
        raw["latency_ms"] = "auto"
    return raw


class ToggleSwitch(QAbstractButton):
    """On/off switch (green and knob right = on), as in the parents' mockups."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(QSize(64, 36))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.4)  # greyed out: it cannot be switched now
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
    """The audio system as a radio list (``HostApiList``) with the editor interface of the panels."""

    def __init__(self, field: Field, value: str) -> None:
        self.field = field
        self.list = HostApiList(value)
        self.widget: QWidget = self.list

    def set_choices(self, choices: list[tuple[str, str]], selected: str) -> None:
        self.list.set_choices(choices, selected)

    def value(self) -> str:
        return self.list.value()


def _stepper(spin: QSpinBox | QDoubleSpinBox) -> QWidget:
    """``spin`` between a "−" and a "+" button (large enough for a finger, as on the panel "Takt")."""
    spin.setObjectName("stepped")  # its own arrows are hidden by the style (see ``FORM_QSS``)
    spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
    spin.setFixedWidth(132)
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    for word, step, name in (("−", spin.stepDown, "Weniger"), (None, None, ""), ("+", spin.stepUp, "Mehr")):
        if word is None:
            row.addWidget(spin)
            continue
        button = QPushButton(word)
        button.setObjectName("step")
        button.setAccessibleName(name)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRepeat(True)  # held: the number runs on (saved once, after the pause)
        button.clicked.connect(step)
        row.addWidget(button)
    return holder


class _Editor:
    """The input widget of one field and how to read its value."""

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
            labels = field.labels or field.choices
            for label, choice in zip(labels, field.choices, strict=True):
                self._combo.addItem(label, choice)
            self._combo.setCurrentIndex(max(0, self._combo.findData(str(value))))
            self.widget = self._combo
        elif kind == "text":
            self._edit = QLineEdit(str(value))
            self.widget = self._edit
        elif kind == "int":
            self._spin = QSpinBox()
            self._spin.setRange(int(field.low), int(field.high))
            self._spin.setValue(int(value))
            self._spin.setSuffix(field.suffix)
            self.widget = _stepper(self._spin)
        else:  # float, auto_float
            self._dspin = QDoubleSpinBox()
            self._dspin.setLocale(QLocale(QLocale.Language.German))  # 10,0 s
            self._dspin.setRange(field.low, field.high)
            self._dspin.setDecimals(1)
            self._dspin.setSuffix(field.suffix)
            self._dspin.setValue(float(value) if value is not None else field.low)
            if kind == "auto_float":
                self._dspin.setObjectName("stepped")
                self._dspin.setFixedWidth(120)
                self._dspin.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._build_auto(value)
            else:
                self.widget = _stepper(self._dspin)

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
            return str(self._combo.currentData())
        if kind == "text":
            return self._edit.text()
        if kind == "int":
            return self._spin.value()
        if self._auto is not None and self._auto.isChecked():
            return "auto"
        return self._dspin.value()

    def set_value(self, value: Any) -> None:
        """Show ``value`` without saving it (a changed field: the file has it now)."""
        kind = self.field.kind
        widget = {"bool": "_box", "choice": "_combo", "text": "_edit", "int": "_spin"}.get(kind, "_dspin")
        target = getattr(self, widget)
        target.blockSignals(True)
        if kind == "bool":
            target.setChecked(bool(value))
        elif kind == "choice":
            target.setCurrentIndex(max(0, target.findData(str(value))))
        elif kind == "text":
            target.setText(str(value))
        elif kind == "int":
            target.setValue(int(value))
        elif value is not None:
            target.setValue(float(value))
        target.blockSignals(False)


class SettingsPanels(QObject):
    """The four settings panels of the parents' view; every change is saved and taken over at once.

    ``apply(settings)`` takes over the live values and returns the keys that need a restart. ``said(text,
    level)`` carries a message for the head of the panel ("" = the normal line; levels "ok", "warning",
    "error"). With a ``controller`` the panels have the live parts: the level section (``LevelPanel``),
    the bar of the session and its correction, the metronome, the microphone scale and the test tone.
    ``source`` lists the audio devices (the audio engine), or None.
    """

    said = Signal(str, str)

    def __init__(
        self,
        config_path: Path,
        running: Settings,
        apply: Callable[[Settings], list[str]],
        template: str | None = None,
        controller: Controller | None = None,
        source: Any = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.running = running
        self._apply = _held_weakly(apply)
        self._template = template
        self._applied = running  # what the controller runs now (live values)
        self.controller = controller
        self._source = source
        self.editors: dict[str, Any] = {}
        # Second inputs of a setting shown outside the four panels (the detail panel of the pads); they
        # save the same way and follow every saved change, as the panels' own inputs do.
        self.mirrors: dict[str, _Editor] = {}
        self.restart_notes: dict[str, QLabel] = {}
        self._pages: dict[str, QWidget] = {}
        self._refused: dict[str, str] = {}  # key -> why its shown value was not saved
        self._pauses: dict[tuple[str, bool], QTimer] = {}
        self._labels = field_labels()
        self.message = ""  # what the head of the panel says now ("" = its normal line)
        self.level = ""
        self._values = settings_values(self._file_settings())
        self.panel: LevelPanel | None = None
        self.grid_panel: GridPanel | None = None
        self.tempo_card: TempoCard | None = None
        self.metronome_card: MetronomeCard | None = None
        self.mic_meter: PeakMeter | None = None
        self.tone_button: QPushButton | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(weak_slot(self.refresh_levels))
        if controller is not None:
            self._timer.start(LEVEL_REFRESH_MS)
        self._calm = QTimer(self)
        self._calm.setSingleShot(True)
        self._calm.setInterval(MESSAGE_MS)
        self._calm.timeout.connect(weak_slot(self._say, ""))

    # ------------------------------------------------------------------ pages

    def page(self, key: str) -> QWidget:
        """The page of the panel ``key`` ("levels", "devices", "tempo", "system"), built on first visit."""
        widget = self._pages.get(key)
        if widget is None:
            builder = {"levels": self._levels_page, "devices": self._devices_page,
                       "tempo": self._tempo_page, "system": self._system_page}[key]
            widget = builder()
            flatten_cards(widget)
            self._pages[key] = widget
        return widget

    def mirror(self, key: str) -> QWidget:
        """A second input of the setting ``key`` (a plain field) for a page outside the panels.

        It is saved like the input on its panel (at once, a number after its pause) and shows what the
        other one saves. One mirror per key: a new one replaces the one before.
        """
        field = next(f for f in FIELDS if f.key == key)
        pause = self._pauses.pop((key, True), None)
        if pause is not None:  # the mirror before goes: its number is not saved later as the new one's
            pause.stop()
            pause.deleteLater()
        editor = _Editor(field, self._values[key])
        if isinstance(editor.widget, QAbstractButton):
            editor.widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # a switch leaves the keys to the pads
        self.mirrors[key] = editor
        self._wire(key, editor, mirror=True)
        return editor.widget

    def build_all(self) -> None:
        for key in SETTINGS_PANELS:
            self.page(key)

    def _fields(self, keys: Iterable[str]) -> list[Field]:
        """The plain fields among ``keys``, in the order given."""
        by_key = {f.key: f for f in FIELDS}
        return [by_key[key] for key in dict.fromkeys(keys) if key in by_key]

    @staticmethod
    def _column(*widgets: QWidget | None, spacing: int = 18) -> QWidget:
        """A page: the widgets one under the other, in a scroll area."""
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 12, 0)  # room for the scroll bar
        layout.setSpacing(spacing)
        for widget in widgets:
            if widget is not None:
                layout.addWidget(widget)
        layout.addStretch(1)
        return scrolled(inner)

    def _section(self, title: str, fields: list[Field], note: str = "") -> QFrame:
        """A section with a heading and one row per field."""
        frame, layout = card(title, note, spacing=12)
        for field in fields:
            layout.addWidget(self._row(field))
        return frame

    def _editor(self, field: Field) -> _Editor:
        editor = self.editors.get(field.key)
        if editor is None:
            editor = _Editor(field, self._values[field.key])
            self.editors[field.key] = editor
            self._wire(field.key, editor)
        return editor

    def _row(self, field: Field) -> QWidget:
        """One field: a switch beside its words, or the words above the input; restart note at the field."""
        editor = self._editor(field)
        holder = QWidget()
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        name = QLabel(field.label)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        name.setObjectName("field_label")
        texts.addWidget(name)
        if field.restart:
            texts.addWidget(self._restart_note(field.key))
        if field.kind == "bool":
            if field.hint:
                texts.addWidget(dim_label(field.hint, 13))
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(16)
            row.addWidget(editor.widget, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(texts, 1)
            return holder
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addLayout(texts)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(editor.widget, 1 if field.kind in ("text", "choice") else 0)
        if field.kind not in ("text", "choice"):
            line.addStretch(1)
        column.addLayout(line)
        if field.hint and field.key != "stretch_engine":
            column.addWidget(dim_label(field.hint, 13))
        if field.key == "stretch_engine":
            if field.hint:
                column.addWidget(dim_label(field.hint, 13))
            self.engine_hint = dim_label(engine_notice(editor.value()), 13)
            column.addWidget(self.engine_hint)
        return holder

    def _restart_note(self, key: str) -> QLabel:
        note = dim_label("", 13, "#FF9F0A")
        self.restart_notes[key] = note
        self._update_restart_note(key)
        return note

    def _update_restart_note(self, key: str) -> None:
        note = self.restart_notes.get(key)
        if note is None:
            return
        saved, running = self._values.get(key), getattr(self.running, key)
        if saved != running:
            shown = breakable(running)
            note.setText(f"gespeichert, {RESTART_TEXT} (jetzt noch: {shown})")
        else:
            note.setText(RESTART_NOTE)

    def _switch_row(self, editor: Any, label: str, hint: str, note: QLabel | None = None) -> QHBoxLayout:
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16.5px; font-weight: 600;")
        texts.addWidget(name)
        if note is not None:
            texts.addWidget(note)
        if hint:
            texts.addWidget(dim_label(hint, 13))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(editor.widget, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        return row

    # -------------------------------------------------------------- the panels

    def _levels_page(self) -> QWidget:
        if self.controller is None:
            return self._column(self._section("Lautstärke und Pegel", self._fields(PANEL_KEYS)))
        panel_fields = {f.key: f for f in FIELDS if f.key in PANEL_KEYS}
        self.panel = LevelPanel(self.controller, self._values, panel_fields, ToggleSwitch)
        self.panel.edited.connect(weak_slot(self._level_edited, pass_signal_args=True))
        self.editors.update(self.panel.editors)
        return self._column(self.panel)

    def _tempo_page(self) -> QWidget:
        switches = self._section("Loop-Verhalten", self._fields(LOOP_SWITCHES))
        numbers = self._section("Taktart und Tempo-Fenster", self._fields(LOOP_NUMBERS))
        if self.controller is None:
            return self._column(switches, numbers)
        self.grid_panel = GridPanel(self.controller)
        self.tempo_card = TempoCard(self.controller)
        self.metronome_card = MetronomeCard(self.controller)
        return self._column(self.grid_panel, self.tempo_card, switches, self.metronome_card, numbers)

    def _system_page(self) -> QWidget:
        sections: list[QWidget | None] = []
        placed: set[str] = set()
        for title, keys in SYSTEM_SECTIONS:
            fields = [f for f in self._fields(keys) if panel_of(f.key) == "system"]
            placed.update(f.key for f in fields)
            if fields:
                sections.append(self._section(title, fields))
        rest = [f for f in FIELDS if panel_of(f.key) == "system" and f.key not in placed]
        if rest:
            sections.append(self._section("Weitere", rest))
        sections.append(dim_label(LOCAL_NOTE, 13, "#6E6E75"))
        return self._column(*sections)

    # -------------------------------------------------- devices and audio system

    def _devices_page(self) -> QWidget:
        """Microphone and speaker, audio system, latency and the advice for good looping."""
        values = self._values
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
        self._wire("asio", self._asio)
        self.editors["audio_hostapi"].list.changed.connect(weak_slot(self._hostapi_changed))
        for key in ("input_device", "output_device"):
            self._choice(key).box.currentIndexChanged.connect(weak_slot(self._device_chosen, key))

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

        out, out_layout = card("Lautsprecher / Kopfhörer (Ausgang)", icon="headphones", spacing=10)
        out_layout.addWidget(self.editors["output_device"].widget)
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

        system = platform_name()
        audio, audio_layout = card("Audio-System" + (f" ({system})" if system else ""),
                                   "Nur ändern, wenn nötig. Die Audio-Streams starten dafür kurz neu.",
                                   spacing=8)
        audio_layout.addWidget(self.editors["audio_hostapi"].widget)
        self._asio_row = QWidget()
        asio_layout = QVBoxLayout(self._asio_row)
        asio_layout.setContentsMargins(0, 6, 0, 0)
        asio_layout.addLayout(self._switch_row(
            self._asio, "ASIO zulassen (nur Windows)", ASIO_WARNING, self._restart_note("asio")))
        self._asio_row.setVisible(sys.platform.startswith("win"))  # ASIO exists on Windows only
        audio_layout.addWidget(self._asio_row)
        audio_layout.addWidget(dim_label(
            "Fehlt ein Gerät, wird der Systemstandard genutzt (Hinweis in der Statuszeile). "
            "Für ein und aus am besten dasselbe Interface wählen: zwei Geräte können gegeneinander driften."))

        latency_field = next((f for f in FIELDS if f.key == LATENCY_KEY), None)
        latency: QWidget | None = None
        if latency_field is not None:
            latency, latency_layout = card("Verzögerung (Latenz)", spacing=6)
            editor = self._editor(latency_field)
            latency_layout.addWidget(editor.widget)
            self.latency_hint = editor.auto_note or dim_label("", 13)
            latency_layout.addWidget(dim_label(
                "Wird nach Geräte- oder System-Wechsel neu berechnet. " + latency_field.hint, 13))
        else:
            self.latency_hint = dim_label("", 13)
        notes_card = QFrame()
        notes_card.setObjectName("notes")
        notes_card.setStyleSheet("#notes { background: rgba(255, 159, 10, 23); border: 1.5px solid "
                                 "rgba(255, 159, 10, 102); border-radius: 14px; }")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(16, 12, 16, 12)
        notes_layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconLabel("alert", "#FF9F0A", 24))
        title = QLabel("Für gutes Looping")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        head.addWidget(title, 1)
        notes_layout.addLayout(head)
        for text in (*NOTES, *MORE_NOTES):
            note = dim_label("• " + text, 13)
            note.setStyleSheet(f"color: {TEXT.name()}; font-size: 13.5px;")
            notes_layout.addWidget(note)
        self._fill_devices()
        return self._column(mic, out, audio, latency, notes_card)

    def play_test_tone(self) -> None:
        """A short quiet tone on the running output, through the same volume and ceiling as the loops."""
        if self.controller is None:
            return
        tone = beep(TEST_TONE_HZ, TEST_TONE_SECONDS, self.controller.sample_rate, TEST_TONE_LEVEL)
        self.controller.audio.play_effect(tone)

    def _choice(self, key: str) -> _ChoiceEditor:
        return self.editors[key]  # type: ignore[no-any-return]

    def _hostapi_changed(self) -> None:
        """Another audio system: its devices are listed, and the three values are saved together."""
        self._fill_devices(reset_devices=True)
        self.commit({key: self.editors[key].value() for key in ("audio_hostapi", "input_device",
                                                                 "output_device")})

    def _device_chosen(self, key: str) -> None:
        self._update_device_hints()
        self.commit({key: self.editors[key].value()})

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
        if "input_device" not in self.editors:
            return
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
        for label in (self.device_hint, self.mic_others, self.out_others, self.latency_hint):
            label.setVisible(bool(label.text()))  # an empty line takes no room

    # ------------------------------------------------------------ saving

    def _wire(self, key: str, editor: _Editor, mirror: bool = False) -> None:
        """Save ``key`` when its input changes: at once, after a pause, or when the field is left."""
        kind = editor.field.kind
        commit = weak_slot(self._commit_editor, key, mirror)
        if kind == "bool":
            editor._box.toggled.connect(commit)
        elif kind == "choice":
            editor._combo.currentIndexChanged.connect(commit)
            if key == "stretch_engine":
                editor._combo.currentIndexChanged.connect(weak_slot(self._update_engine_hint))
        elif kind == "text":
            editor._edit.editingFinished.connect(commit)
        else:
            spin = editor._spin if kind == "int" else editor._dspin
            pause = QTimer(self)
            pause.setSingleShot(True)
            pause.setInterval(NUMBER_PAUSE_MS)
            pause.timeout.connect(commit)
            self._pauses[(key, mirror)] = pause
            spin.valueChanged.connect(pause.start)
            spin.editingFinished.connect(commit)
            if kind == "auto_float" and editor._auto is not None:
                editor._auto.toggled.connect(weak_slot(self._auto_toggled, key, pass_signal_args=True))

    def _auto_toggled(self, key: str, automatic: bool) -> None:
        """"Automatisch" saves "auto". "Von Hand" starts from what the devices report and saves that;
        without a reported value nothing is saved until a number is entered (never a made-up 0 ms)."""
        editor = self.editors[key]
        if automatic:
            self._commit_editor(key)
            return
        reported = getattr(self._source, "reported_latency_ms", lambda: None)()
        if reported is None:
            editor._dspin.setFocus()
            return
        editor._dspin.blockSignals(True)
        editor._dspin.setValue(round(float(reported)))
        editor._dspin.blockSignals(False)
        self._commit_editor(key)

    def flush(self) -> None:
        """Save what is waiting: a number in its pause, the text of a field that still has the focus."""
        for (key, mirror), pause in list(self._pauses.items()):
            if pause.isActive():
                self._commit_editor(key, mirror)
        for key, editor in self.editors.items():
            edit = getattr(editor, "_edit", None)
            if edit is not None and edit.hasFocus():
                self._commit_editor(key)

    def _commit_editor(self, key: str, mirror: bool = False) -> None:
        pause = self._pauses.get((key, mirror))
        if pause is not None:
            pause.stop()
        editor = self.mirrors[key] if mirror else self.editors[key]
        self.commit({key: editor.value()})

    def _show_saved(self, keys: Iterable[str]) -> None:
        """Every input of ``keys`` (on its panel and its mirror) shows the saved value."""
        for key in keys:
            value = self._values.get(key)
            for editor in (self.editors.get(key), self.mirrors.get(key)):
                if isinstance(editor, _Editor) and isValid(editor.widget) and editor.value() != value:
                    editor.set_value(value)

    def _update_engine_hint(self) -> None:
        """Which stretch engine runs for the choice, and why (Rubber Band missing or not)."""
        self.engine_hint.setText(engine_notice(self.editors["stretch_engine"].value()))

    def _file_settings(self) -> Settings:
        """What the file says now (it may hold restart values not running yet), else the running ones."""
        try:
            return load_settings(self.config_path)
        except ConfigError:
            return self.running

    def commit(self, changes: dict[str, Any]) -> bool:
        """Check ``changes`` with the rest of the file, write the file, take the values over.

        False (nothing written, nothing taken over) if a value is refused or the file cannot be read or
        written; the reason is said in the head of the panel. A value equal to the saved one writes nothing.
        """
        try:
            # A damaged file is never overwritten from here; a missing one is written new.
            base = load_settings(self.config_path) if self.config_path.exists() else self._applied
        except ConfigError as exc:
            # Broken by hand: no change can be saved, whatever field it is; the file must be fixed first.
            reason = readable_error(exc, self.config_path, self._labels)
            if not reason.startswith(self.config_path.name):
                reason = f"{self.config_path.name} enthält einen ungültigen Wert: {reason}. Nichts gesichert."
            for key in changes:
                self._refused[key] = reason
            self._say(reason, "error")
            return False
        try:
            raw = _file_raw(base)
            raw.update(changes)
            if self.controller is not None:
                raw["volume"] = self.controller.volume  # the child's volume stays as it is
            new = parse_settings(raw, str(self.config_path))
            if self.config_path.exists() and all(getattr(new, k) == getattr(base, k) for k in changes):
                self._accepted(changes)
                self._show_saved(changes)
                return True
            write_settings(self.config_path, new, self._template)
        except (ConfigError, OSError) as exc:
            reason = readable_error(exc, self.config_path, self._labels)
            for key in changes:
                self._refused[key] = reason
            self._say(reason, "error")
            return False
        restart = self._apply(new)
        switched = any(getattr(new, key) != getattr(self._applied, key)
                       for key in ("input_device", "output_device", "audio_hostapi"))
        self._applied = new
        self._values = settings_values(new)
        self._show_saved(changes)
        for key in self.restart_notes:
            self._update_restart_note(key)
        self._accepted(changes)
        if self._refused:
            return True
        names = ", ".join(self._labels.get(key, key) for key in changes)
        pending = [key for key in restart if key in changes]
        if pending:
            words = ", ".join(self._labels.get(key, key) for key in pending)
            self._say(f"Gespeichert, {RESTART_TEXT}: {words}", "warning")
        elif switched:
            hint = str(getattr(self._source, "device_notice", "") or "")
            self._say("Gespeichert, Audio wurde kurz neu gestartet." + (f" {hint}" if hint else ""),
                      "warning" if hint else "ok")
            self._update_device_hints()
        else:
            self._say(f"Gespeichert: {names}", "ok", calm=True)
        return True

    def _accepted(self, changes: dict[str, Any]) -> None:
        """``changes`` are saved: a refusal of those fields is over; the next one left is shown, or none."""
        had = bool(self._refused)
        for key in changes:
            self._refused.pop(key, None)
        if self._refused:
            self._say(next(iter(self._refused.values())), "error")
        elif had:
            self._say("")

    def _level_edited(self, key: str, value: Any, final: bool) -> None:
        """A control of the level section changed: the controller takes it over at once.

        While a slider is dragged or stepped with the keys only the level setter acts; the value is saved
        like a number field: at the end of the drag, when the slider is left, or after the pause. A switch
        saves at once.
        """
        pause = self._pauses.get((key, False))
        if not final:
            setter = {"max_level_db": "set_max_level_db", "input_gain_db": "set_input_gain_db"}.get(key)
            if setter is not None and self.controller is not None:
                getattr(self.controller, setter)(value)
                self._applied = replace(self._applied, **{key: value})
                if pause is None:
                    pause = QTimer(self)
                    pause.setSingleShot(True)
                    pause.setInterval(NUMBER_PAUSE_MS)
                    pause.timeout.connect(weak_slot(self._commit_editor, key))
                    self._pauses[(key, False)] = pause
                pause.start()
                self.refresh_levels()
                return
        if pause is not None:
            pause.stop()
        self.commit({key: value})
        self.refresh_levels()

    def _say(self, text: str, level: str = "ok", calm: bool = False) -> None:
        self.message = text
        self.level = level if text else ""
        if calm:
            self._calm.start()
        else:
            self._calm.stop()
        self.said.emit(text, self.level)

    # ------------------------------------------------------------ refresh

    def refresh_levels(self) -> None:
        """Let the level scale, loud recordings, the bar and the microphone scale follow the controller."""
        controller = self.controller
        if controller is None:
            return
        if self.panel is not None and self.panel.isVisible():
            self.panel.refresh()
        if self.grid_panel is not None and self.grid_panel.isVisible():
            self.grid_panel.refresh()
        if self.tempo_card is not None and self.tempo_card.isVisible():
            self.tempo_card.refresh()
        if self.mic_meter is not None and self.mic_meter.isVisible():
            level, hold = controller.meter_levels()
            self.mic_meter.setEnabled(controller.peak_meter)
            self.mic_meter.set_state(level, hold, controller.input_clipping())


# --- Onset grid (W2-ONSET-GRID) ---
register_field(Field("auto_grid", "Takt aus Klatschen erkennen", "bool",
                     hint="Die erste Aufnahme beginnt beim ersten Schlag und kann ihren Takt aus dem "
                          "Abstand der Schläge bekommen. Aus = Aufnahmelänge wird Takt."),
               before="soft_seam")
register_field(Field("time_signature", "Taktart", "choice", choices=tuple(SIGNATURES),
                     hint="Ein Takt besteht aus so vielen Schlägen wie die Taktart (4/4 = 4). "
                          "Gilt ab der nächsten ersten Aufnahme."),
               before="latency_ms")
register_field(Field("snap_markers", "Marker auf Schläge einrasten", "bool",
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
register_field(Field("stretch_engine", "Stretch-Verfahren", "choice", choices=STRETCH_ENGINES,
                     labels=("Automatisch", "Rubber Band", "Einfach"),
                     hint="Automatisch: Rubber Band, wenn vorhanden (sauberer), sonst still der einfache "
                          "Stretch. Rubber Band: gewünscht, fehlt es, steht hier ein Hinweis. "
                          "Einfach: immer der eingebaute."),
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
register_field(Field("export_cue_points", "Marker als Cue-\u2060Punkte mitschreiben", "bool",
                     hint="Beim Sichern eines einzelnen Loops: Marker in die WAV-Datei schreiben, sonst "
                          "als Begleitdatei daneben. Das Sichern scheitert daran nie."),
               before="latency_ms")
