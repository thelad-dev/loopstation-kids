"""Parents' level section: ceiling, trim, switches, scale, loud recordings (offscreen, no hardware)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from loopstation.audio.dynamics import db_to_gain
from loopstation.clips import KEEP, ClipEvent, ClipLog
from loopstation.config import load_settings
from loopstation.controller import NEAR_CLIP_DB, Controller
from loopstation.gui import level_panel
from loopstation.gui.level_panel import PANEL_KEYS, describe_clip, format_db, format_when
from loopstation.gui.main_window import MainWindow
from loopstation.gui.peak_meter import peak_to_position
from loopstation.gui.settings_panels import NOTES, SettingsPanels
from loopstation.store import EventStore

SHIPPED = (Path(__file__).resolve().parent.parent / "settings.toml").read_text(encoding="utf-8")


@pytest.fixture
def parts(qapp, tmp_path, clock):
    settings = make_settings(tmp_path, volume=0.3, max_level_db=-6.0)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml",
                        settings_template=SHIPPED)
    window.resize(1280, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    yield window, controller, tmp_path / "settings.toml"
    window.timer.stop()
    window.close()
    store.close()


@pytest.fixture
def dialog(parts):
    """The side panel "Pegel" open in the parents' view of the real window; yields its ``SettingsPanels``."""
    window = parts[0]
    window.enter_parent_mode()
    window.open_tool("levels")
    yield window.settings_panels


def controller_event_time(parts) -> float:
    return parts[1].clip_events()[0].at


def record_take(parts, clock, pad=0, peak=0.5, clips=0, seconds=1.0):
    window, controller, _ = parts
    window.controller.set_mode(type(controller.mode).RECORD)
    controller.press(pad)
    controller.audio.input_peak, controller.audio.clips = peak, clips
    controller.tick()
    clock.advance(seconds)
    controller.tick()
    controller.press(pad)  # stop


# ----------------------------------------------------------- clip log


def test_clip_log_keeps_newest_first_and_survives_a_restart(tmp_path):
    path = tmp_path / "data" / "clips.jsonl"
    log = ClipLog(path)
    log.add(ClipEvent(100.0, 1, -1.0, False))
    log.add(ClipEvent(200.0, 5, 3.2, True))
    assert [e.pad for e in log.events()] == [5, 1]
    again = ClipLog(path)
    assert again.events() == [ClipEvent(200.0, 5, 3.2, True), ClipEvent(100.0, 1, -1.0, False)]


