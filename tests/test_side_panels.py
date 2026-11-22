"""The tools of the parents' view as side panels beside the pads (Loopstation 2, mockup L2-05).

Each tool opens its panel to the right of the pads in the same window; the same tool again, Esc or
"Pads" closes it. The settings panels ("Pegel", "Geräte", "Takt", "System") have one way of saving:
at once. Every panel fits 1024 x 640 without a sideways scroll bar and without a cut text.
"""

from __future__ import annotations

import gc
import sys
import weakref
from dataclasses import fields

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel, QScrollArea, QWidget

from loopstation.config import Settings, load_settings
from loopstation.controller import Controller
from loopstation.gui import settings_panels
from loopstation.gui.changes_page import ChangesPage
from loopstation.gui.detail_panel import DetailPanel, LoopTab, PadTab, RecordTab
from loopstation.gui.export_dialog import ExportPage
from loopstation.gui.main_window import TOOL_HEADS, MainWindow
from loopstation.gui.parent_nav import WIDE_PAGE, CardGrid, breakable, dim_label
from loopstation.gui.sets_page import SetsPage
from loopstation.gui.settings_panels import FIELDS, SETTINGS_PANELS, SettingsPanels, panel_of
from loopstation.gui.side_panel import SAVED_LINE
from loopstation.gui.tempo_card import TempoCard
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS
from loopstation.session import SetSession
from loopstation.store import EventStore

TOOLS = ("changes", "sets", "export", "levels", "devices", "system", "tempo")
DETAIL_TABS = ("loop", "pad", "record")  # the tabs of the detail panel under the pads
SIZES = [(1024, 640), (1280, 800), (1920, 1080)]
INTERNAL_KEYS = ("sample_rate", "data_dir", "max_level_db", "input_gain_db", "latency_ms", "audio_hostapi",
                 "stretch_engine", "rubberband", "time_signature", "parent_idle_minutes", "duration")


class Parts:
    def __init__(self, tmp_path, clock, size=(1280, 800)):
        settings = make_settings(tmp_path / "live", auto_grid=True)
        self.store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
        self.audio = FakeAudio(clock)
        self.controller = Controller(self.store, self.audio, settings, clock=clock)
        self.controller.startup()
        self.config = tmp_path / "settings.toml"
        self.config.write_text("# test\nvolume = 0.5\n", encoding="utf-8")
        session = SetSession(self.controller, self.config, clock=clock, sets_folder=tmp_path / "sets")
        self.window = MainWindow(self.controller, None, [], config_path=self.config, set_session=session)
        self.window.timer.stop()
        self.window.resize(*size)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.window.enter_parent_mode()
        self.view = self.window.parent_view
        self.clock = clock

    def record(self, pad: int, seconds: float) -> None:
        self.controller.press(pad)
        self.clock.advance(seconds)
        self.controller.press(pad)

    def open(self, key: str) -> QWidget:
        """Open the tool ``key`` the way the parents do (its button, the bar chip)."""
        view = self.view
        if key == "tempo":
            view.bar_chip.click()
        else:
            view.toolbar.buttons[key].click()
        QTest.qWait(20)
        assert view.panel_key == key
        return view.side_panel.current_page()

    def open_tab(self, key: str) -> QWidget:
        """Unfold the detail panel on its tab ``key`` (a tap on the tab)."""
        detail = self.view.detail
        detail.tab_buttons[key].click()
        QTest.qWait(20)
        assert detail.is_open and detail.tab == key and self.view.panel_key is None
        return detail.pages[key]

    def close(self) -> None:
        self.window.leave_parent_mode()
        self.window.close()
        self.store.close()


@pytest.fixture
def parts(qapp, tmp_path, clock):
    p = Parts(tmp_path, clock)
    yield p
    p.close()


def panels_of(parts: Parts) -> SettingsPanels:
    panels = parts.window.settings_panels
    assert panels is not None
    return panels


# ------------------------------------------------------------- open and close


