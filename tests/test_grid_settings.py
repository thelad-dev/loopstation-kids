"""Settings and parents' view of the onset grid: auto grid, time signature, tempo window, tiles."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtTest import QTest

from loopstation.config import SIGNATURES, ConfigError, Settings, parse_settings, render_settings_text
from loopstation.controller import Controller
from loopstation.gui import grid_panel
from loopstation.gui.main_window import MainWindow
from loopstation.gui.settings_panels import FIELDS
from loopstation.store import EventStore

SHIPPED = (Path(__file__).resolve().parent.parent / "settings.toml").read_text(encoding="utf-8")


# --- settings.toml ---------------------------------------------------------------------------------


def test_defaults_keep_todays_behaviour():
    settings = Settings()
    assert settings.auto_grid is False and settings.time_signature == "4/4"
    assert (settings.grid_bpm_min, settings.grid_bpm_max) == (40.0, 200.0)
    assert settings.beats_per_bar == 4


@pytest.mark.parametrize(("signature", "beats"), [("2/4", 2), ("3/4", 3), ("4/4", 4), ("6/8", 2)])
def test_time_signatures_give_the_beats_of_a_bar(signature, beats):
    assert parse_settings({"time_signature": signature}).beats_per_bar == beats
    assert SIGNATURES[signature] == beats


@pytest.mark.parametrize("raw", [{"auto_grid": "ja"}, {"time_signature": "5/4"}, {"time_signature": 4},
                                 {"grid_bpm_min": 10}, {"grid_bpm_max": 400}, {"grid_bpm_min": True}])
def test_invalid_grid_values_name_the_key(raw):
    with pytest.raises(ConfigError, match=next(iter(raw))):
        parse_settings(raw, "settings.toml")


def test_the_tempo_window_must_not_be_reversed():
    with pytest.raises(ConfigError, match="grid_bpm_min"):
        parse_settings({"grid_bpm_min": 150, "grid_bpm_max": 100}, "settings.toml")
    assert parse_settings({"grid_bpm_min": 60, "grid_bpm_max": 120}).grid_bpm_max == 120.0


def test_the_shipped_file_documents_the_grid_keys():
    for key in ("auto_grid = false", 'time_signature = "4/4"', "grid_bpm_min = 40", "grid_bpm_max = 200"):
        assert key in SHIPPED


def test_a_file_without_the_keys_gets_them_with_comments_when_written():
    text = render_settings_text("rows = 3\n", Settings(auto_grid=True, time_signature="3/4"))
    assert "auto_grid = true" in text and 'time_signature = "3/4"' in text
    assert "# true = die erste Aufnahme beginnt beim ersten Schlag" in text


# --- tiles -------------------------------------------------------------------------------------------


def test_tiles_of_a_measured_grid_as_in_the_mockup():
    from loopstation.controller import GridInfo

    info = GridInfo(bpm=96.0, signature="4/4", beats=4, seconds=2.5, source="onset", pad=0)
    assert grid_panel.tiles(info) == [
        ("Tempo", "96 BPM", "gemessen"),
        ("Taktart", "4/4", "Standard"),
        ("Takt-Länge", "2,50 s", "1 Takt = 4 Schläge"),
        ("Quelle", "Klatschen", "Pad 1"),
    ]


def test_tiles_name_a_length_grid_and_a_session_without_grid():
    from loopstation.controller import GridInfo

    info = GridInfo(bpm=72.0, signature="3/4", beats=3, seconds=2.5, source="duration", pad=None)
    tiles = grid_panel.tiles(info)
    assert tiles[0] == ("Tempo", "72 BPM", "aus der Aufnahmelänge")
    assert tiles[1][2] == "gewählt" and tiles[3] == ("Quelle", "Aufnahmelänge", "für alle Pads")
    assert not any("duration" in text for tile in tiles for text in tile)  # no internal key on the tile
    free = grid_panel.tiles(None, "onsets_without_beat_and_length_implausible")
    assert free[3] == ("Quelle", "Kein Takt", "Schläge unklar, Aufnahme zu lang")
    assert grid_panel.tiles(None)[0] == ("Tempo", "–", "kein Takt")


# --- the page ----------------------------------------------------------------------------------------


@pytest.fixture
def parts(qapp, tmp_path, clock):
    settings = make_settings(tmp_path, auto_grid=True)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    controller = Controller(store, audio, settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml",
                        settings_template=SHIPPED)
    window.resize(1280, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    yield window, controller, audio, tmp_path / "settings.toml"
    window.timer.stop()
    window.close()
    store.close()


@pytest.fixture
def dialog(parts):
    """The side panel "Takt" open in the parents' view of the real window; yields its ``SettingsPanels``."""
    window = parts[0]
    window.enter_parent_mode()
    window.parent_view.bar_chip.click()
    yield window.settings_panels
    window.leave_parent_mode()


def test_the_page_has_the_switch_the_signature_and_the_tempo_window(dialog):
    keys = [f.key for f in FIELDS]
    for key in ("auto_grid", "time_signature", "grid_bpm_min", "grid_bpm_max"):
        assert key in keys and key in dialog.editors
    assert dialog.editors["auto_grid"].value() is True
    assert dialog.editors["time_signature"].value() == "4/4"
    assert [f for f in FIELDS if f.key == "auto_grid"][0].label == "Takt aus Klatschen erkennen"


def test_a_change_on_the_panel_writes_and_applies_the_grid_settings(parts, dialog):
    _, controller, _, path = parts
    dialog.editors["auto_grid"]._box.setChecked(False)
    assert "auto_grid = false" in path.read_text(encoding="utf-8")  # at once, no "Speichern"
    dialog.editors["time_signature"]._combo.setCurrentText("3/4")
    text = path.read_text(encoding="utf-8")
    assert "auto_grid = false" in text and 'time_signature = "3/4"' in text
    assert controller.settings.auto_grid is False and controller.settings.time_signature == "3/4"


def test_the_card_shows_no_grid_before_a_recording_and_the_source_after(parts, dialog, clock):
    _, controller, audio, _ = parts
    panel = dialog.grid_panel
    assert panel is not None and panel.texts()[0] == ("Tempo", "–", "kein Takt")
    assert not panel.note.isHidden()
    audio.clap_times = [0.5, 1.0]
    controller.press(0)
    clock.advance(3.0)
    controller.press(0)
    dialog.refresh_levels()
    assert panel.texts() == [
        ("Tempo", "120 BPM", "gemessen"),
        ("Taktart", "4/4", "Standard"),
        ("Takt-Länge", "2,00 s", "1 Takt = 4 Schläge"),
        ("Quelle", "Klatschen", "Pad 1"),
    ]
    assert panel.note.isHidden()  # the 'nothing is guessed' note is only for a session without grid