def test_clip_log_skips_broken_lines_and_keeps_only_the_newest(tmp_path):
    path = tmp_path / "clips.jsonl"
    lines = ['{"at": 1, "pad": 0, "peak_db": 0, "clipped": true}', "kaputt", '{"at": 2}', ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    assert len(ClipLog(path).events()) == 1
    log = ClipLog(path, keep=3)
    for i in range(5):
        log.add(ClipEvent(10.0 + i, i, 0.0, True))
    assert [e.pad for e in log.events()] == [4, 3, 2]
    assert [e.pad for e in ClipLog(path, keep=3).events()] == [4, 3, 2]
    assert KEEP >= 10


def test_clip_log_in_memory_writes_nothing(tmp_path):
    log = ClipLog()
    log.add(ClipEvent(1.0, 0, 0.0, True))
    assert len(log.events()) == 1 and list(tmp_path.iterdir()) == []


# ------------------------------------------------------- controller


def test_loud_recordings_are_noted_quiet_ones_are_not(parts, clock):
    controller = parts[1]
    record_take(parts, clock, pad=0, peak=0.3)  # about -10 dBFS
    assert controller.clip_events() == []
    record_take(parts, clock, pad=1, peak=db_to_gain(NEAR_CLIP_DB + 0.5))  # near full scale
    record_take(parts, clock, pad=5, peak=1.4, clips=2)  # clipped
    first, second = controller.clip_events()[::-1]
    assert (first.pad, first.clipped) == (1, False)
    assert first.peak_db == pytest.approx(NEAR_CLIP_DB + 0.5, abs=0.1)
    assert (second.pad, second.clipped) == (5, True) and second.peak_db > 0
    assert controller.clip_events()[0] is second  # newest first


def test_scale_follows_the_take_and_keeps_the_last_peak(parts, clock):
    window, controller, _ = parts
    window.controller.set_mode(type(controller.mode).RECORD)
    controller.press(0)
    controller.audio.input_peak = 0.4
    controller.tick()
    controller.audio.input_peak = 0.1
    controller.tick()
    assert controller.meter_levels() == (0.1, 0.4)  # now, and the highest so far
    clock.advance(1.0)
    controller.press(0)
    assert controller.meter_levels() == (0.4, 0.4)  # the microphone is closed: the last peak stays


# ------------------------------------------- the switch on the child page


def test_peak_meter_switch_hides_the_pad_bars_but_never_the_clip_sign(parts, clock):
    window, controller, _ = parts
    window.controller.set_mode(type(controller.mode).RECORD)
    pad = window.grid.pads[0]
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(pad.width() // 2, pad.height() // 2))
    controller.audio.input_peak, controller.audio.clips = 0.9, 1
    controller.tick()
    window.refresh()
    assert pad.level == 3 and pad.clip is True
    controller.set_peak_meter(False)
    window.refresh()
    assert pad.level == 0 and pad.clip is True  # the warning is protection, not a display option
    controller.set_peak_meter(True)
    window.refresh()
    assert pad.level == 3


def test_child_page_has_no_extra_level_widget(parts):
    window = parts[0]
    assert not hasattr(window, "peak_meter")


# ------------------------------------------------------ the page


def test_page_has_the_volume_slider_top_right_and_the_level_cards(parts, dialog):
    window = parts[0]
    slider = window.parent_view.volume_slider  # one volume: the slider of the header, beside the panel
    top_left = slider.mapTo(window, QPoint(0, 0))
    assert top_left.x() + slider.width() >= window.width() - 40 and top_left.y() < 40
    assert dialog.panel is not None and dialog.panel.isVisible()
    for key in PANEL_KEYS:
        assert key in dialog.editors and dialog.editors[key] is dialog.panel.editors[key]


def test_page_states_that_dbfs_is_not_db_spl(dialog):
    texts = " ".join(label.text() for label in dialog.page("levels").findChildren(QLabel))
    assert level_panel.HONESTY_TITLE in texts and "dBFS ist nicht dB am Ohr" in texts
    assert any("dB(FS)" in note and "dB(SPL)" in note for note in NOTES)


def test_one_volume_for_both_sliders(parts, dialog):
    window, controller, _ = parts
    slider = window.parent_view.volume_slider
    window.refresh()
    assert slider.volume == pytest.approx(controller.volume)
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(slider._x_of(0.5)), slider.height() // 2))
    assert controller.volume == pytest.approx(0.25, abs=0.01)
    assert controller.audio.volume == controller.volume
    window.refresh()
    assert window.volume_slider.volume == pytest.approx(controller.volume)  # the child's slider moved, too
    controller.set_volume(0.1)
    window.refresh()
    assert slider.volume == pytest.approx(0.1)


def test_lowering_the_ceiling_pulls_both_sliders_down(parts, dialog):
    window, controller, path = parts
    controller.set_volume(db_to_gain(-6.0))
    ceiling = dialog.panel.ceiling
    ceiling.set_value(-6)
    ceiling.valueChanged.emit(-20.0)  # dragging: live, nothing written yet
    assert controller.max_level_db == -20.0 and controller.audio.ceiling_db == -20.0
    assert controller.volume == pytest.approx(db_to_gain(-20.0))
    assert not path.exists()
    ceiling.released.emit(-20.0)
    assert load_settings(path).max_level_db == -20.0
    window.refresh()
    assert window.parent_view.volume_slider.volume == pytest.approx(db_to_gain(-20.0))
    assert window.volume_slider.volume == pytest.approx(db_to_gain(-20.0))
    assert window.volume_slider.limit == pytest.approx(db_to_gain(-20.0))


def test_ceiling_slider_by_mouse_and_keyboard(parts, dialog):
    _, controller, path = parts
    ceiling = dialog.panel.ceiling
    QTest.mouseClick(ceiling, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(ceiling._x_of(-12)), ceiling.height() // 2))
    assert controller.max_level_db == -12.0
    assert load_settings(path).max_level_db == -12.0
    QTest.keyClick(ceiling, Qt.Key.Key_Right)
    assert controller.max_level_db == -11.0 and load_settings(path).max_level_db == -11.0
    for _ in range(5):
        QTest.keyClick(ceiling, Qt.Key.Key_PageDown)  # five steps each
    assert controller.max_level_db == -30.0  # stops at the end of the range


def test_trim_and_switches_write_the_file_and_reach_the_engine(parts, dialog):
    _, controller, path = parts
    audio = controller.audio
    dialog.panel.trim.valueChanged.emit(-4.5)
    dialog.panel.trim.released.emit(-4.5)
    assert audio.input_gain_db == -4.5 and load_settings(path).input_gain_db == -4.5
    switches = dialog.panel.switches
    switches["auto_gain"].setChecked(True)
    assert audio.auto_gain is True and load_settings(path).auto_gain is True
    switches["peak_meter"].setChecked(False)
    assert controller.peak_meter is False and load_settings(path).peak_meter is False
    switches["soft_seam"].setChecked(False)
    assert controller.settings.soft_seam is False and load_settings(path).soft_seam is False
    # The beeps are on the panel "System" (mockup L2-05): they save and act the same way.
    dialog.page("system")
    beep = dialog.editors["sound_effects"]._box
    beep.setChecked(False)
    assert controller.settings.sound_effects is False and load_settings(path).sound_effects is False
    start_tone = dialog.editors["record_start_tone"]._box
    assert controller.settings.record_start_tone is True and start_tone.isChecked()
    start_tone.setChecked(False)
    assert controller.settings.record_start_tone is False and load_settings(path).record_start_tone is False
    # The values the child set meanwhile are kept in the file, too.
    assert load_settings(path).volume == pytest.approx(controller.volume)


def test_a_live_change_keeps_the_other_values_of_the_file(parts, dialog):
    _, controller, path = parts
    dialog.page("system")
    rows = dialog.editors["rows"]._spin
    rows.setValue(5)
    rows.editingFinished.emit()  # saved, acts after a restart
    dialog.panel.switches["auto_gain"].setChecked(True)
    stored = load_settings(path)
    assert stored.rows == 5 and stored.auto_gain is True
    assert controller.settings.rows == 3 and controller.settings.auto_gain is True


def test_latency_is_live_from_the_page(parts, dialog):
    _, controller, path = parts
    dialog.page("devices")
    editor = dialog.editors["latency_ms"]
    editor._manual.setChecked(True)
    editor._dspin.setValue(85.0)
    editor._dspin.editingFinished.emit()
    assert controller.settings.latency_ms == 85.0 and load_settings(path).latency_ms == 85.0
    editor._auto.setChecked(True)
    assert controller.settings.latency_ms is None and load_settings(path).latency_ms is None


def test_saving_keeps_the_childs_volume(parts, dialog):
    _, controller, path = parts
    controller.set_volume(0.2)  # the child moved the slider after the panel opened
    dialog.panel.switches["auto_gain"].setChecked(True)
    assert controller.volume == pytest.approx(0.2) and load_settings(path).volume == pytest.approx(0.2)


def test_loud_recordings_show_up_on_the_page(parts, dialog, clock):
    record_take(parts, clock, pad=5, peak=1.2, clips=1)
    dialog.refresh_levels()
    rows = dialog.panel.clip_list.rows
    assert len(rows) == 1
    texts = " ".join(label.text() for label in rows[0].findChildren(QLabel))
    when = format_when(controller_event_time(parts))
    assert "Pad 6" in texts and "übersteuert" in texts and when in texts
    record_take(parts, clock, pad=1, peak=db_to_gain(-1.0))
    dialog.refresh_levels()
    assert len(dialog.panel.clip_list.rows) == 2


def test_empty_list_says_so(dialog):
    texts = [label.text() for label in dialog.panel.clip_list.findChildren(QLabel)]
    assert texts == [level_panel.CLIP_EMPTY]


def test_scale_on_the_page_shows_the_last_take_and_dims_with_the_switch(parts, dialog, clock):
    controller = parts[1]
    record_take(parts, clock, peak=0.5)
    dialog.refresh_levels()
    meter = dialog.panel.meter
    assert meter.position == pytest.approx(peak_to_position(0.5), abs=0.01) and meter.hold == meter.position
    assert meter.isEnabled()
    controller.set_peak_meter(False)
    dialog.refresh_levels()
    assert not meter.isEnabled()


def test_page_without_a_controller_still_has_the_plain_rows(qapp, tmp_path):
    running = make_settings(tmp_path)
    plain = SettingsPanels(tmp_path / "s.toml", running, lambda new: [], SHIPPED)
    plain.page("levels")
    assert plain.panel is None
    assert {"volume", "max_level_db", "peak_meter"} <= set(plain.editors)
    plain.refresh_levels()  # nothing to do


# --------------------------------------------------------- helpers


def test_number_and_date_formats():
    assert format_db(-6, "dBFS") == "−6 dBFS" and format_db(0, "dB", signed=True) == "0 dB"
    assert format_db(-4.5, "dB") == "−4,5 dB" and format_db(3, "dB", signed=True) == "+3 dB"
    now = datetime(2026, 11, 20, 17, 0)
    today = datetime(2026, 11, 20, 16, 42).timestamp()
    assert format_when(today, now) == "Heute 16:42"
    assert format_when(datetime(2026, 11, 19, 18, 5).timestamp(), now) == "Gestern 18:05"
    assert format_when(datetime(2026, 11, 3, 7, 30).timestamp(), now) == "3.11. 07:30"
    assert describe_clip(ClipEvent(0, 5, 2.0, True)) == "Pad 6 · Spitze 0 dBFS · übersteuert"
    assert describe_clip(ClipEvent(0, 1, -1.2, False)) == "Pad 2 · Spitze −1 dBFS"


def test_a_damaged_file_is_not_overwritten_by_a_level_change(parts, dialog):
    _, controller, path = parts
    path.write_text("max_level_db = kaputt\n", encoding="utf-8")
    dialog.panel.switches["auto_gain"].setChecked(True)
    assert path.read_text(encoding="utf-8") == "max_level_db = kaputt\n"
    head = parts[0].parent_view.side_panel
    assert "ungültiges TOML" in dialog.message and head.message() == dialog.message  # said in the head