@pytest.mark.parametrize("key", TOOLS)
def test_every_tool_opens_its_panel_right_of_the_pads(parts, key):
    view = parts.view
    page = parts.open(key)
    panel = view.side_panel
    icon, title, line = TOOL_HEADS[key]
    assert panel.isVisible() and panel.title.text() == title
    # Right of the pads, below the header, inside the window; the pads are narrower but all there.
    root = parts.window.view_host
    box = panel.geometry().translated(panel.parentWidget().mapTo(root, QPoint(0, 0)))
    assert root.rect().contains(box)
    header = view.header.geometry()
    assert box.top() >= header.bottom()
    for tile in view.tiles:
        body = tile.body().translated(tile.mapTo(root, QPoint(0, 0)).toPointF())
        assert body.right() < box.left() and body.width() > 60 and tile.isVisible()
    assert view.detail.geometry().right() < box.left() and not view.detail.is_open
    # The lit tool is the open one ("Takt" has no button of its own).
    lit = [name for name, button in view.toolbar.buttons.items() if button.isChecked()]
    assert lit == ([key] if key in view.toolbar.buttons else [])
    assert page.isVisible() and panel.isAncestorOf(page)


def test_the_same_tool_again_esc_and_pads_close_the_panel(parts):
    view, window = parts.view, parts.window
    pads_box = view.grid.geometry()
    parts.open("levels")
    narrow = view.grid.geometry()
    assert narrow.width() < pads_box.width()
    view.toolbar.buttons["levels"].click()  # the same tool again
    assert view.panel_key is None and not view.side_panel.isVisible()
    assert view.grid.geometry() == pads_box and view.toolbar.buttons["pads"].isChecked()
    parts.open("export")
    QTest.keyClick(window, Qt.Key.Key_Escape)  # Esc closes the top layer
    assert view.panel_key is None and window.parent_mode
    parts.open("devices")
    view.toolbar.buttons["pads"].click()
    assert view.panel_key is None and view.toolbar.buttons["pads"].isChecked()
    parts.open("tempo")
    view.side_panel.close_button.click()  # the cross in the head
    assert view.panel_key is None
    QTest.keyClick(window, Qt.Key.Key_Escape)  # nothing open: Esc does what it did before
    assert window.parent_mode


def test_another_tool_takes_the_place_and_a_page_is_built_once(parts):
    view = parts.view
    first = parts.open("changes")
    parts.open("export")
    assert view.panel_key == "export" and not first.isVisible()
    assert parts.open("changes") is first  # kept while the parents' view is shown


def test_enter_opens_the_detail_panel_of_the_chosen_pad_and_follows_the_choice(parts):
    parts.record(0, 2.0)
    parts.record(2, 2.0)
    window, view = parts.window, parts.view
    window.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Return)
    detail = view.detail
    page = detail.loop_tab
    assert detail.is_open and detail.tab == "loop" and page.isVisible() and page.pad == 0
    assert detail.title == "Pad 1"
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert page.pad == 2 and detail.title == "Pad 3"
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert not detail.is_open


def test_keys_typed_into_a_panel_stay_in_the_panel(parts):
    parts.record(0, 2.0)
    view = parts.view
    parts.open("system")
    edit = panels_of(parts).editors["data_dir"]._edit
    edit.setFocus()
    QTest.keyClick(edit, Qt.Key.Key_Space)
    QTest.keyClick(edit, Qt.Key.Key_Right)
    assert view.selected == 0 and parts.audio.calls.count(("play", 0, False)) == 0
    assert edit.text().endswith(" ")
    # Enter in a text field is not the key of the view (the detail panel): the field keeps it.
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert view.panel_key == "system"


def test_leaving_the_parents_view_takes_the_panel_with_it(parts):
    parts.open("levels")
    parts.view.mode_switch.kids_button.click()
    assert not parts.window.parent_mode and parts.window.settings_panels is None
    parts.window.enter_parent_mode()
    assert parts.window.parent_view.panel_key is None  # a new visit starts with the pads


# ---------------------------------------------------------- one way of saving


@pytest.mark.parametrize("key", SETTINGS_PANELS)
def test_a_settings_panel_says_it_acts_at_once_and_has_no_save_button(parts, key):
    page = parts.open(key)
    assert parts.view.side_panel.line.text() == SAVED_LINE
    words = [button.text() for button in page.findChildren(QAbstractButton)]
    assert not any("Speichern" in word or "Sichern" in word for word in words), words


def test_a_change_is_saved_and_said_in_the_head(parts):
    parts.open("system")
    head = parts.view.side_panel
    panels_of(parts).editors["fullscreen"]._box.setChecked(True)
    assert load_settings(parts.config).fullscreen is True and parts.controller.settings.fullscreen
    assert head.message() == "Gespeichert: Vollbild"
    parts.window.showMaximized()


