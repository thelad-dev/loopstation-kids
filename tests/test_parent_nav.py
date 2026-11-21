"""The parents' area as one window: left navigation with seven areas, one page each (mockups 09-16)."""

from __future__ import annotations

import gc
import sys
from dataclasses import fields

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from loopstation.config import RESTART_KEYS, Settings
from loopstation.controller import Controller
from loopstation.gui import settings_page
from loopstation.gui.advanced_page import AdvancedPage
from loopstation.gui.changes_page import ChangesPage
from loopstation.gui.export_dialog import ExportPage
from loopstation.gui.main_window import MainWindow
from loopstation.gui.parent_nav import WIDE_PAGE, CardGrid
from loopstation.gui.sets_page import SetsPage
from loopstation.gui.settings_page import FIELDS, SettingsDialog
from loopstation.gui.tempo_card import TempoCard
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS
from loopstation.session import SetSession
from loopstation.store import EventStore

AREAS = [
    "Lautstärke & Pegel", "Geräte & Audio", "Takt & Loop", "Verlauf & Undo", "Erweitert", "Sets", "Export",
]


@pytest.fixture
def parts(qapp, tmp_path, clock):
    settings = make_settings(tmp_path / "live", auto_grid=True)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    config = tmp_path / "settings.toml"
    config.write_text("# test\nvolume = 0.5\n", encoding="utf-8")
    session = SetSession(controller, config, clock=clock, sets_folder=tmp_path / "sets")
    window = MainWindow(controller, None, [], config_path=config, set_session=session)
    dialog = SettingsDialog(config, controller.settings, window.apply_settings, None, window,
                            window.parent_pages())
    yield dialog, window, controller, audio
    dialog.close()
    window.timer.stop()
    window.close()
    store.close()


def show(dialog: SettingsDialog, width: int = 1280, height: int = 800) -> None:
    dialog.resize(width, height)
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    QTest.qWait(30)


# ------------------------------------------------------------- the navigation


def test_the_navigation_has_the_seven_areas_in_the_order_of_the_mockups(parts):
    dialog, *_ = parts
    assert [button.text() for button in dialog.nav.buttons.values()] == AREAS
    assert dialog.page_keys == ["levels", "devices", "tempo", "changes", "advanced", "sets", "export"]
    assert dialog.current_key() == "levels" and dialog.nav.buttons["levels"].isChecked()


def test_every_area_is_one_page_and_the_chosen_button_is_the_only_marked_one(parts):
    dialog, *_ = parts
    show(dialog)
    seen = []
    for key in dialog.page_keys:
        dialog.nav.buttons[key].click()
        assert dialog.current_key() == key
        assert [k for k, b in dialog.nav.buttons.items() if b.isChecked()] == [key]
        page = dialog.page(key)
        assert page.isVisible()
        assert not any(dialog.page(other).isVisible() for other in dialog.page_keys if other != key)
        seen.append(type(page).__name__)
    assert seen[3:] == ["ChangesPage", "AdvancedPage", "SetsPage", "ExportPage"]


def test_the_areas_behind_the_settings_pages_are_built_on_the_first_visit(parts):
    dialog, *_ = parts
    assert set(dialog._widgets) == {"levels", "devices", "tempo"}
    dialog.nav.buttons["export"].click()
    assert isinstance(dialog.page("export"), ExportPage) and "export" in dialog._widgets
    assert "advanced" not in dialog._widgets
    assert dialog.current_key() == "export"
    dialog.page("advanced")  # built, but not shown
    assert dialog.current_key() == "export"


def test_the_window_hands_in_the_real_pages_and_the_history_page_is_the_changes_page(parts):
    dialog, window, controller, _ = parts
    built = {page.key: page.build() for page in window.parent_pages()}
    try:
        assert isinstance(built["changes"], ChangesPage)
        assert isinstance(built["advanced"], AdvancedPage)
        assert isinstance(built["sets"], SetsPage)
        assert isinstance(built["export"], ExportPage)
    finally:
        for widget in built.values():
            widget.deleteLater()


