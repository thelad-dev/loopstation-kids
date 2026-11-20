"""Sets page of the parents' area: save the session as a set, open a saved one (mockups 14 and 15).

Nothing of this is on the child page. The dialog only talks to a
``SetSession``; opening hands the verified set to ``on_open`` and closes, the
app then replaces the session between two runs of its event loop.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from loopstation import sets
from loopstation.gui.icons import draw_icon
from loopstation.gui.parent_gate import PARENT_ACCENT, _IconLabel
from loopstation.gui.widgets import (
    ACCENT_GRAY,
    ACCENT_ORANGE,
    BACKGROUND,
    SURFACE,
    TEXT,
    TEXT_DIM,
    BigButton,
)
from loopstation.session import PreparedOpen, SetInfo, SetSession, list_sets
from loopstation.sets import SetError

ORANGE = "#FF9F0A"
GREEN = "#32D74B"
RED = "#FF3B30"
CARD = "#1B1B1F"
CARD_BORDER = "#26262B"
SELECTED = "#2E3355"  # list row and nav tint of the mockup

_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_name(text: str) -> str:
    """A set name that is safe as a file name; empty input becomes ``Set``."""
    name = _BAD_FILENAME_CHARS.sub(" ", text).strip().strip(".")
    return " ".join(name.split()) or "Set"


def target_path(folder: Path, name: str, as_file: bool, when: datetime) -> Path:
    """``<folder>/<name> <date>[.loopset]``; an existing set is never reused (``(2)``, ``(3)``, ...)."""
    stem = f"{clean_name(name)} {when:%Y-%m-%d}"
    suffix = sets.SET_SUFFIX if as_file else ""
    candidate = folder / (stem + suffix)
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def format_size(size: int) -> str:
    megabytes = size / 1_000_000
    text = f"{megabytes:.1f}".replace(".", ",")
    return f"{text} MB" if megabytes >= 0.1 else "< 0,1 MB"


def format_loop(grid: dict[str, int] | None) -> str:
    if not grid:
        return "frei"
    return f"{grid['frames'] / grid['rate']:.1f}".replace(".", ",") + " s Loop"


def format_when(created_at: str, *, with_time: bool = True) -> str:
    """Local date (and time) of the manifest's UTC stamp."""
    try:
        moment = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return created_at
    return f"{moment:%d.%m.%Y}" + (f", {moment:%H:%M}" if with_time else "")