def test_a_refusal_stays_in_the_head_when_the_panel_opens_again(parts):
    parts.open("system")
    edit = panels_of(parts).editors["data_dir"]._edit
    edit.setText(" ")
    edit.editingFinished.emit()
    head = parts.view.side_panel
    assert "„Datenordner“" in head.message()
    parts.open("export")
    assert head.message() == ""  # the export has its own line
    parts.open("system")
    assert "„Datenordner“" in head.message()


# ------------------------------------------------------------------ contents


def test_every_field_has_an_editor_that_sits_on_its_panel(parts):
    panels = panels_of_all(parts)
    keys = {f.key for f in FIELDS} | set(settings_panels.DEVICE_KEYS)
    assert set(panels.editors) == {f.name for f in fields(Settings)} == keys
    for key in keys:
        assert panels.page(panel_of(key)).isAncestorOf(panels.editors[key].widget), key


def panels_of_all(parts: Parts) -> SettingsPanels:
    for key in ("levels", "devices", "tempo", "system"):
        parts.open(key)
    return panels_of(parts)


def test_the_switches_sit_where_the_mockup_has_them(parts):
    panels = panels_of_all(parts)
    for key in ("auto_grid", "loop_sync", "stretch_to_grid", "free_pad_on_grid", "metronome_tone"):
        assert panel_of(key) == "tempo", key
    for key in ("auto_gain", "soft_seam", "peak_meter", "max_level_db", "input_gain_db"):
        assert panel_of(key) == "levels", key
    for key in ("rows", "cols", "sample_rate", "data_dir", "launchpad", "fullscreen", "max_record_seconds",
                "sound_effects", "record_start_tone", "stretch_engine", "snap_markers", "export_cue_points",
                "parent_unlock_minutes", "parent_idle_minutes"):
        assert panels.page("system").isAncestorOf(panels.editors[key].widget), key


def test_the_tempo_correction_is_the_one_card_of_the_tempo_panel(parts):
    panels = panels_of_all(parts)
    assert panels.page("tempo").findChildren(TempoCard) == [panels.tempo_card]
    assert not any(parts.open_tab(key).findChildren(TempoCard) for key in DETAIL_TABS)


def test_the_level_panel_keeps_the_must_say_text_about_dbfs_and_who(parts):
    page = parts.open("levels")
    texts = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "dBFS ist nicht dB am Ohr" in texts and "WHO: 75 dBA" in texts
    assert "Höchste Lautstärke (nur Eltern)" in texts and "Mikrofon" in texts and "Limiter" in texts
    assert "Pegel automatisch nachziehen" in texts and "Naht weich zeichnen" in texts  # mockup L2-05
    assert "Zu laut gewesen" in texts


def test_the_device_and_system_panels_have_their_sections(parts):
    texts = " | ".join(label.text() for label in parts.open("devices").findChildren(QLabel))
    for title in ("Mikrofon (Eingang)", "Lautsprecher / Kopfhörer (Ausgang)", "Audio-System",
                  "Verzögerung (Latenz)", "Für gutes Looping"):
        assert title in texts, title
    editor = panels_of(parts).editors["latency_ms"]
    assert editor._auto.text() == "Automatisch" and editor._manual.text() == "Von Hand"
    texts = " | ".join(label.text() for label in parts.open("system").findChildren(QLabel))
    for title in ("Bedienung", "Aufnahme", "Bearbeiten und Sichern", "Elternansicht",
                  "Raster, Klang und Ordner", "Lokal · ohne Konto · ohne Internet"):
        assert title in texts, title


def test_the_test_tone_plays_through_the_effects_path(parts):
    parts.open("devices")
    panels = panels_of(parts)
    assert panels.tone_button is not None
    panels.tone_button.click()
    assert len(parts.audio.effects) == 1
    tone = parts.audio.effects[0]
    assert len(tone) > 0 and abs(tone).max() <= 0.2  # quiet


