"""The unfoldable detail panel of the chosen pad in the parents' view (mockups L2-03 and L2-04), offscreen.

Folding and unfolding (tap, button, Enter, double click, Esc), choosing versus starting a pad, the tabs
Loop (handles, markers, play head, one step back), Pad (free mode, takes, level, greyed fields) and
Aufnahme (the settings of the panel "System" with the same way of saving), the turn with the side
panels, the room at 1024 x 640 and the look against the two mockups.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import make_settings
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QPushButton, QScrollArea
from test_parent_mode import ShapedAudio, World, _difference, _part, calls, open_parents, tap

from loopstation.audio.base import PREVIEW_VOICE
from loopstation.config import load_settings
from loopstation.controller import Controller, Mode
from loopstation.gui.detail_panel import BADGE_END, INFO_LEAST
from loopstation.gui.parent_view import ParentView, WaveCache
from loopstation.store import EventStore

REPO = Path(__file__).resolve().parent.parent
MOCKUP_LOOP = REPO / "mockups" / "L2-03_eltern_detail_loop_kuerzen.png"
MOCKUP_PAD = REPO / "mockups" / "L2-04_eltern_detail_pad_takes_pegel.png"


@pytest.fixture
def world(qapp, tmp_path, clock):
    w = World(tmp_path, clock)
    yield w
    w.close()


def double_click(widget, point: QPoint) -> None:
    """What a double click delivers: press, release, double click, release."""
    none = Qt.KeyboardModifier.NoModifier
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, none, point)
    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, none, point)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, none, point)


def wait_for(condition, ms: int = 3000) -> bool:
    """Let the event loop run until ``condition()`` holds (at most ``ms``)."""
    for _ in range(ms // 20):
        if condition():
            return True
        QTest.qWait(20)
    return condition()


def tick(world: World) -> None:
    world.window._tick()
    QTest.qWait(10)


# ------------------------------------------------------------------ fold and unfold


def test_the_panel_unfolds_and_folds_by_tap_button_enter_double_click_and_esc(world):
    world.record(0, 2.0)
    window = world.window
    view = open_parents(window)
    detail = view.detail
    folded_tile = view.tiles[0].body().height()
    assert not detail.is_open and detail.height() == 64 and detail.stack.isHidden()
    tap(detail, QPoint(300, 30))  # a tap on the line
    assert detail.is_open and detail.tab == "loop" and detail.loop_tab.isVisible()
    assert detail.height() > 300 and view.tiles[0].body().height() < folded_tile  # flatter tiles
    detail.fold_button.click()
    assert not detail.is_open and detail.height() == 64
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert detail.is_open
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert not detail.is_open
    tile = view.tiles[3]
    double_click(tile, tile.body().center().toPoint())
    assert detail.is_open and view.selected == 3 and detail.pad == 3
    window.activateWindow()  # Esc is a shortcut of the active window
    QTest.qWaitForWindowActive(window)
    QTest.keyClick(window, Qt.Key.Key_Escape)  # Esc folds it, the parents' view stays
    assert not detail.is_open and window.parent_mode
    detail.tab_buttons["pad"].click()  # a tab of the folded line unfolds on that tab
    assert detail.is_open and detail.tab == "pad" and detail.pad_tab.isVisible()
    assert [k for k, b in detail.tab_buttons.items() if b.isChecked()] == ["pad"]


def test_a_double_click_on_the_start_field_is_two_taps_not_the_panel(world):
    world.record(2, 1.0)
    window = world.window
    view = open_parents(window)
    tile = view.tiles[2]
    before = len(world.audio.calls)
    double_click(tile, tile.start_field().center().toPoint())
    assert not view.detail.is_open
    # Two taps on the pad, as on the child page: the first plays it, the second stops it.
    assert world.audio.calls[before:] == [("play", 2, False), ("stop", 2, True)]


def test_choosing_a_pad_changes_the_panel_starting_one_does_not(world):
    world.record(0, 2.0)
    world.record(2, 4.0)
    window, audio = world.window, world.audio
    view = open_parents(window)
    view.detail.open_tab("loop")
    loop = view.detail.loop_tab
    assert loop.pad == 0 and loop.waveform.loop_frames == 16000
    tile = view.tiles[2]
    tap(tile, tile.start_field().center())  # starts pad 3
    assert calls(audio, "play")[-1] == ("play", 2, False)
    world.launchpad.events = [(2, True), (2, False)]  # and the Launchpad
    tick(world)
    assert view.selected == 0 and view.detail.pad == 0 and loop.pad == 0 and view.detail.title == "Pad 1"
    tap(tile, tile.body().center())  # choosing it
    tick(world)
    assert view.selected == 2 and loop.pad == 2 and loop.waveform.loop_frames == 32000
    assert view.detail.title == "Pad 3"


def test_a_side_panel_and_the_unfolded_panel_take_turns(world):
    window = world.window
    view = open_parents(window)
    view.open_detail()
    view.toolbar.buttons["levels"].click()
    assert view.panel_key == "levels" and not view.detail.is_open
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert view.detail.is_open and view.panel_key is None and view.toolbar.buttons["pads"].isChecked()


def test_the_panel_has_no_timer_of_its_own(world):
    world.record(0, 2.0)
    view = open_parents(world.window)
    for tab in ("loop", "pad", "record"):
        view.detail.open_tab(tab)
    assert view.detail.findChildren(QTimer) == []  # the main window's tick drives it


# ------------------------------------------------------------------ tab "Loop"


def test_a_marker_by_a_tap_on_the_wave_and_the_key_m(world):
    world.record(0, 2.0)
    window, controller = world.window, world.controller
    view = open_parents(window)
    QTest.keyClick(window, Qt.Key.Key_M)  # folded: M does nothing
    QTest.keyClick(window, Qt.Key.Key_Return)
    loop = view.detail.loop_tab
    wave = loop.waveform
    assert not loop.stretch_button.isEnabled() and "Marker" in loop.stretch_button.toolTip()
    x = round(wave._x_of(6000))
    QTest.mouseClick(wave, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, 100))
    frame = wave.cursor_frame
    assert frame is not None and controller.markers(0) == []
    QTest.keyClick(window, Qt.Key.Key_M)
    assert controller.markers(0) == [controller.snap_marker(0, frame)]
    assert wave.markers == controller.markers(0) and loop.stretch_button.isEnabled()


def test_apply_is_one_step_back_and_the_balance_is_the_controllers(world):
    world.record(0, 2.0)
    world.record(1, 4.0)  # two bars
    window, controller = world.window, world.controller
    view = open_parents(window)
    view.select(1)
    view.detail.open_tab("loop")
    loop = view.detail.loop_tab
    original = controller.pad(1).sample
    loop.trim.snap_switch.click()  # off: the dragged length
    loop.waveform.set_trim_range(0, 12000)
    check = controller.check_trim(1, 0, 12000, snap=False)
    assert f"neu {check.seconds:.2f}".replace(".", ",") in loop.trim.readout.text()
    loop.trim.apply_button.click()
    assert controller.pad(1).sample != original
    view.undo_button.click()  # "Zurück" in the header
    tick(world)
    assert controller.pad(1).sample == original and loop.waveform.loop_frames == 32000


def test_the_play_head_runs_while_the_loop_is_heard(world):
    world.record(0, 2.0)
    window, audio, clock = world.window, world.audio, world.clock
    view = open_parents(window)
    view.detail.open_tab("loop")
    loop = view.detail.loop_tab
    assert loop.waveform.play_frame is None
    loop.listen_button.click()
    assert calls(audio, "play")[-1] == ("play", PREVIEW_VOICE, False)
    assert loop.waveform.play_frame == 0 and loop.listen_button.text() == "Stopp"
    clock.advance(0.5)
    tick(world)
    assert loop.waveform.play_frame == 4000  # half a second at 8000 Hz
    clock.advance(2.0)
    tick(world)
    assert loop.waveform.play_frame is None and loop.listen_button.text() == "Anhören"
    loop.listen_button.click()
    loop.listen_button.click()  # a second tap stops it
    assert ("stop", PREVIEW_VOICE) in [c[:2] for c in audio.calls] and loop.waveform.play_frame is None


# ------------------------------------------------------------------ tab "Pad"


def test_free_mode_is_a_step_back_and_takes_are_heard_and_brought_back(world):
    world.record(0, 2.0)
    first = world.controller.pad(0).sample
    world.clock.advance(60)
    world.controller.set_mode(Mode.RECORD)
    world.record(0, 2.0)  # a second take on the same pad
    world.controller.set_mode(Mode.PLAY)
    window, controller, audio = world.window, world.controller, world.audio
    newest = controller.pad(0).sample
    view = open_parents(window)
    view.detail.open_tab("pad")
    pad = view.detail.pad_tab
    pad.free_switch.click()
    assert controller.is_free(0)
    view.undo_button.click()
    tick(world)
    assert not controller.is_free(0) and not pad.free_switch.isChecked()
    assert [row.label for row in pad.take_rows.values()] == ["Jetzt", "Vorher"]
    assert pad.take_rows[newest].restore_button is None  # the take on the pad cannot be brought back
    row = pad.take_rows[first]
    row.listen_button.click()
    assert calls(audio, "play")[-1] == ("play", PREVIEW_VOICE, False)
    assert len(audio.voices[PREVIEW_VOICE][0]) == len(controller.sample_audio(first))
    row.restore_button.click()
    assert controller.pad(0).sample == first
    assert [row.label for row in pad.take_rows.values()] == ["Jetzt", "Vorher"]
    view.undo_button.click()  # bringing it back is one step on the Zurück stack
    tick(world)
    assert controller.pad(0).sample == newest


def test_a_take_that_was_too_loud_says_so(world):
    window, controller, clock = world.window, world.controller, world.clock
    world.record(0, 2.0)
    view = open_parents(window)
    view.detail.open_tab("pad")
    pad = view.detail.pad_tab
    assert "zu laut" not in pad.verdict.text() and pad.loud_box.isHidden()
    controller.set_mode(Mode.RECORD)
    controller.press(0)
    controller.audio.input_peak, controller.audio.clips = 1.4, 2  # the microphone clipped
    controller.tick()
    clock.advance(2.0)
    controller.tick()
    controller.press(0)
    controller.set_mode(Mode.PLAY)
    tick(world)
    assert "zu laut" in pad.verdict.text()
    assert not pad.loud_box.isHidden() and pad.loud_title.text() == "Zu laut gewesen: einmal"
    assert pad.loud_line.text().startswith("Take „Jetzt“") and "übersteuert" in pad.loud_line.text()
    view.select(1)  # another pad has no loud take
    assert pad.loud_box.isHidden()


def test_the_verdict_of_the_take_level_goes_with_the_number_shown(world):
    world.record(0, 2.0)  # the test take peaks at 0.25: -12.04 dBFS, shown as -12, the low end of the target
    view = open_parents(world.window)
    tick(world)
    assert view.detail.info.endswith("Spitze \u221212 dBFS")  # the folded line writes it the same way
    view.detail.open_tab("pad")
    tick(world)
    assert view.detail.pad_tab.verdict.text() == "Spitze \u221212 dBFS · im Ziel"


def test_greyed_fields_cannot_be_used(world):
    world.record(0, 2.0)
    view = open_parents(world.window)
    detail = view.detail
    detail.open_tab("pad")
    pad = detail.pad_tab
    QTest.keyClicks(pad.name_edit, "Trommel")
    assert pad.name_edit.text() == "" and not pad.name_edit.isEnabled()
    assert "neuen Kern" in pad.name_edit.toolTip()
    value = pad.volume_slider.value()
    QTest.mouseClick(pad.volume_slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(5, pad.volume_slider.height() // 2))
    assert pad.volume_slider.value() == value and not pad.volume_slider.isEnabled()
    effects = detail.tab_buttons["effects"]
    QTest.mouseClick(effects, Qt.MouseButton.LeftButton)
    assert detail.tab == "pad" and not effects.isEnabled() and "neuen Kern" in effects.toolTip()


def test_start_on_the_bar_is_the_setting_of_the_panel_takt(world):
    world.record(0, 2.0)
    window, controller = world.window, world.controller
    view = open_parents(window)
    view.detail.open_tab("pad")
    pad = view.detail.pad_tab
    switch = pad.on_grid_switch
    before = controller.settings.free_pad_on_grid
    assert not switch.isEnabled() and "nur bei einem freien Pad" in pad.on_grid_hint.text()
    pad.free_switch.click()
    assert switch.isEnabled() and "alle freien Pads" in pad.on_grid_hint.text()
    switch.click()
    assert controller.settings.free_pad_on_grid is not before
    assert load_settings(world.config).free_pad_on_grid is not before  # saved at once
    view.bar_chip.click()  # the panel "Takt" shows the same value ...
    editor = window.settings_panels.editors["free_pad_on_grid"]._box
    assert editor.isChecked() is not before
    editor.click()  # ... and the detail panel follows a change made there
    assert switch.isChecked() is before and controller.settings.free_pad_on_grid is before


# ------------------------------------------------------------------ tab "Aufnahme"


def test_the_record_tab_saves_the_way_the_system_panel_does(world):
    window, controller = world.window, world.controller
    view = open_parents(window)
    view.detail.open_tab("record")
    record = view.detail.record_tab
    before = controller.settings.max_record_seconds
    more = next(b for b in record.longest.findChildren(QPushButton) if b.accessibleName() == "Mehr")
    more.click()
    assert controller.settings.max_record_seconds == before  # a number waits for its pause ...
    assert wait_for(lambda: controller.settings.max_record_seconds == before + 1)  # ... and is then saved
    assert load_settings(world.config).max_record_seconds == before + 1
    tone = controller.settings.record_start_tone
    record.tone_switch.click()
    assert controller.settings.record_start_tone is not tone
    assert load_settings(world.config).record_start_tone is not tone
    panels = window.settings_panels
    panels.page("system")
    assert panels.editors["max_record_seconds"].value() == before + 1
    assert panels.editors["record_start_tone"].value() is not tone


def test_a_refused_value_of_a_tab_says_why_in_the_panel(world):
    window, controller = world.window, world.controller
    view = open_parents(window)
    view.detail.open_tab("record")
    record = view.detail.record_tab
    world.config.write_text("rows = 99\n", encoding="utf-8")  # broken by hand: nothing may be saved
    record.tone_switch.click()
    assert "Zeilen" in view.detail.message.text() and not view.detail.message.isHidden()
    assert world.config.read_text(encoding="utf-8") == "rows = 99\n"
    world.config.write_text("", encoding="utf-8")
    record.tone_switch.click()  # saved again: the message goes
    assert view.detail.message.isHidden() or "Gespeichert" in view.detail.message.text()
    assert controller.settings.record_start_tone == load_settings(world.config).record_start_tone


def test_the_keys_stay_with_the_pads_after_a_field_or_an_empty_spot(world):
    world.record(0, 2.0)
    window = world.window
    view = open_parents(window)
    view.toolbar.buttons["system"].click()
    field = window.settings_panels.editors["max_record_seconds"]._dspin
    field.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Return)  # Enter in the field stays there ...
    view.detail.tab_buttons["record"].click()  # ... a tab unfolds the panel, the side panel closes
    assert view.detail.is_open and view.panel_key is None
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert view.selected == 1  # the arrow reached the pads, not the hidden field
    view.detail.open_tab("pad")
    column = view.detail.pad_tab.findChildren(QScrollArea)[0]
    QTest.mouseClick(column.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(10, column.viewport().height() - 5))  # an empty spot of the tab
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert view.selected == 0


def test_choosing_another_pad_stops_the_loop_being_heard(world):
    world.record(0, 2.0)
    world.record(1, 2.0)
    view = open_parents(world.window)
    view.detail.open_tab("loop")
    loop = view.detail.loop_tab
    loop.listen_button.click()
    assert loop.waveform.play_frame == 0
    view.select(1)
    assert world.audio.calls[-1][:2] == ("stop", PREVIEW_VOICE) and loop.waveform.play_frame is None
    loop.listen_button.click()
    view.detail.open_tab("pad")  # an unseen play head does not run on
    assert loop.waveform.play_frame is None


def test_the_microphone_level_is_live_while_recording(world):
    window, controller = world.window, world.controller
    view = open_parents(window)
    view.detail.open_tab("record")
    meter = view.detail.record_tab.meter
    assert meter.position == 0.0
    controller.press(0)
    controller.audio.input_peak = 0.5
    tick(world)
    assert meter.position > 0.8  # -6 dBFS on a scale from -48 to 0


# ------------------------------------------------------------------ room


def test_at_1024_x_640_the_tiles_stay_playable_and_the_row_fits(qapp, tmp_path, clock):
    w = World(tmp_path, clock, size=(1024, 640))
    try:
        w.like_the_mockup()
        view = open_parents(w.window)
        view.select(4)
        root = w.window.view_host
        for tab in ("loop", "pad", "record"):
            view.detail.open_tab(tab)
            tick(w)
            detail_box = view.detail.geometry().translated(view.mapTo(root, QPoint(0, 0)))
            assert root.rect().contains(detail_box)
            for tile in view.tiles:
                body = tile.body().translated(tile.mapTo(root, QPoint(0, 0)).toPointF())
                assert body.height() >= 70 and not body.intersects(detail_box.toRectF()), (tab, tile.index)
            page = view.detail.pages[tab]
            for button in page.findChildren(QAbstractButton):
                if button.isVisible():
                    assert button.width() >= button.sizeHint().width() - 1, (tab, button.text())
                    if tab == "loop":  # the action row is never cut (the other tabs scroll)
                        offset = button.parentWidget().mapTo(view.detail, QPoint(0, 0))
                        box = button.geometry().translated(offset)
                        assert view.detail.rect().contains(box), (tab, button.text())
        tile = view.tiles[3]
        tap(tile, tile.start_field().center())  # a pad under the open panel still records
        assert w.controller.recording_pad == 3
    finally:
        w.close()


@pytest.mark.parametrize("rows,size", [(4, (1024, 640)), (6, (1280, 800))])
def test_many_rows_in_a_low_window_keep_64_px_tiles_and_the_panel_scrolls(qapp, tmp_path, clock, rows, size):
    settings = make_settings(tmp_path / "live", rows=rows, cols=4)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, ShapedAudio(clock), settings, clock=clock)
    controller.press(0)
    clock.advance(2.0)
    controller.press(0)
    view = ParentView(controller, WaveCache(), False)
    try:
        view.resize(*size)
        view.show()
        QTest.qWaitForWindowExposed(view)
        detail = view.detail
        for tab in ("loop", "pad", "record"):
            detail.open_tab(tab)
            view.refresh({}, (0.0,) * 4)
            QTest.qWait(20)
            assert min(t.body().height() for t in view.tiles) >= 64, tab
            assert detail.geometry().bottom() < view.height() and detail.y() > view.grid.geometry().top()
        detail.open_tab("loop")
        QTest.qWait(20)
        loop, holder = detail.loop_tab, detail.holder("loop")
        assert isinstance(holder, QScrollArea)
        assert holder.viewport().height() < loop.minimumSizeHint().height()
        assert loop.height() >= loop.minimumSizeHint().height()  # not squeezed: the panel scrolls instead
        assert holder.verticalScrollBar().maximum() > 0
        assert loop.width() <= holder.viewport().width()  # never sideways
        bar = holder.verticalScrollBar()
        bar.setValue(bar.maximum())  # scrolled down, the whole action row is in sight
        QTest.qWait(20)
        apply = loop.trim.apply_button
        box = apply.rect().translated(apply.mapTo(holder.viewport(), QPoint(0, 0)))
        assert holder.viewport().rect().contains(box)
    finally:
        view.close()
        store.close()


@pytest.mark.parametrize("size", [(1024, 640), (1280, 800)])
def test_beside_a_side_panel_the_folded_line_keeps_its_facts_readable(qapp, tmp_path, clock, size):
    w = World(tmp_path, clock, size=size)
    try:
        w.like_the_mockup()
        view = open_parents(w.window)
        view.select(4)
        tick(w)
        detail = view.detail
        assert all(button.isVisible() for button in detail.tab_buttons.values())  # the full width: tabs
        for button in detail.tab_buttons.values():
            assert button.x() - 16 - BADGE_END >= INFO_LEAST
        view.toolbar.buttons["changes"].click()
        tick(w)
        assert view.panel_key == "changes" and not detail.is_open
        # Tabs that would cover "Pad 5" and its facts give way; a tap on the line still unfolds it.
        assert not any(button.isVisible() for button in detail.tab_buttons.values())
        assert detail._tabs_left - 16 - BADGE_END >= INFO_LEAST
        tap(detail, QPoint(BADGE_END + 20, 30))
        assert detail.is_open and view.panel_key is None
        assert all(button.isVisible() for button in detail.tab_buttons.values())
    finally:
        w.close()


# ------------------------------------------------------------------ the look


def _part_difference(shot: QImage, mockup: QImage, box, size) -> float:
    return float(np.mean(np.abs(_part(shot, box, *size) - _part(mockup, box, *size))))


def mockup_state(world: World):
    """The state of the mockups: pad 5 chosen, two markers on its loop."""
    world.like_the_mockup()
    view = open_parents(world.window)
    view.select(4)
    controller = world.controller
    frames = len(controller.loop_audio(controller.pad(4).sample, 4))
    controller.add_marker(4, frames // 4)
    controller.add_marker(4, frames // 2)
    return view, frames


# Mockup L2-03 at 1280 x 800, compared as in test_parent_mode (64 x 40, and parts). Measured with the
# test font: the whole window 13.6, the head of the panel 7.9, the wave as a vertical profile 16.1, the
# action row 22.2. What is left on purpose: the pad names, the start handle drawn on the edge, the
# "Anfang"/"Ende" words inside the wave and the marker flags above it. Counter-checks: the folded
# panel about 69 (head 121, wave 157, row 79), the tab "Pad" in its place (wave 22.8, row 35.0).
LOOP_THRESHOLD = 15.0
LOOP_PARTS = {
    "head": ((108, 427, 1148, 64), (143, 8), 10.0),
    "wave": ((124, 490, 1116, 160), (1, 20), 19.5),
    "actions": ((124, 686, 1116, 52), (140, 6), 28.0),
}


def test_the_loop_tab_looks_like_the_mockup(world):
    view, frames = mockup_state(world)
    loop = view.detail.loop_tab
    view.detail.open_tab("loop")
    loop.trim.snap_switch.click()
    loop.waveform.set_trim_range(0, frames * 7 // 8)
    loop.waveform.set_play_frame(frames * 3 // 8)
    tick(world)
    mockup = QImage(str(MOCKUP_LOOP)).copy(0, 0, 1280, 800)
    shot = world.window.grab().toImage()
    assert _difference(shot, mockup) < LOOP_THRESHOLD, _difference(shot, mockup)
    for name, (box, size, threshold) in LOOP_PARTS.items():
        difference = _part_difference(shot, mockup, box, size)
        assert difference < threshold, (name, difference)
    # Counter-checks.
    view.detail.open_tab("pad")
    tick(world)
    other = world.window.grab().toImage()
    for name in ("wave", "actions"):
        box, size, threshold = LOOP_PARTS[name]
        assert _part_difference(other, mockup, box, size) >= threshold, name
    view.detail.set_open(False)
    tick(world)
    folded = world.window.grab().toImage()
    assert _difference(folded, mockup) > 3 * LOOP_THRESHOLD
    for name, (box, size, threshold) in LOOP_PARTS.items():
        assert _part_difference(folded, mockup, box, size) >= threshold, name
    dark = QImage(1280, 800, QImage.Format.Format_RGB32)
    dark.fill(QColor("#0E0E10"))
    assert _difference(dark, mockup) > 3 * LOOP_THRESHOLD


# Mockup L2-04: whole 12.1, head 7.7, the left column 26.8 (the mockup shows a name and an active pad
# volume, here greyed out until the new core), takes 18.6, level 13.9. Counter-checks: the tab "Loop"
# in its place (whole 17.4, left 43, takes 38, level 31), the folded panel (about 69, parts over 120).
PAD_THRESHOLD = 14.5
PAD_PARTS = {
    "head": ((108, 427, 1148, 64), (143, 8), 10.0),
    "left": ((124, 495, 310, 270), (39, 34), 33.0),
    "takes": ((470, 495, 370, 220), (46, 27), 27.0),
    "level": ((870, 495, 370, 270), (46, 34), 21.0),
}


def test_the_pad_tab_looks_like_the_mockup(world):
    view, _frames = mockup_state(world)
    view.detail.open_tab("pad")
    tick(world)
    mockup = QImage(str(MOCKUP_PAD)).copy(0, 0, 1280, 800)
    shot = world.window.grab().toImage()
    assert _difference(shot, mockup) < PAD_THRESHOLD, _difference(shot, mockup)
    for name, (box, size, threshold) in PAD_PARTS.items():
        difference = _part_difference(shot, mockup, box, size)
        assert difference < threshold, (name, difference)
    view.detail.open_tab("loop")
    tick(world)
    other = world.window.grab().toImage()
    assert _difference(other, mockup) >= PAD_THRESHOLD
    for name in ("left", "takes", "level"):
        box, size, threshold = PAD_PARTS[name]
        assert _part_difference(other, mockup, box, size) >= threshold, name
    view.detail.set_open(False)
    tick(world)
    folded = world.window.grab().toImage()
    assert _difference(folded, mockup) > 3 * PAD_THRESHOLD
    for name, (box, size, threshold) in PAD_PARTS.items():
        assert _part_difference(folded, mockup, box, size) >= threshold, name
