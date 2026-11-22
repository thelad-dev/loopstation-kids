"""Card "Aktueller Takt der Sitzung" of the side panel "Takt" (mockup 11, plan 2.2 rule 7).

Four tiles (two by two, the panel is narrow) show tempo, time signature, bar length and where the bar
came from.
The panel owns no state: it reads ``Controller.grid_info()`` and, while the
session has no grid, the outcome of the last grid-setting recording.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from loopstation.gui.parent_nav import fitted_font
from loopstation.gui.widgets import TEXT, TEXT_DIM

if TYPE_CHECKING:
    from loopstation.controller import Controller, GridInfo

NO_GRID = "-"
# How a source reads in the tile: (title, hint for the parents).
SOURCES = {
    "onset": "Klatschen",
    "duration": "Aufnahmelänge",
    "parent_bpm": "Eltern-BPM",
    "free_pad": "Freies Pad",
}
TEMPO_HINTS = {
    "onset": "gemessen",
    "duration": "aus der Aufnahmelänge",
    "parent_bpm": "von den Eltern eingestellt",
    "free_pad": "aus einem freien Pad",
}
# Why a recording left the session without a grid (``GridResult.reason``).
NO_GRID_REASONS = {
    "too_long": "Aufnahme zu lang",
    "too_short": "Aufnahme zu kurz",
    "onsets_without_beat_and_length_implausible": "Schläge unklar, Aufnahme zu lang",
}
NO_GRID_HINT = "Ohne Takt (freie Sitzung) wird nichts geraten: lieber kein Raster als ein falsches."


def format_seconds(seconds: float) -> str:
    return f"{seconds:.2f} s".replace(".", ",")


def tiles(info: GridInfo | None, reason: str | None = None) -> list[tuple[str, str, str]]:
    """``(label, value, hint)`` of the four tiles."""
    if info is None:
        why = NO_GRID_REASONS.get(reason or "", "freie Sitzung")
        return [("Tempo", NO_GRID, "kein Takt"), ("Taktart", NO_GRID, why),
                ("Takt-Länge", NO_GRID, "kein Takt"), ("Quelle", "Kein Takt", why)]
    pad = "" if info.pad is None else f" · Pad {info.pad + 1}"
    return [
        ("Tempo", f"{round(info.bpm)} BPM", TEMPO_HINTS.get(info.source, "")),
        ("Taktart", info.signature, "Standard" if info.signature == "4/4" else "gewählt"),
        ("Takt-Länge", format_seconds(info.seconds), f"1 Takt = {info.beats} Schläge"),
        ("Quelle", SOURCES.get(info.source, info.source), pad.removeprefix(" · ") or "für alle Pads"),
    ]


class _Tile(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("grid_tile")
        self.setFixedHeight(112)
        self.setStyleSheet("#grid_tile { background: #26262B; border-radius: 14px; }")
        self.label = QLabel(label)
        self.label.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 14px; font-weight: 600;")
        self.value = QLabel()
        # The tile must not grow with its text (two tiles in a row in a narrow panel).
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._size = 0
        self.hint = QLabel()
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hint.setStyleSheet("color: #AEAEB2; font-size: 13px;")
        self.hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(0)
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.value)
        layout.addSpacing(8)
        layout.addWidget(self.hint)

    def show_values(self, label: str, value: str, hint: str) -> None:
        self.label.setText(label)
        self.value.setText(value)
        self.hint.setText(hint)
        self._fit()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """The value as large as the tile allows: a long word ("Aufnahmelänge") gets a smaller font."""
        room = self.contentsRect().width() - 32
        font = fitted_font(self.value.text(), room, 28, QFont.Weight.ExtraBold, 12)
        size = font.pixelSize()
        if size != self._size:
            self._size = size
            self.value.setStyleSheet(f"color: {TEXT.name()}; font-size: {size}px; font-weight: 800;")


class GridPanel(QFrame):
    """The card with the four tiles; ``refresh()`` follows the controller."""

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("card")
        heading = QLabel("Aktueller Takt der Sitzung")
        heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        heading.setWordWrap(True)
        self.tiles = [_Tile(name) for name in ("Tempo", "Taktart", "Takt-Länge", "Quelle")]
        row = QGridLayout()
        row.setSpacing(12)
        for index, tile in enumerate(self.tiles):
            row.addWidget(tile, index // 2, index % 2)
        self.note = QLabel(NO_GRID_HINT)
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addLayout(row)
        layout.addWidget(self.note)
        self.refresh()

    def refresh(self) -> None:
        info = self.controller.grid_info()
        last = self.controller.last_grid
        values = tiles(info, None if last is None else last.reason)
        for tile, (label, value, hint) in zip(self.tiles, values, strict=True):
            tile.show_values(label, value, hint)
        self.note.setVisible(info is None)

    def texts(self) -> list[tuple[str, str, str]]:
        """What the tiles show now, for tests."""
        return [(t.label.text(), t.value.text(), t.hint.text()) for t in self.tiles]