def test_the_sets_area_is_left_out_without_a_set_session(qapp, tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")
    try:
        assert [page.label for page in window.parent_pages()] == ["Verlauf & Undo", "Erweitert", "Export"]
    finally:
        window.timer.stop()
        window.close()
        store.close()


def test_the_way_out_is_top_left_and_ends_the_parents_area(parts):
    dialog, *_ = parts
    assert dialog.close_button.text() == "Zur Kinderseite"
    assert dialog.close_button.toolTip() == "Eltern-Modus beenden"
    dialog.show()
    dialog.close_button.click()
    assert dialog.result() == dialog.DialogCode.Rejected and not dialog.isVisible()


def test_the_footer_in_the_navigation_names_the_restart_keys(parts):
    dialog, *_ = parts
    text = dialog.nav.footer.text()
    assert "Lokal · ohne Konto · ohne Internet" in text
    assert all(key in text for key in RESTART_KEYS)
    assert dialog.nav.footer.parentWidget() is dialog.nav
    # The file is saved from the navigation column, below the areas.
    assert dialog.save_button.parentWidget() is dialog.nav


def test_the_volume_slider_is_top_right_on_every_area(parts):
    dialog, *_ = parts
    show(dialog)
    assert dialog.volume_slider is not None
    for key in dialog.page_keys:
        dialog.show_page(key)
        corner = dialog.volume_slider.mapTo(dialog, dialog.volume_slider.rect().topRight())
        assert corner.x() > dialog.width() - 60 and corner.y() < 130


# ----------------------------------------------------------------- the settings


def test_every_field_has_an_editor_that_sits_on_a_page(parts):
    dialog, *_ = parts
    keys = {f.key for f in FIELDS} | set(settings_page.DEVICE_KEYS)
    assert keys <= set(dialog.editors)
    assert set(dialog.editors) == {f.name for f in fields(Settings)}
    for key in keys:
        widget = dialog.editors[key].widget
        assert dialog.isAncestorOf(widget), key


def test_the_loop_switches_are_on_the_tempo_area_and_the_level_switches_on_the_level_area(parts):
    dialog, *_ = parts
    tempo, levels = dialog.page("tempo"), dialog.page("levels")
    for key in ("auto_grid", "loop_sync", "stretch_to_grid", "free_pad_on_grid", "metronome_tone"):
        assert tempo.isAncestorOf(dialog.editors[key].widget), key
    for key in ("auto_gain", "soft_seam", "sound_effects", "peak_meter"):
        assert levels.isAncestorOf(dialog.editors[key].widget), key
    for key in ("rows", "cols", "sample_rate", "data_dir", "launchpad", "fullscreen"):
        assert dialog.page("devices").isAncestorOf(dialog.editors[key].widget), key


def test_the_tempo_correction_is_the_one_card_of_the_tempo_area(parts):
    dialog, *_ = parts
    cards = dialog.page("tempo").findChildren(TempoCard)
    assert cards == [dialog.tempo_card]
    assert not dialog.page("advanced").findChildren(TempoCard)  # not doubled on the Erweitert area


def test_the_level_area_keeps_the_must_say_text_about_dbfs_and_who(parts):
    dialog, *_ = parts
    texts = " ".join(label.text() for label in dialog.page("levels").findChildren(QLabel))
    assert "dBFS ist nicht dB am Ohr" in texts and "WHO: 75 dBA" in texts
    assert "Maximale Lautstärke" in texts and "Aufnahmepegel" in texts and "Automatik" in texts
    assert "Zu laut gewesen" in texts


def test_the_device_area_has_the_cards_of_mockup_10(parts):
    dialog, *_ = parts
    texts = " | ".join(label.text() for label in dialog.page("devices").findChildren(QLabel))
    for title in ("Mikrofon (Eingang)", "Lautsprecher / Kopfhörer (Ausgang)", "Audio-System",
                  "Verzögerung (Latenz)", "Für gutes Looping", "Allgemein"):
        assert title in texts, title
    editor = dialog.editors["latency_ms"]
    assert editor._auto.text() == "Automatisch" and editor._manual.text() == "Von Hand"


def test_the_test_tone_plays_through_the_effects_path(parts):
    dialog, _window, controller, audio = parts
    assert dialog.tone_button is not None
    dialog.tone_button.click()
    assert len(audio.effects) == 1
    tone = audio.effects[0]
    assert len(tone) > 0 and abs(tone).max() <= 0.2  # quiet


def test_without_a_controller_the_areas_are_there_but_the_live_cards_are_not(qapp, tmp_path):
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
    try:
        assert dialog.panel is None and dialog.volume_slider is None and dialog.tone_button is None
        assert [button.text() for button in dialog.nav.buttons.values()] == AREAS[:3]
        assert dialog.isAncestorOf(dialog.editors["volume"].widget)  # the plain rows are still there
    finally:
        dialog.close()


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
        dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
        dialog.show()
        rows[platform] = not dialog._asio_row.isHidden()
        assert "asio" in dialog.editors  # the setting itself is there on every system
        dialog.close()
    assert rows == {"linux": False, "win32": True}


# ------------------------------------------------------------------- 1024 px


@pytest.mark.parametrize("width", [1024, 1280])
def test_every_area_fits_the_window_width_without_a_sideways_scroll_bar(parts, width):
    dialog, *_ = parts
    assert dialog.minimumSizeHint().width() <= 1024
    show(dialog, width, 768)
    assert dialog.width() == width
    for key in dialog.page_keys:
        dialog.show_page(key)
        if key == "sets":
            dialog.page("sets").show_tab("open")
        QTest.qWait(30)
        for area in dialog.page(key).findChildren(QScrollArea):
            assert area.horizontalScrollBar().maximum() == 0, f"{key}: sideways scroll bar"
        assert dialog.minimumSizeHint().width() <= 1024, key
        if key == "sets":
            dialog.page("sets").show_tab("save")


def test_the_navigation_gets_narrower_in_a_narrow_window(parts):
    dialog, *_ = parts
    show(dialog, 1280)
    wide = dialog.nav.width()
    dialog.resize(1024, 768)
    QTest.qWait(30)
    assert dialog.nav.width() < wide


def test_the_scroll_bars_of_the_areas_are_the_dark_ones(parts):
    dialog, *_ = parts
    assert DARK_SCROLLBAR_QSS in dialog.styleSheet()  # the settings pages and the areas inside the dialog
    for key in ("advanced", "sets", "export"):  # the areas also bring the style when they stand alone
        assert DARK_SCROLLBAR_QSS in dialog.page(key).styleSheet(), key
    areas = [a for key in dialog.page_keys for a in dialog.page(key).findChildren(QScrollArea)]
    assert len(areas) >= 4  # the export preview grows with its rows and has no scroll area of its own


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


def test_the_parents_area_is_freed_when_the_last_reference_goes(qapp, tmp_path, clock):
    """No reference cycle (the window's ``apply`` method, a connection) keeps the page tree until a GC run."""
    settings = make_settings(tmp_path / "live")
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    config = tmp_path / "settings.toml"
    session = SetSession(controller, config, clock=clock, sets_folder=tmp_path / "sets")
    window = MainWindow(controller, None, [], config_path=config, set_session=session)
    gone: list[str] = []
    dialog = SettingsDialog(config, controller.settings, window.apply_settings, None, window,
                            window.parent_pages())
    for key in dialog.page_keys:
        dialog.show_page(key)
    dialog.destroyed.connect(lambda *_: gone.append("dialog"))
    dialog.setParent(None)  # a top level window here; the app gives it to the window instead
    # Every page of it goes with it.
    pages = [dialog.page(key) for key in dialog.page_keys]
    for page in pages:
        page.destroyed.connect(lambda *_: gone.append("page"))
    del pages
    del dialog
    gc.collect()
    qapp.processEvents()
    assert gone.count("dialog") == 1 and gone.count("page") == 7
    window.timer.stop()
    window.close()
    store.close()


def test_the_window_is_not_kept_alive_by_the_parents_area(qapp, tmp_path, clock):
    settings = make_settings(tmp_path / "live")
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")
    gone: list[str] = []
    window.destroyed.connect(lambda *_: gone.append("window"))
    dialog = SettingsDialog(tmp_path / "settings.toml", controller.settings, window.apply_settings, None,
                            window, window.parent_pages())
    window.timer.stop()
    window.close()
    del window, dialog
    gc.collect()
    qapp.processEvents()
    assert gone, "the main window is still alive: the parents' area holds a reference to it"
    store.close()


def test_the_pages_are_plain_widgets_and_not_windows(parts):
    dialog, *_ = parts
    for key in dialog.page_keys:
        page = dialog.page(key)
        assert isinstance(page, QWidget) and not page.isWindow(), key


# ------------------------------------------------------------- no cut-off texts


@pytest.mark.parametrize("width", [1024, 1280])
def test_no_single_line_label_is_cut_off_on_any_area(parts, width):
    """A label that may not wrap must show its whole text (a cut word like "(Ausgan" is a bug)."""
    dialog, *_ = parts
    show(dialog, width, 800)
    cut = []
    for key in dialog.page_keys:
        dialog.show_page(key)
        if key == "sets":
            dialog.page("sets").show_tab("save")
        QTest.qWait(40)
        dialog.layout().activate()
        pages = [dialog.page(key)]
        if key == "sets":
            dialog.page("sets").show_tab("open")
            QTest.qWait(40)
        for label in pages[0].findChildren(QLabel):
            text = label.text()
            rich = label.textFormat() == Qt.TextFormat.RichText
            if not label.isVisible() or not text or label.wordWrap() or rich:
                continue
            if label.fontMetrics().horizontalAdvance(text) > label.contentsRect().width():
                cut.append((width, key, text))
        if key == "sets":
            dialog.page("sets").show_tab("save")
    assert not cut, cut