def test_without_a_controller_the_panels_are_there_but_the_live_cards_are_not(qapp, tmp_path):
    panels = SettingsPanels(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
    panels.build_all()
    assert panels.panel is None and panels.tone_button is None and panels.tempo_card is None
    assert panels.page("levels").isAncestorOf(panels.editors["volume"].widget)  # the plain rows


def test_no_internal_key_in_any_text_of_the_panels(parts):
    parts.record(0, 2.0)
    texts = []
    for key in TOOLS:
        page = parts.open(key)
        texts += [label.text() for label in page.findChildren(QLabel)]
        texts += [button.text() for button in page.findChildren(QAbstractButton)]
        texts.append(parts.view.side_panel.line.text())
    for key in DETAIL_TABS:
        page = parts.open_tab(key)
        texts += [w.text() for w in page.findChildren(QLabel) + page.findChildren(QAbstractButton)]
        texts += [w.toolTip() for w in page.findChildren(QWidget)]
        texts.append(parts.view.detail.open_info)
    joined = " | ".join(texts)
    for key in INTERNAL_KEYS:
        assert key not in joined, key


def test_the_audio_system_is_a_list_of_the_systems_the_machine_has(qapp, tmp_path, monkeypatch):
    from loopstation.gui.devices_page import HostApiList

    monkeypatch.setattr(sys, "platform", "linux")
    hostapis = HostApiList("", "linux")
    hostapis.set_choices([("ALSA", "ALSA"), ("JACK Audio Connection Kit", "JACK Audio Connection Kit")], "")
    assert hostapis.labels() == ["ALSA", "JACK Audio Connection Kit"]
    assert hostapis.value() == "" and hostapis.radios[""].isChecked()  # ALSA is the standard of Linux
    texts = " ".join(label.text() for label in hostapis.findChildren(QLabel))
    assert "Standard" in texts and "optional" in texts and "ASIO" not in texts
    changes = []
    hostapis.changed.connect(lambda: changes.append(hostapis.value()))
    hostapis.select("JACK Audio Connection Kit")
    assert changes == ["JACK Audio Connection Kit"]
    hostapis.select("ALSA")
    assert changes[-1] == ""  # back to the platform standard


def test_a_saved_audio_system_that_is_gone_stays_listed_and_marked(qapp):
    from loopstation.gui.devices_page import HostApiList

    hostapis = HostApiList("ASIO", "linux")
    hostapis.set_choices([("ALSA", "ALSA")], "ASIO")
    assert hostapis.labels() == ["ALSA", "ASIO (nicht gefunden)"]
    assert hostapis.value() == "ASIO"


def test_asio_is_offered_on_windows_only(qapp, tmp_path, monkeypatch):
    rows = {}
    for platform in ("linux", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        panels = SettingsPanels(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
        panels.page("devices")
        rows[platform] = not panels._asio_row.isHidden()
        assert "asio" in panels.editors  # the setting itself is there on every system
        assert "Neustart" in panels.restart_notes["asio"].text()  # said at the switch
    assert rows == {"linux": False, "win32": True}


# ------------------------------------------------------------- every size


@pytest.mark.parametrize("size", SIZES)
def test_every_panel_fits_without_a_sideways_scroll_bar_or_a_cut_text(qapp, tmp_path, clock, size):
    """No sideways scroll, no squeezed page, no single-line text cut off (a word like "(Ausgan" is a bug)."""
    p = Parts(tmp_path, clock, size)
    try:
        p.record(0, 2.0)
        p.record(4, 4.0)
        problems = []
        for key in TOOLS:
            page = p.open(key)
            tabs = ("save", "open") if key == "sets" else (None,)
            for tab in tabs:
                if tab is not None:
                    page.show_tab(tab)
                QTest.qWait(30)
                problems += fit_problems(key, page)
        p.window.close_tool()
        for key in DETAIL_TABS:
            page = p.open_tab(key)
            problems += fit_problems(key, page)
            tiles = min(tile.body().height() for tile in p.view.tiles)
            if tiles < 70:  # the pads stay playable under the unfolded panel
                problems.append((key, "tiles", tiles))
        assert not problems, (size, problems)
    finally:
        p.close()


def fit_problems(key: str, page: QWidget) -> list[tuple]:
    problems: list[tuple] = []
    areas = page.findChildren(QScrollArea) + ([page] if isinstance(page, QScrollArea) else [])
    for area in areas:
        if not area.isVisible():
            continue
        inner = area.widget()
        if area.horizontalScrollBar().maximum() > 0:
            problems.append((key, "sideways scroll bar"))
        if inner is not None and inner.minimumSizeHint().width() > area.viewport().width():
            problems.append((key, "content wider than the panel", inner.minimumSizeHint().width()))
    hint = page.minimumSizeHint()
    if hint.width() > page.width() or hint.height() > page.height():
        problems.append((key, "page squeezed", hint, page.size()))
    for label in page.findChildren(QLabel):
        text = label.text()
        rich = label.textFormat() == Qt.TextFormat.RichText
        if not label.isVisible() or not text or label.wordWrap() or rich:
            continue
        if label.fontMetrics().horizontalAdvance(text) > label.contentsRect().width():
            problems.append((key, "cut", text))
    return problems


def test_the_scroll_bars_of_the_panels_are_the_dark_ones(parts):
    assert DARK_SCROLLBAR_QSS in parts.view.side_panel.styleSheet()
    for key in ("sets", "export"):  # the pages also bring the style when they stand alone
        assert DARK_SCROLLBAR_QSS in parts.open(key).styleSheet(), key
    assert DARK_SCROLLBAR_QSS in DetailPanel(parts.controller).styleSheet()
    areas = [a for key in TOOLS for a in parts.open(key).findChildren(QScrollArea)]
    areas += [a for key in DETAIL_TABS for a in parts.open_tab(key).findChildren(QScrollArea)]
    areas += [parts.open(key) for key in SETTINGS_PANELS]
    assert len(areas) >= 8 and all(isinstance(a, QScrollArea) for a in areas)


@pytest.mark.parametrize("path", [r"C:\Users\runneradmin\AppData\Local\Temp\pytest-of-runneradmin\live",
                                  "/home/kind/Dokumente/Loopstation/Exporte/live"])
def test_a_folder_path_in_a_wrapped_label_breaks_at_the_folders(qapp, path):
    """Qt does not break inside a Windows path: unbroken it would make the panel scroll sideways."""
    plain, wrapped = dim_label(f"Ziel: {path}"), dim_label(f"Ziel: {breakable(path)}")
    assert wrapped.minimumSizeHint().width() < 150
    assert wrapped.text().replace("\u200b", "") == plain.text()  # only invisible break points are added
    if "\\" in path:
        assert plain.minimumSizeHint().width() > 2 * wrapped.minimumSizeHint().width()


def test_two_columns_on_a_wide_page_and_one_on_a_narrow_page(qapp):
    left, right, wide = QLabel("links"), QLabel("rechts"), QLabel("breit")
    grid = CardGrid([[wide], [left, right]], ratio=(3, 2))
    grid.resize(WIDE_PAGE + 100, 300)
    grid.show()
    QTest.qWait(20)
    assert grid.wide and left.y() == right.y() and left.x() < right.x()
    assert left.width() > right.width()  # 3 : 2
    grid.resize(600, 300)
    QTest.qWait(20)
    assert not grid.wide and left.x() == right.x() and left.y() < right.y()
    grid.close()


# ---------------------------------------------------------- the lifetime of the pages


def test_the_window_hands_in_the_real_pages(parts):
    kinds = {"changes": ChangesPage, "sets": SetsPage, "export": ExportPage}
    for key, kind in kinds.items():
        page = parts.open(key)
        assert isinstance(page, kind) and not page.isWindow(), key
    tabs = {"loop": LoopTab, "pad": PadTab, "record": RecordTab}
    for key, kind in tabs.items():
        page = parts.open_tab(key)
        assert isinstance(page, kind) and not page.isWindow() and parts.view.isAncestorOf(page), key


def test_the_panels_go_with_the_view_and_the_window_is_not_kept_alive(qapp, tmp_path, clock):
    """No reference cycle (the window's ``apply`` method, a connection) keeps a page or the window alive."""
    p = Parts(tmp_path, clock)
    pages = [weakref.ref(p.open(key)) for key in TOOLS]
    pages += [weakref.ref(p.open_tab(key)) for key in DETAIL_TABS]
    pages.append(weakref.ref(p.view.detail))
    panels = weakref.ref(panels_of(p))
    view = weakref.ref(p.view)
    p.window.leave_parent_mode()
    p.view = None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert view() is None and panels() is None and all(page() is None for page in pages)
    p.window.enter_parent_mode()
    p.view = p.window.parent_view
    for key in TOOLS:
        p.open(key)  # the window ends with every panel built
    for key in DETAIL_TABS:
        p.open_tab(key)
    window = weakref.ref(p.window)
    p.window.close()
    p.window.deleteLater()
    p.store.close()
    p.window = p.view = None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert window() is None


# --------------------------------------------- the keys belong to the pads unless a field is typed in


def press(window: MainWindow, key: Qt.Key) -> None:
    """A key as the keyboard sends it: to the widget with the focus (the window if none has it)."""
    from PySide6.QtWidgets import QApplication

    QTest.keyClick(QApplication.focusWidget() or window, key)


@pytest.fixture
def active(parts):
    parts.window.activateWindow()
    QTest.qWaitForWindowActive(parts.window)
    return parts


def test_a_tap_on_a_tile_gives_the_keys_back_to_the_pads(active):
    window, view, controller = active.window, active.view, active.controller
    active.open("system")
    edit = panels_of(active).editors["data_dir"]._edit
    before, file_before = edit.text(), active.config.read_text(encoding="utf-8")
    edit.setFocus()
    tile = view.tiles[3]
    QTest.mouseClick(tile, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     tile.body().center().toPoint())  # chooses pad 4 (not its start field)
    press(window, Qt.Key.Key_R)
    assert controller.recording_pad == 3  # R records, it is not typed into the field
    assert edit.text() == before and active.config.read_text(encoding="utf-8") == file_before


def test_the_keys_work_after_the_cross_and_after_another_tool(active):
    window, view = active.window, active.view
    active.open("system")
    panels_of(active).editors["data_dir"]._edit.setFocus()
    view.side_panel.close_button.click()
    press(window, Qt.Key.Key_Right)
    assert view.selected == 1
    active.open("devices")
    panels_of(active).tone_button.setFocus()
    active.open("export")  # another tool: the keys go back to the view
    press(window, Qt.Key.Key_Right)
    assert view.selected == 2 and view.panel_key == "export"


def test_a_number_waiting_for_its_pause_is_saved_when_the_parents_leave(active):
    active.open("system")
    spin = panels_of(active).editors["max_record_seconds"]._dspin
    spin.setValue(17)
    active.view.mode_switch.kids_button.click()  # within the pause, without leaving the field first
    assert load_settings(active.config).max_record_seconds == 17.0
    assert active.controller.settings.max_record_seconds == 17.0


def test_the_steppers_save_once_after_the_pause(active):
    active.open("system")
    editor = panels_of(active).editors["max_record_seconds"]
    plus = [b for b in editor.widget.findChildren(QAbstractButton) if b.text() == "+"][0]
    writes = []
    panels_of(active).said.connect(lambda text, _level: writes.append(text))
    for _ in range(3):
        plus.click()
    assert load_settings(active.config).max_record_seconds == 10.0  # still the old value
    QTest.qWait(settings_panels.NUMBER_PAUSE_MS + 200)
    assert load_settings(active.config).max_record_seconds == 13.0
    assert writes == ["Gespeichert: Längste Aufnahme"]


class Devices:
    """Stands in for the audio engine: no device groups, a reported latency."""

    def __init__(self, latency):
        self.latency = latency

    def device_groups(self, _kind):
        return []

    def reported_latency_ms(self):
        return self.latency


@pytest.mark.parametrize("reported", [42.4, None])
def test_by_hand_starts_from_the_reported_latency_and_never_saves_a_made_up_zero(qapp, tmp_path, reported):
    path = tmp_path / "settings.toml"
    panels = SettingsPanels(path, make_settings(tmp_path), lambda s: [], source=Devices(reported))
    panels.page("devices")
    editor = panels.editors["latency_ms"]
    editor._manual.setChecked(True)
    if reported is None:
        assert not path.exists()  # nothing to start from: nothing saved until a number is typed
        editor._dspin.setValue(55)
        editor._dspin.editingFinished.emit()
        assert load_settings(path).latency_ms == 55.0
    else:
        assert editor._dspin.value() == 42 and load_settings(path).latency_ms == 42.0


def test_a_file_broken_by_hand_is_named_as_the_reason(parts):
    parts.open("system")
    parts.config.write_text("rows = 99\n", encoding="utf-8")
    panels_of(parts).editors["fullscreen"]._box.setChecked(True)
    head = parts.view.side_panel.message()
    assert head.startswith("settings.toml enthält einen ungültigen Wert") and "„Zeilen“" in head
    assert parts.config.read_text(encoding="utf-8") == "rows = 99\n"


@pytest.mark.parametrize("size", [(1024, 640), (1280, 800)])
def test_the_key_help_fits_beside_an_open_panel(qapp, tmp_path, clock, size):
    p = Parts(tmp_path, clock, size)
    try:
        p.view.toolbar.keys_button.click()
        p.open("devices")
        detail = p.view.detail
        room = detail.width() * 0.5
        lines, font = detail.help_lines(room)
        metrics = QFontMetrics(font)
        assert all(metrics.horizontalAdvance(line) <= room for line in lines)
        shown = " ".join(lines)
        assert "…" not in shown and "Enter" in shown and "Esc" in shown and "F1" in shown
    finally:
        p.close()
