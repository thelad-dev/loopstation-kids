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

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
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

from loopstation.config import (
    RESTART_KEYS,
    ConfigError,
    Settings,
    load_settings,
    parse_settings,
    settings_values,
    write_settings,
)
from loopstation.gui.parent_gate import PARENT_ACCENT, _IconLabel
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_GREEN,
    BACKGROUND,
    SURFACE,
    TEXT,
    TEXT_DIM,
    BigButton,
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
        self.setWindowTitle("Elternbereich")
        self.setModal(True)
        self.setStyleSheet(
            f"SettingsDialog {{ background: {BACKGROUND.name()}; border: 5px solid {PARENT_ACCENT}; }} "
            f"QScrollArea, #settings_inner {{ background: transparent; border: none; }} "
            f"QLabel, QCheckBox {{ color: {TEXT.name()}; font-size: 16px; }} "
            "#card { background: #1B1B1F; border: 1px solid #26262B; border-radius: 18px; } "
            f"QSpinBox, QDoubleSpinBox, QLineEdit {{ color: {TEXT.name()}; background: {SURFACE.name()}; "
            f"font-size: 16px; border: 1px solid {PARENT_ACCENT}; border-radius: 10px; padding: 6px 10px; }} "
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

        self.editors: dict[str, _Editor] = {}
        shown = self._file_settings()
        values = settings_values(shown)
        self._pending = [f.label for f in FIELDS if f.restart and values[f.key] != getattr(running, f.key)]
        switches, numbers = QVBoxLayout(), QFormLayout()
        switches.setSpacing(14)
        numbers.setHorizontalSpacing(24)
        numbers.setVerticalSpacing(12)
        for field in FIELDS:
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
        inner_layout.addWidget(self._card("Loop-Verhalten und Aufnahme", switches))
        inner_layout.addWidget(self._card("Zahlenwerte", numbers))
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
        # Fill the window it was opened from, like the page in the mockup.
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            self.setGeometry(parent.geometry())

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
        self.saved = True
        labels = {f.key: f.label for f in FIELDS}
        if restart:
            names = ", ".join(labels.get(key, key) for key in restart)
            self._say(f"Gespeichert, {RESTART_TEXT}: {names}", warning=True)
        else:
            self._say("Gespeichert und übernommen.")
        return True