class TabButton(QAbstractButton):
    """The two big tabs of the page: filled with the parents' colour when active."""

    def __init__(self, kind: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setText(text)
        self.setCheckable(True)
        self.setMinimumHeight(52)
        self.setFixedWidth(300)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(300, 52)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.isChecked()
        painter.setBrush(QColor(PARENT_ACCENT) if active else SURFACE)
        painter.setPen(Qt.PenStyle.NoPen if active else QPen(QColor("#3A3A41"), 1.5))
        painter.drawRoundedRect(rect, 16, 16)
        color = QColor("#111114") if active else QColor(TEXT)
        font = painter.font()
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(self.text())
        icon_size, gap = 24, 12
        left = rect.center().x() - (icon_size + gap + width) / 2
        icon_rect = QRectF(left, rect.center().y() - icon_size / 2, icon_size, icon_size)
        draw_icon(painter, self.kind, icon_rect, color)
        painter.setPen(color)
        painter.drawText(QRectF(left + icon_size + gap, rect.top(), width + 4, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class _SetRow(QAbstractButton):
    """One saved set in the list: folder icon, name, date line and (if any) a hint line."""

    def __init__(self, info: SetInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setCheckable(True)
        self.setFixedHeight(76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(info.name)

    @property
    def hint(self) -> str:
        return self.info.short

    @property
    def detail_line(self) -> str:
        info = self.info
        if info.manifest is None:
            return ""
        manifest = info.manifest
        parts = [format_when(manifest.created_at), f"{info.recorded_pads} Pads", format_loop(manifest.grid)]
        return " · ".join(parts)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        info = self.info
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        selected = self.isChecked()
        painter.setBrush(QColor(SELECTED) if selected else SURFACE)
        painter.setPen(QPen(QColor(PARENT_ACCENT), 2) if selected else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 16, 16)
        if info.error:
            accent = QColor(RED)
        elif info.notes:
            accent = QColor(ORANGE)
        else:
            accent = QColor(PARENT_ACCENT)
        draw_icon(painter, "folder", QRectF(rect.left() + 18, rect.center().y() - 15, 30, 30), accent)
        dim = info.error != ""
        title_font = painter.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_color = QColor(TEXT_DIM) if dim else QColor(TEXT)
        painter.setPen(title_color)
        painter.drawText(QRectF(rect.left() + 66, rect.top() + 10, rect.width() - 80, 26),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, info.name)
        small = painter.font()
        small.setPointSize(11)
        small.setBold(False)
        painter.setFont(small)
        second, color = self.detail_line, QColor(TEXT_DIM)
        if info.error or info.notes:
            second, color = self.hint, QColor("#FF8A80" if info.error else ORANGE)
        painter.setPen(color)
        room = int(rect.width() - 80)
        second = QFontMetrics(small).elidedText(second, Qt.TextElideMode.ElideRight, room)
        painter.drawText(QRectF(rect.left() + 66, rect.top() + 38, room, 24),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, second)
        painter.end()


class SetsDialog(QDialog):
    """Save the session as a set / open a saved one. Modal, fills the window it was opened from."""

    def __init__(
        self,
        session: SetSession,
        on_open: Callable[[PreparedOpen], None] | None = None,
        parent: QWidget | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._on_open = on_open
        self._clock = clock
        self.opened: PreparedOpen | None = None
        self.infos: list[SetInfo] = []
        self.rows: list[_SetRow] = []
        self.selected: SetInfo | None = None
        # Folder chooser; tests replace it.
        self.folder_chooser: Callable[[QWidget, str], str] = (
            lambda parent_, start: QFileDialog.getExistingDirectory(parent_, "Ordner für Sets", start))
        self.setWindowTitle("Sets")
        self.setModal(True)
        self.setStyleSheet(
            f"SetsDialog {{ background: {BACKGROUND.name()}; border: 5px solid {PARENT_ACCENT}; }} "
            f"QLabel, QRadioButton {{ color: {TEXT.name()}; font-size: 16px; }} "
            f"#card {{ background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 18px; }} "
            f"#good {{ background: #12201A; border: 1px solid #1F5A32; border-radius: 18px; }} "
            f"#warn {{ background: #2A2314; border: 2px solid {ORANGE}; border-radius: 18px; }} "
            f"QLineEdit {{ color: {TEXT.name()}; background: {SURFACE.name()}; font-size: 17px; "
            f"font-weight: bold; border: 2px solid {PARENT_ACCENT}; border-radius: 12px; "
            "padding: 12px 16px; } "
            "QRadioButton::indicator { width: 22px; height: 22px; border-radius: 12px; "
            f"background: {BACKGROUND.name()}; border: 2px solid #5A5A60; }} "
            "QRadioButton::indicator:checked { border: 2px solid "
            f"{PARENT_ACCENT}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, "
            f"stop:0 {PARENT_ACCENT}, stop:0.5 {PARENT_ACCENT}, stop:0.56 {BACKGROUND.name()}, "
            f"stop:1 {BACKGROUND.name()}); }}")

        # Header: back to the child page, the open lock, title.
        self.close_button = BigButton("back", "Zur Kinderseite", ACCENT_GRAY, min_height=64)
        self.close_button.setToolTip("Eltern-Modus beenden")
        self.close_button.clicked.connect(self.reject)
        title = QLabel("Elternbereich")
        title.setStyleSheet("font-size: 34px; font-weight: bold;")
        subtitle = QLabel("Sets · lokal, ohne Konto, ohne Internet")
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

        # Tabs.
        self.save_tab = TabButton("save", "Set speichern")
        self.open_tab = TabButton("folder", "Set öffnen …")
        self.save_tab.clicked.connect(lambda: self.show_tab("save"))
        self.open_tab.clicked.connect(lambda: self.show_tab("open"))
        tabs = QHBoxLayout()
        tabs.setSpacing(16)
        tabs.addWidget(self.save_tab)
        tabs.addWidget(self.open_tab)
        tabs.addStretch(1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_save_page())
        self.stack.addWidget(self._build_open_page())

        self.message = QLabel("")
        self.message.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(tabs)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.message)
        self.resize(1280, 800)
        self.show_tab("save")

    # -------------------------------------------------------------- pages

    @staticmethod
    def _card(title: str, name: str = "card") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName(name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 21px; font-weight: bold;")
        if title:
            layout.addWidget(heading)
        return card, layout

    @staticmethod
    def _small(text: str, color: str = TEXT_DIM.name(), size: int = 13) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {color}; font-size: {size}px;")
        return label

    @staticmethod
    def _facts(rows: list[tuple[str, str]]) -> tuple[QVBoxLayout, dict[str, QLabel]]:
        """Label and value pairs, value bold on the right."""
        box = QVBoxLayout()
        box.setSpacing(9)
        values: dict[str, QLabel] = {}
        for label, value in rows:
            line = QHBoxLayout()
            name = QLabel(label)
            name.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 15px;")
            shown = QLabel(value)
            shown.setStyleSheet("font-size: 15px; font-weight: bold;")
            shown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(name, 1)
            line.addWidget(shown)
            box.addLayout(line)
            values[label] = shown
        return box, values

    def _build_save_page(self) -> QWidget:
        page = QWidget()
        form_card, form = self._card("Aktuelle Sitzung als Set sichern")

        form.addWidget(self._bold("Name"))
        self.name_edit = QLineEdit("Loopstation")
        self.name_edit.textChanged.connect(self._update_target)
        form.addWidget(self.name_edit)

        form.addSpacing(8)
        form.addWidget(self._bold("Speichern als"))
        self.file_radio = QRadioButton("Eine Datei (.loopset)")
        self.file_radio.setChecked(True)
        self.file_radio.toggled.connect(self._update_target)
        self.folder_radio = QRadioButton("Ordner")
        recommended = QLabel("empfohlen")
        recommended.setStyleSheet(
            f"color: {PARENT_ACCENT}; background: #2E3355; border-radius: 9px; padding: 1px 9px; "
            "font-size: 12px; font-weight: bold;")
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_radio)
        file_row.addWidget(recommended)
        file_row.addStretch(1)
        form.addLayout(file_row)
        form.addWidget(self._indented("gepackt, gut zum Aufheben"))
        form.addWidget(self.folder_radio)
        form.addWidget(self._indented("gleiche Struktur, ungepackt"))

        form.addSpacing(8)
        form.addWidget(self._bold("Ort"))
        self.folder_edit = QLineEdit(str(self.session.sets_folder))
        self.folder_edit.textChanged.connect(self._update_target)
        self.choose_button = QPushButton("Ändern …")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.choose_button.setStyleSheet(
            f"QPushButton {{ color: {TEXT.name()}; background: {SURFACE.name()}; border: none; "
            "border-radius: 12px; font-size: 16px; font-weight: bold; padding: 14px 24px; } "
            "QPushButton:pressed { background: #3A3A41; }")
        self.choose_button.clicked.connect(self._choose_folder)
        place = QHBoxLayout()
        place.setSpacing(12)
        place.addWidget(self.folder_edit, 1)
        place.addWidget(self.choose_button)
        form.addLayout(place)
        self.target_label = self._small("")
        form.addWidget(self.target_label)
        form.addStretch(1)

        self.save_button = BigButton(
            "check", "Speichern", QColor(PARENT_ACCENT), checkable=True, min_height=60)
        self.save_button.setChecked(True)  # filled: the one main action
        self.save_button.clicked.connect(self._save_clicked)
        self.cancel_button = BigButton("close", "Abbrechen", ACCENT_GRAY, min_height=60)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addWidget(self.save_button, 5)
        buttons.addWidget(self.cancel_button, 5)
        form.addLayout(buttons)

        facts_card, facts_layout = self._card("Was im Set steckt")
        facts, self.summary_values = self._facts([
            ("Pads mit Aufnahme", ""), ("Aufnahmen inkl. Verlauf", ""), ("Takt", ""),
            ("Zurück-Schritte", ""), ("Einstellungen", ""), ("Größe ca.", ""),
        ])
        facts_layout.addLayout(facts)
        facts_layout.addStretch(1)

        good_card, good = self._card("", "good")
        self.safe_title = QLabel("Sicher gespeichert")
        self.safe_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        good.addWidget(self.safe_title)
        good.addWidget(self._small(
            "Erst fertig schreiben, dann umbenennen: ein Abbruch überschreibt kein altes Set halb.\n"
            "Nur lokal – keine Cloud.", TEXT.name(), 14))
        good.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(facts_card, 3)
        right.addWidget(good_card, 2)
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(20)
        columns.addWidget(form_card, 3)
        columns.addLayout(right, 2)
        return page

    def _build_open_page(self) -> QWidget:
        page = QWidget()
        list_card, list_layout = self._card("Gespeicherte Sets")
        self.folder_hint = self._small("")
        list_layout.addWidget(self.folder_hint)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(12)
        list_layout.addLayout(self.list_box)
        self.empty_label = self._small("Hier liegt noch kein Set. Mit „Set speichern“ entsteht das erste.",
                                       TEXT_DIM.name(), 15)
        list_layout.addWidget(self.empty_label)
        list_layout.addStretch(1)

        self.detail_card, detail = self._card("")
        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet("font-size: 21px; font-weight: bold;")
        detail.addWidget(self.detail_title)
        facts, self.detail_values = self._facts([
            ("Gespeichert", ""), ("Pads mit Aufnahme", ""), ("Takt", ""),
            ("Zurück-Schritte", ""), ("Wiederholen", "startet leer"), ("Format", ""),
        ])
        detail.addLayout(facts)
        self.detail_note = self._small("", ORANGE, 14)
        detail.addWidget(self.detail_note)
        detail.addStretch(1)

        # Question card: shown when the session has unsaved changes.
        self.unsaved_card, ask = self._card("", "warn")
        head = QHBoxLayout()
        sign = QLabel("⚠")
        sign.setStyleSheet(f"color: {ORANGE}; font-size: 26px;")
        question = QLabel("Aktuelle Sitzung ist nicht gesichert")
        question.setStyleSheet("font-size: 17px; font-weight: bold;")
        question.setWordWrap(True)
        head.addWidget(sign)
        head.addWidget(question, 1)
        ask.addLayout(head)
        ask.addWidget(self._small(
            "Öffnen ersetzt, was gerade auf den Pads ist.\nJetzt zuerst als Set sichern?",
            TEXT.name(), 14))
        ask.addStretch(1)
        self.save_then_open_button = BigButton(
            "check", "Erst sichern, dann öffnen", QColor(PARENT_ACCENT), checkable=True,
            min_height=48, font_pt=13)
        self.save_then_open_button.setChecked(True)
        self.save_then_open_button.clicked.connect(self._save_then_open)
        self.open_anyway_button = BigButton(
            "delete", "Ohne sichern", ACCENT_ORANGE, min_height=48, font_pt=13)
        self.open_anyway_button.clicked.connect(self._open_selected)
        self.cancel_open_button = BigButton("close", "Abbrechen", ACCENT_GRAY, min_height=48, font_pt=13)
        self.cancel_open_button.clicked.connect(self.reject)
        ask.addWidget(self.save_then_open_button)
        lower = QHBoxLayout()
        lower.setSpacing(12)
        lower.addWidget(self.open_anyway_button)
        lower.addWidget(self.cancel_open_button)
        ask.addLayout(lower)

        # Plain open button: shown when nothing would be lost.
        self.open_card, plain = self._card("")
        self.open_button = BigButton("play", "Öffnen", QColor(PARENT_ACCENT), checkable=True, min_height=60)
        self.open_button.setChecked(True)
        self.open_button.clicked.connect(self._open_selected)
        plain.addWidget(self._small("Die aktuelle Sitzung wird durch das Set ersetzt.", TEXT.name(), 14))
        plain.addWidget(self.open_button)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self.detail_card, 3)
        right.addWidget(self.unsaved_card, 3)
        right.addWidget(self.open_card, 2)
        columns = QHBoxLayout(page)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(20)
        columns.addWidget(list_card, 3)
        columns.addLayout(right, 2)
        return page

    @staticmethod
    def _bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 16px; font-weight: bold;")
        return label

    def _indented(self, text: str) -> QLabel:
        label = self._small(text)
        label.setContentsMargins(34, 0, 0, 0)
        return label

    # ---------------------------------------------------------- behaviour

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            self.setGeometry(parent.geometry())

    def show_tab(self, which: str) -> None:
        saving = which == "save"
        self.save_tab.setChecked(saving)
        self.open_tab.setChecked(not saving)
        self.stack.setCurrentIndex(0 if saving else 1)
        self.message.setText("")
        if saving:
            self._refresh_summary()
            self._update_target()
        else:
            self._refresh_list()
        if self.session.notices:
            self._say("  ".join(self.session.notices), warning=True)

    def _say(self, text: str, *, error: bool = False, warning: bool = False) -> None:
        color = RED if error else ORANGE if warning else GREEN
        self.message.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold;")
        self.message.setText(text)

    # save

    def _refresh_summary(self) -> None:
        info = self.session.summary()
        values = self.summary_values
        values["Pads mit Aufnahme"].setText(f"{info['recorded_pads']} von {info['pad_count']}")
        values["Aufnahmen inkl. Verlauf"].setText(f"{info['samples']} WAV")
        values["Takt"].setText(format_loop(info["grid"]))
        values["Zurück-Schritte"].setText(f"{info['undo_steps']} (bleiben erhalten)")
        values["Einstellungen"].setText("Kopie settings.toml" if info["has_settings"] else "keine Datei")
        values["Größe ca."].setText(format_size(info["bytes"]))

    def _folder(self) -> Path:
        return Path(self.folder_edit.text().strip() or str(self.session.sets_folder)).expanduser()

    def _target(self) -> Path:
        return target_path(self._folder(), self.name_edit.text(), self.file_radio.isChecked(), self._clock())

    def _update_target(self, *_args: object) -> None:
        kind = "Datei" if self.file_radio.isChecked() else "Ordner"
        self.target_label.setText(f"{kind}: {self._target().name}")

    def _choose_folder(self) -> None:
        chosen = self.folder_chooser(self, str(self._folder()))
        if chosen:
            self.folder_edit.setText(chosen)

    def _save_clicked(self) -> None:
        self.save_button.setChecked(True)  # keep it filled after the click toggled it
        self.save()

    def save(self, target: Path | None = None) -> Path | None:
        """Write the set; the message says how it went. Returns the path on success."""
        target = target if target is not None else self._target()
        try:
            self.session.save(target)
        except (SetError, OSError) as exc:
            self._say(str(exc), error=True)
            return None
        self._say(f"Gespeichert: {target}")
        self._refresh_summary()
        self._update_target()
        return target

    # open

    def _refresh_list(self) -> None:
        folder = self.session.sets_folder
        self.folder_hint.setText(str(folder))
        for row in self.rows:
            self.list_box.removeWidget(row)
            row.deleteLater()
        self.rows = []
        self.infos = list_sets(folder, self.session.sd)
        for info in self.infos:
            row = _SetRow(info)
            row.clicked.connect(lambda _checked=False, r=row: self._select(r))
            self.list_box.addWidget(row)
            self.rows.append(row)
        self.empty_label.setVisible(not self.rows)
        self.detail_card.setVisible(bool(self.rows))
        self._select(self.rows[0] if self.rows else None)

    def _select(self, row: _SetRow | None) -> None:
        for other in self.rows:
            other.setChecked(other is row)
        self.selected = None if row is None else row.info
        info = self.selected
        unsaved = self.session.unsaved()
        can_open = info is not None and info.usable
        self.open_card.setVisible(can_open and not unsaved)
        self.unsaved_card.setVisible(can_open and unsaved)
        self.detail_card.setVisible(info is not None)
        if info is None:
            return
        manifest = info.manifest
        self.detail_title.setText(info.name)
        values = self.detail_values
        if manifest is not None:
            values["Gespeichert"].setText(format_when(manifest.created_at))
            values["Pads mit Aufnahme"].setText(str(info.recorded_pads))
            values["Takt"].setText(format_loop(manifest.grid))
            values["Zurück-Schritte"].setText(f"{info.undo_steps} (bleiben)")
            values["Format"].setText(f"v{manifest.format_version} · passt" if not info.error else "")
        else:
            for key in ("Gespeichert", "Pads mit Aufnahme", "Takt", "Zurück-Schritte"):
                values[key].setText("–")
            values["Format"].setText("zu neu" if info.too_new else "unlesbar")
        values["Format"].setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {RED if info.error else TEXT.name()};")
        note = info.error or "\n".join(info.notes)
        self.detail_note.setStyleSheet(
            f"color: {'#FF8A80' if info.error else ORANGE}; font-size: 14px;")
        self.detail_note.setText(note)

    def _save_then_open(self) -> None:
        """Save the running session first (own name, never over an old set), then open the selection."""
        self.save_then_open_button.setChecked(True)
        stamp = self._clock()
        folder = self.session.sets_folder
        target = target_path(folder, f"Sicherung {stamp:%H-%M}", True, stamp)
        if self.save(target) is None:
            return  # the message says why; nothing is replaced
        self._open_selected()

    def _open_selected(self) -> None:
        self.open_button.setChecked(True)
        info = self.selected
        if info is None or not info.usable:
            return
        try:
            prepared = self.session.prepare_open(info.path)
        except (SetError, OSError) as exc:
            self._say(str(exc), error=True)
            return
        self.opened = prepared
        if self._on_open is not None:
            self._on_open(prepared)
        self.accept()
