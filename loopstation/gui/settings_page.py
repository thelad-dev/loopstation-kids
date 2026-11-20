"""Settings page of the parents' area.

The fields are a plain list (``FIELDS``). A later package adds a setting to
the page with one entry, no change to this dialog::

    register_field(Field("auto_gain", "Auto-Gain", "bool", hint="Standard: aus."))

(plus the key in ``Settings``, its check in ``parse_settings`` and its comment
in ``config.SETTING_COMMENTS``).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation.audio.devices import default_hostapi
from loopstation.config import (
    RESTART_KEYS,
    SIGNATURES,
    ConfigError,
    Settings,
    load_settings,
    parse_settings,
    settings_values,
    write_settings,
)
from loopstation.gui.grid_panel import GridPanel
from loopstation.gui.parent_gate import PARENT_ACCENT, _IconLabel
from loopstation.gui.volume_slider import VolumeSlider
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_GREEN,
    BACKGROUND,
    SURFACE,
    TEXT,
    TEXT_DIM,
    BigButton,
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

RESTART_TEXT = "wirkt nach Neustart"

# Words in a device name that make a poor recording and playback device (plan 8).
BLUETOOTH_WORDS = ("bluetooth", "airpods", "bt-", "bt ", "a2dp", "hands-free")
BLUETOOTH_WARNING = "⚠ Bluetooth ist für Aufnahmen meist zu langsam."
STANDARD_TEXT = "Systemstandard"
ASIO_WARNING = (
    "ASIO ist für Audio-Interfaces gedacht. Viele Treiber öffnen das Gerät exklusiv: andere Programme "
    "sind dann still. ASIO4ALL ist nur ein Wrapper, kein echter Treiber. Wirkt erst nach einem Neustart.")


@dataclass(frozen=True)
class ParentAction:
    """A further page of the parents' area, reached by a button next to "Speichern".

    ``open(parent)`` shows that page (modal) on top of the settings page.
    """

    icon: str
    label: str
    open: Callable[[QWidget], None]


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
          hint="Blendet Anfang und Ende jedes Loops kurz aus, damit es nicht knackt."),
    Field("sound_effects", "Piepton bei Aufnahme", "bool"),
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
    Field("rows", "Zeilen", "int", 1, 16),
    Field("cols", "Spalten", "int", 1, 16),
    Field("sample_rate", "Abtastrate", "int", 8000, 192000, suffix=" Hz"),
    Field("data_dir", "Datenordner", "text"),
]

# The device section (own card, see ``SettingsDialog._device_card``): the three
# drop-downs and the ASIO switch. Not part of FIELDS, which are plain rows.
DEVICE_KEYS = ("audio_hostapi", "input_device", "output_device", "asio")


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


class _Editor:
    """The input widget of one field and how to read and set its value."""

    def __init__(self, field: Field, value: Any) -> None:
        self.field = field
        self.widget: QWidget
        self._auto: QCheckBox | None = None
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
                self._auto = QCheckBox("automatisch")
                self._auto.setChecked(value is None)
                self._dspin.setEnabled(value is not None)
                self._auto.toggled.connect(lambda on: self._dspin.setEnabled(not on))
                holder = QWidget()
                row = QHBoxLayout(holder)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(self._auto)
                row.addWidget(self._dspin)
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
    """Edits ``settings.toml`` and hands the result to ``apply``.

    ``apply(settings)`` takes over the live values and returns the keys that
    need a restart. A refused value is shown in the dialog and nothing is written.

    With a ``controller`` (or a parent window that has one) the page also has
    the volume slider at the top right and the level section (``LevelPanel``);
    those controls act at once, the rest of the page waits for "Speichern".
    """

    def __init__(
        self,
        config_path: Path,
        running: Settings,
        apply: Callable[[Settings], list[str]],
        template: str | None = None,
        parent: QWidget | None = None,
        actions: Sequence[ParentAction] = (),
        controller: Controller | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.running = running
        self._apply = apply
        self._template = template
        self._applied = running  # what the controller runs now (live values)
        self.saved = False
        self.setWindowTitle("Elternbereich")
        self.setModal(True)
        self.setStyleSheet(
            f"SettingsDialog {{ background: {BACKGROUND.name()}; border: 5px solid {PARENT_ACCENT}; }} "
            f"QScrollArea, #settings_inner {{ background: transparent; border: none; }} "
            f"QLabel, QCheckBox {{ color: {TEXT.name()}; font-size: 16px; }} "
            "#card { background: #1B1B1F; border: 1px solid #26262B; border-radius: 18px; } "
            f"QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {{ color: {TEXT.name()}; "
            f"background: {SURFACE.name()}; "
            f"font-size: 16px; border: 1px solid {PARENT_ACCENT}; border-radius: 10px; padding: 6px 10px; }} "
            f"QComboBox QAbstractItemView {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
            f"selection-background-color: {PARENT_ACCENT}; selection-color: #000000; font-size: 16px; }} "
            "QSpinBox:disabled, QDoubleSpinBox:disabled { color: #5A5A60; border-color: #3A3A41; } "
            "QCheckBox::indicator { width: 22px; height: 22px; border-radius: 5px; "
            f"background: {SURFACE.name()}; border: 1px solid #5A5A60; }} "
            f"QCheckBox::indicator:checked {{ background: {ACCENT_GREEN.name()}; }}")

        # Header: back to the child page, title with the open lock, what the page does.
        self.close_button = BigButton("back", "Zur Kinderseite", ACCENT_GRAY)
        self.close_button.setToolTip("Eltern-Modus beenden")
        self.close_button.clicked.connect(self.reject)
        title = QLabel("Elternbereich")
        title.setStyleSheet("font-size: 34px; font-weight: bold;")
        subtitle = QLabel("Änderungen gelten sofort · gespeichert in settings.toml")
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

        self.editors: dict[str, Any] = {}
        shown = self._file_settings()
        values = settings_values(shown)
        self.controller = controller if controller is not None else getattr(parent, "controller", None)
        self.panel = None
        self.grid_panel: GridPanel | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_levels)
        self.volume_slider: VolumeSlider | None = None
        if self.controller is not None:
            # Imported here because level_panel imports ToggleSwitch from this module.
            from loopstation.gui.level_panel import PANEL_KEYS, LevelPanel

            self.volume_slider = VolumeSlider(captions=True)
            self.volume_slider.setMinimumWidth(300)
            self.volume_slider.setMaximumWidth(384)
            self.volume_slider.volumeChanged.connect(self.controller.set_volume)
            header.addWidget(self.volume_slider, 0)
            self.grid_panel = GridPanel(self.controller)
            panel_fields = {f.key: f for f in FIELDS if f.key in PANEL_KEYS}
            self.panel = LevelPanel(self.controller, values, panel_fields, ToggleSwitch)
            self.panel.edited.connect(self._level_edited)
            self.editors.update(self.panel.editors)
        self._pending = [f.label for f in FIELDS if f.restart and values[f.key] != getattr(running, f.key)]
        self._source = getattr(parent, "audio_devices", None)
        self._applied = running
        switches, numbers = QVBoxLayout(), QFormLayout()
        switches.setSpacing(14)
        numbers.setHorizontalSpacing(24)
        numbers.setVerticalSpacing(12)
        for field in FIELDS:
            if field.key in self.editors:
                continue  # the level section above has it
            editor = _Editor(field, values[field.key])
            self.editors[field.key] = editor
            label = field.label + (f" ({RESTART_TEXT})" if field.restart else "")
            if field.kind == "bool":
                switches.addLayout(self._switch_row(editor, label, field.hint))
            else:
                row = QVBoxLayout()
                row.setSpacing(2)
                row.addWidget(editor.widget)
                if field.hint:
                    row.addWidget(self._hint(field.hint))
                numbers.addRow(label, row)

        inner = QWidget()
        inner.setObjectName("settings_inner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(14)
        if self.grid_panel is not None:
            inner_layout.addWidget(self.grid_panel)
        if self.panel is not None:
            inner_layout.addWidget(self.panel)
        inner_layout.addWidget(self._card("Loop-Verhalten und Aufnahme", switches))
        inner_layout.addWidget(self._card("Zahlenwerte", numbers))
        inner_layout.addWidget(self._device_card(values))
        notes = QVBoxLayout()
        for text in NOTES:
            note = self._hint(text)
            note.setStyleSheet(f"color: {TEXT.name()}; font-size: 14px;")
            notes.addWidget(note)
        inner_layout.addWidget(self._card("Hinweise für Erwachsene", notes))
        inner_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        footer = QLabel(
            "Lokal · ohne Konto · ohne Internet · Neustart nötig nur für: " + ", ".join(RESTART_KEYS))
        footer.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        footer.setWordWrap(True)
        self.save_button = BigButton("check", "Speichern", QColor(PARENT_ACCENT), checkable=True)
        self.save_button.setChecked(True)  # filled: the one main action
        self.save_button.clicked.connect(self._save_clicked)
        bottom = QHBoxLayout()
        bottom.setSpacing(24)
        texts = QVBoxLayout()
        texts.addWidget(self.message)
        texts.addWidget(footer)
        bottom.addLayout(texts, 1)
        self.action_buttons: dict[str, BigButton] = {}
        for action in actions:
            button = BigButton(action.icon, action.label, ACCENT_GRAY)
            button.clicked.connect(lambda _checked=False, a=action: a.open(self))
            self.action_buttons[action.label] = button
            bottom.addWidget(button)
        bottom.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        layout.addLayout(bottom)
        self.resize(1280, 800)
        if self._pending:
            self._say(f"Gespeichert, {RESTART_TEXT}: " + ", ".join(self._pending), warning=True)

    # -------------------------------------------------- devices and audio system

    def _device_card(self, values: dict[str, Any]) -> QFrame:
        """Microphone, speaker and audio system as drop-downs, plus the ASIO switch (plan 8, 12)."""
        fields = {
            "audio_hostapi": Field("audio_hostapi", "Audio-System", "choice"),
            "input_device": Field("input_device", "Mikrofon (Eingang)", "choice"),
            "output_device": Field("output_device", "Lautsprecher / Kopfhörer (Ausgang)", "choice"),
        }
        for key, field in fields.items():
            self.editors[key] = _ChoiceEditor(field, str(values[key]))  # type: ignore[assignment]
        self._asio = _Editor(Field("asio", "ASIO zulassen (nur Windows)", "bool"), values["asio"])
        self.editors["asio"] = self._asio
        self._hostapi_box().currentIndexChanged.connect(lambda _i: self._fill_devices(reset_devices=True))
        for key in ("input_device", "output_device"):
            self._choice(key).box.currentIndexChanged.connect(lambda _i: self._update_device_hints())

        self.device_hint = self._hint("")
        self.device_hint.setStyleSheet("color: #FF9F0A; font-size: 13px;")
        self.latency_hint = self._hint("")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        for key, field in fields.items():
            form.addRow(field.label, self.editors[key].widget)
        content = QVBoxLayout()
        content.addLayout(form)
        content.addWidget(self.device_hint)
        content.addWidget(self.latency_hint)
        content.addWidget(self._hint(
            "Der Wechsel gilt sofort, die Audio-Streams starten dafür kurz neu. "
            "Fehlt ein Gerät, wird der Systemstandard genutzt (Hinweis in der Statuszeile). "
            "Für ein und aus am besten dasselbe Interface wählen: zwei Geräte können gegeneinander driften."))
        content.addLayout(self._switch_row(self._asio, "ASIO zulassen (nur Windows, " + RESTART_TEXT + ")",
                                           ASIO_WARNING))
        self._fill_devices()
        return self._card("Geräte und Audio-System", content)

    def _choice(self, key: str) -> _ChoiceEditor:
        return self.editors[key]  # type: ignore[return-value]

    def _hostapi_box(self) -> QComboBox:
        return self._choice("audio_hostapi").box

    def _fill_devices(self, reset_devices: bool = False) -> None:
        """Fill the audio systems and, for the chosen one, the microphone and speaker lists.

        ``reset_devices``: the audio system was just changed, so a device that
        the new one does not offer goes back to the system default.
        """
        hostapi = self._choice("audio_hostapi").value()
        source = self._source
        if source is None:
            self._choice("audio_hostapi").set_choices([], hostapi)
            for key in ("input_device", "output_device"):
                self._choice(key).set_choices([], self._choice(key).value())
            self._update_device_hints()
            return
        groups = {"input": source.device_groups("input"), "output": source.device_groups("output")}
        names = list(dict.fromkeys(g.name for kind in groups.values() for g in kind))
        self._choice("audio_hostapi").set_choices([(name, name) for name in names], hostapi)
        shown = self._choice("audio_hostapi").value()
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
        latency = getattr(self._source, "reported_latency_ms", lambda: None)()
        self.latency_hint.setText(
            "" if latency is None else f"Latenz „automatisch“ aus den Geräten ermittelt: {latency:.0f} ms")

    @staticmethod
    def _hint(text: str) -> QLabel:
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        return hint

    @staticmethod
    def _card(title: str, content: QVBoxLayout | QFormLayout) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 18, 24, 18)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(heading)
        layout.addLayout(content)
        return card

    def _switch_row(self, editor: _Editor, label: str, hint: str) -> QHBoxLayout:
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(label)
        name.setStyleSheet("font-size: 18px; font-weight: bold;")
        texts.addWidget(name)
        if hint:
            texts.addWidget(self._hint(hint))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(editor.widget)
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

    def refresh_levels(self) -> None:
        """Let the volume slider, the level scale and the loud-recordings list follow the controller."""
        if self.controller is None or self.volume_slider is None or self.panel is None:
            return
        self.volume_slider.set_state(self.controller.volume, self.controller.volume_limit)
        self.panel.refresh()
        if self.grid_panel is not None:
            self.grid_panel.refresh()

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
        color = "#FF3B30" if error else "#FF9F0A" if warning else "#32D74B"
        self.message.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")
        self.message.setText(text)

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
register_field(Field("grid_bpm_min", "Langsamstes Tempo für den Takt", "float", 20, 300, suffix=" BPM"),
               before="latency_ms")
register_field(Field("grid_bpm_max", "Schnellstes Tempo für den Takt", "float", 20, 300, suffix=" BPM",
                     hint="Außerhalb dieses Fensters entsteht kein Takt aus Schlägen."),
               before="latency_ms")


# --- Stretch into the grid (W3-STRETCH-INT) ---
register_field(Field("stretch_to_grid", "Aufnahmen weich in den Takt ziehen", "bool",
                     hint="Knapp neben einem ganzen Takt: auf den Takt ziehen statt auffüllen oder "
                          "schneiden. Aus = immer auffüllen oder schneiden."),
               before="latency_ms")
