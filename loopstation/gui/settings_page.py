"""Settings page of the parents' area.

The fields are a plain list (``FIELDS``). A later package adds a setting to
the page with one entry, no change to this dialog::

    register_field(Field("auto_gain", "Auto-Gain", "bool", hint="Standard: aus."))

(plus the key in ``Settings``, its check in ``parse_settings`` and its comment
in ``config.SETTING_COMMENTS``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from loopstation.config import (
    RESTART_KEYS,
    ConfigError,
    Settings,
    load_settings,
    parse_settings,
    settings_values,
    write_settings,
)
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_GREEN,
    BACKGROUND,
    SURFACE,
    TEXT,
    TEXT_DIM,
    BigButton,
    big_font,
)

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


@dataclass(frozen=True)
class Field:
    """One row of the page. ``kind``: ``bool``, ``int``, ``float``, ``auto_float`` or ``text``."""

    key: str
    label: str
    kind: str
    low: float = 0
    high: float = 1000
    hint: str = ""
    suffix: str = ""

    @property
    def restart(self) -> bool:
        return self.key in RESTART_KEYS


FIELDS: list[Field] = [
    Field("loop_sync", "Loops im Takt halten", "bool",
          hint="Die erste Aufnahme bestimmt die Loop-Länge, alle weiteren passen dazu."),
    Field("sound_effects", "Piepton bei Aufnahme", "bool"),
    Field("max_record_seconds", "Längste Aufnahme", "float", 1, 120, suffix=" s"),
    Field("latency_ms", "Latenz Lautsprecher zu Mikrofon", "auto_float", 0, 1000, suffix=" ms",
          hint="Der Auto-Wert hängt vom Gerät ab. Mit Mikrofon und Kopfhörer gegenhören: "
               "klingen neue Loops zu spät, die Zahl erhöhen."),
    Field("launchpad", "Launchpad benutzen", "bool"),
    Field("fullscreen", "Vollbild", "bool"),
    Field("rows", "Zeilen", "int", 1, 16),
    Field("cols", "Spalten", "int", 1, 16),
    Field("sample_rate", "Abtastrate", "int", 8000, 192000, suffix=" Hz"),
    Field("data_dir", "Datenordner", "text"),
]


def register_field(field: Field, before: str | None = None) -> None:
    """Add ``field`` to the page (at the end, or in front of the field ``before``)."""
    if any(f.key == field.key for f in FIELDS):
        raise ValueError(f"Feld '{field.key}' gibt es schon")
    index = next((i for i, f in enumerate(FIELDS) if f.key == before), len(FIELDS))
    FIELDS.insert(index, field)


class _Editor:
    """The input widget of one field and how to read and set its value."""

    def __init__(self, field: Field, value: Any) -> None:
        self.field = field
        self.widget: QWidget
        self._auto: QCheckBox | None = None
        kind = field.kind
        if kind == "bool":
            self._box = QCheckBox()
            self._box.setChecked(bool(value))
            self.widget = self._box
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
    """

    def __init__(
        self,
        config_path: Path,
        running: Settings,
        apply: Callable[[Settings], list[str]],
        template: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.running = running
        self._apply = apply
        self._template = template
        self.saved = False
        self.setWindowTitle("Einstellungen")
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog, QScrollArea, #settings_inner {{ background: {BACKGROUND.name()}; }} "
            f"QLabel, QCheckBox {{ color: {TEXT.name()}; font-size: 16px; }} "
            f"QSpinBox, QDoubleSpinBox, QLineEdit {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
            "font-size: 16px; border: 1px solid #3A3A41; border-radius: 6px; padding: 4px 8px; } "
            "QSpinBox:disabled, QDoubleSpinBox:disabled { color: #5A5A60; } "
            "QCheckBox::indicator { width: 22px; height: 22px; border-radius: 5px; "
            f"background: {SURFACE.name()}; border: 1px solid #5A5A60; }} "
            f"QCheckBox::indicator:checked {{ background: {ACCENT_GREEN.name()}; }}")

        title = QLabel("Einstellungen für Erwachsene")
        title.setFont(big_font(24))
        title.setStyleSheet(f"color: {TEXT.name()};")

        self.editors: dict[str, _Editor] = {}
        shown = self._file_settings()
        values = settings_values(shown)
        self._pending = [f.label for f in FIELDS if f.restart and values[f.key] != getattr(running, f.key)]
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(10)
        for field in FIELDS:
            editor = _Editor(field, values[field.key])
            self.editors[field.key] = editor
            label = field.label + (f" ({RESTART_TEXT})" if field.restart else "")
            row = QVBoxLayout()
            row.setSpacing(2)
            row.addWidget(editor.widget)
            if field.hint:
                hint = QLabel(field.hint)
                hint.setWordWrap(True)
                hint.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
                row.addWidget(hint)
            form.addRow(label, row)

        inner = QWidget()
        inner.setObjectName("settings_inner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.addLayout(form)
        for text in NOTES:
            note = QLabel(text)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px;")
            inner_layout.addWidget(note)
        inner_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.close_button = BigButton("close", "Schließen", ACCENT_GRAY)
        self.close_button.clicked.connect(self.reject)
        self.save_button = BigButton("check", "Speichern", ACCENT_GREEN)
        self.save_button.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.setSpacing(24)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self.resize(760, 640)
        if self._pending:
            self._say(f"Gespeichert, {RESTART_TEXT}: " + ", ".join(self._pending), warning=True)

    def _file_settings(self) -> Settings:
        """What the file says now (it may hold restart values not running yet), else the running ones."""
        try:
            return load_settings(self.config_path)
        except ConfigError:
            return self.running

    def _say(self, text: str, warning: bool = False, error: bool = False) -> None:
        color = "#FF3B30" if error else "#FF9F0A" if warning else "#32D74B"
        self.message.setStyleSheet(f"color: {color}; font-size: 15px;")
        self.message.setText(text)

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
        self.saved = True
        labels = {f.key: f.label for f in FIELDS}
        if restart:
            names = ", ".join(labels.get(key, key) for key in restart)
            self._say(f"Gespeichert, {RESTART_TEXT}: {names}", warning=True)
        else:
            self._say("Gespeichert und übernommen.")
        return True
