"""Widgets of the "Geräte & Audio" area (mockup 10, plan 8, 11.1 and 12).

``HostApiList`` is the audio-system choice as a list of radio buttons with a short sentence and a badge
(standard, optional, ...) per entry. It only lists the host APIs the machine has, so on Linux there is no
ASIO and no WASAPI. Its interface is that of a drop-down editor of the settings page: ``set_choices`` and
``value`` (the stored text, "" = the platform's standard).
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QRadioButton, QVBoxLayout, QWidget

from loopstation.audio.devices import default_hostapi
from loopstation.gui.parent_gate import PARENT_ACCENT
from loopstation.gui.parent_nav import dim_label
from loopstation.gui.widgets import weak_slot

# What a host API is good for: (sentence, badge). Names as PortAudio reports them.
HOSTAPI_INFO: dict[str, tuple[str, str]] = {
    "Windows WASAPI": ("Nativ, mischt sich mit anderen Programmen", ""),
    "ASIO": ("Für Audio-Interfaces · oft exklusiv", "optional"),
    "Windows DirectSound": ("Ältere Schicht, mehr Verzögerung", "Kompatibilität"),
    "Windows WDM-KS": ("Direkt am Treiber, Gerät nur für die Loopstation", "exklusiv"),
    "MME": ("Hohe Verzögerung", "letzter Ausweg"),
    "ALSA": ("Direkt am Linux-Treiber (PipeWire und Pulse laufen darüber)", ""),
    "JACK Audio Connection Kit": ("Für Profi-Setups mit eigenem Audio-Server", "optional"),
    "OSS": ("Sehr alte Schicht", "letzter Ausweg"),
    "Core Audio": ("Nativ unter macOS", ""),
}
STANDARD_BADGE = "Standard"
SYSTEM_DEFAULT = "Systemstandard"
MISSING = " (nicht gefunden)"
PLATFORM_NAMES = (("win", "Windows"), ("darwin", "macOS"), ("linux", "Linux"))


def platform_name(platform: str = sys.platform) -> str:
    """The name of the system the page runs on, for the card title."""
    return next((name for key, name in PLATFORM_NAMES if platform.startswith(key)), "")


class _Badge(QLabel):
    def __init__(self, text: str, standard: bool) -> None:
        super().__init__(text)
        color, fill = (PARENT_ACCENT, "#2E3355") if standard else ("#AEAEB2", "#3A3A41")
        self.setStyleSheet(f"color: {color}; background: {fill}; font-size: 11.5px; font-weight: bold; "
                           "border-radius: 10px; padding: 2px 10px;")


class HostApiList(QWidget):
    """The audio systems as radio buttons; ``changed`` fires when the user picks another one."""

    changed = Signal()

    def __init__(
        self, selected: str = "", platform: str = sys.platform, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._platform = platform
        self._value = selected
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._group: QButtonGroup | None = None
        self.radios: dict[str, QRadioButton] = {}  # stored value ("" for the standard) -> radio button
        self.by_name: dict[str, QRadioButton] = {}  # audio system name -> radio button
        self.set_choices([], selected)

    def value(self) -> str:
        return self._value

    def labels(self) -> list[str]:
        """The names shown, in order."""
        return [radio.text() for radio in self.radios.values()]

    def select(self, name: str) -> None:
        """Pick the audio system ``name`` as if the user had (``changed`` fires)."""
        radio = self.by_name.get(name)
        if radio is not None:
            radio.click()

    def set_choices(self, choices: list[tuple[str, str]], selected: str) -> None:
        """Show ``choices`` (label, name); an unlisted ``selected`` name stays, marked, so it is not lost."""
        names = [name for _label, name in choices]
        standard = default_hostapi(names, self._platform) if names else None
        entries = [(name, name) for name in names]
        if selected and selected not in names:
            entries.append((selected + MISSING, selected))
        if standard is None and (not entries or not selected):
            entries.insert(0, (SYSTEM_DEFAULT, ""))
        self._value = selected
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # gone at once: until it is deleted Tab could still land on it
                item.widget().deleteLater()
        self._group = QButtonGroup(self)
        self.radios, self.by_name = {}, {}
        shown = selected or standard or ""
        for label, name in entries:
            key = "" if name == standard else name
            self.radios[key] = self.by_name[name] = self._entry(label, name, name == standard, name == shown)

    def _entry(self, label: str, name: str, standard: bool, checked: bool) -> QRadioButton:
        sentence, badge = HOSTAPI_INFO.get(name, ("", ""))
        radio = QRadioButton(label)
        radio.setStyleSheet("font-size: 16px; font-weight: 500;")
        radio.setChecked(checked)
        assert self._group is not None
        self._group.addButton(radio)
        radio.toggled.connect(weak_slot(self._toggled, "" if standard else name, pass_signal_args=True))
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(radio)
        if standard:
            head.addWidget(_Badge(STANDARD_BADGE, True))
        elif badge:
            head.addWidget(_Badge(badge, False))
        head.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addLayout(head)
        if sentence:
            hint = dim_label(sentence, 13)
            hint.setContentsMargins(30, 0, 0, 0)
            box.addWidget(hint)
        holder = QWidget()
        holder.setLayout(box)
        box.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(holder)
        return radio

    def _toggled(self, value: str, on: object) -> None:
        if on and value != self._value:
            self._value = value
            self.changed.emit()
