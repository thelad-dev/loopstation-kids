"""GUI smoke test (offscreen): the window builds and is wired to the controller."""

from __future__ import annotations

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from loopstation.controller import Controller, Mode
from loopstation.store import EventStore


@pytest.fixture
def window(qapp, tmp_path, clock):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    win = MainWindow(controller, None, ["Kein Mikrofon gefunden"])
    win.resize(1280, 800)
    win.show()
    QTest.qWaitForWindowExposed(win)
    yield win
    win.timer.stop()
    win.close()
    store.close()


def click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(widget.width() // 2, widget.height() // 2))


def test_window_has_twelve_large_pads(window):
    pads = window.grid.pads
    assert len(pads) == 12
    assert all(pad.width() >= 120 and pad.width() == pad.height() for pad in pads)
    assert all(pad.color == "white" for pad in pads)
    assert window.status_label.text() == "Kein Mikrofon gefunden"
    assert [b.text() for b in window.mode_buttons.values()] == [
        "Spielen", "Aufnehmen", "Loop", "Löschen", "Verlauf"]
    assert all(b.height() >= 64 for b in window.mode_buttons.values())


def test_click_on_pad_calls_controller(window, clock):
    pad = window.grid.pads[0]
    click(pad)
    assert window.controller.recording_pad == 0
    assert pad.color == "red"
    clock.advance(1)
    click(pad)
    assert pad.color == "yellow"


def test_mode_buttons_toggle(window):
    click(window.mode_buttons[Mode.DELETE])
    assert window.controller.mode == Mode.DELETE
    assert window.mode_buttons[Mode.DELETE].isChecked()
    assert window.frame.accent is not None
    click(window.mode_buttons[Mode.DELETE])
    assert window.controller.mode == Mode.PLAY
    assert window.mode_buttons[Mode.PLAY].isChecked()


def test_shortcuts_are_wired(window, clock):
    controller = window.controller
    click(window.grid.pads[2])
    clock.advance(1)
    click(window.grid.pads[2])
    assert controller.pad(2).sample is not None
    assert window.undo_shortcut.key().matches(Qt.Modifier.CTRL | Qt.Key.Key_Z)
    window.undo_shortcut.activated.emit()
    assert controller.pad(2).sample is None

    controller.set_mode(Mode.LOOP)
    window.escape_shortcut.activated.emit()
    assert controller.mode == Mode.PLAY


def test_keyboard_shortcuts_reach_the_window(window, clock):
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.controller.set_mode(Mode.RECORD)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert window.controller.mode == Mode.PLAY

    click(window.grid.pads[3])
    clock.advance(1)
    click(window.grid.pads[3])
    assert window.controller.pad(3).sample is not None
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.controller.pad(3).sample is None


def test_history_dialog_restores_a_version(window, clock, qapp):
    from loopstation.gui.history_dialog import HistoryDialog

    controller = window.controller
    controller.set_mode(Mode.RECORD)
    for _ in range(2):
        controller.press(1)
        clock.advance(1)
        controller.press(1)
    first, second = controller.pad(1).history
    assert controller.pad(1).sample == second
    dialog = HistoryDialog(controller, 1, window)
    assert dialog.take_buttons[second].isHidden()  # current version: "jetzt" mark instead
    click(dialog.listen_buttons[first])
    assert ("play", -1, False) in controller.audio.calls
    click(dialog.take_buttons[first])
    assert controller.pad(1).sample == first


def test_waiting_pad_pulses_without_text(window, clock):
    controller = window.controller
    click(window.grid.pads[0])
    clock.advance(1)
    click(window.grid.pads[0])  # sets the loop length
    audio = controller.audio
    audio.wait = 0.4
    audio.boundary_in = 0.25
    click(window.grid.pads[1])  # waits for the next loop start
    window.refresh()
    pad = window.grid.pads[1]
    assert pad.color == "red" and pad.waiting == 0.75
    assert pad.remaining is None and pad.overlay is None  # no countdown number yet
    assert window.grid.pads[0].waiting is None
    pad.grab()  # paints without errors

    audio.wait = 0.0  # loop start reached: now it really records
    window.refresh()
    assert pad.waiting is None and pad.remaining is not None


def test_new_session_runs_a_wave_across_the_pads(window, clock):
    controller = window.controller
    click(window.grid.pads[0])
    clock.advance(1)
    click(window.grid.pads[0])
    controller.delete_all()
    window.refresh()
    assert window.grid.pads[0].sparkle == 0.5  # 0 s after the start, top left
    clock.advance(0.15)
    window.refresh()
    assert window.grid.pads[0].sparkle == 1.0 and window.grid.pads[11].sparkle == 0.0
    window.grid.pads[0].grab()
    clock.advance(0.75)
    window.refresh()
    assert window.grid.pads[11].sparkle == 1.0  # bottom right, last
    clock.advance(1)
    controller.tick()
    window.refresh()
    assert all(p.sparkle == 0.0 for p in window.grid.pads)


def record_pad(window, clock, index):
    click(window.grid.pads[index])
    clock.advance(1)
    click(window.grid.pads[index])


def test_redo_button_is_active_only_when_possible(window, clock):
    assert not window.redo_button.isEnabled() and not window.undo_button.isEnabled()
    record_pad(window, clock, 0)
    assert window.undo_button.isEnabled() and not window.redo_button.isEnabled()
    click(window.undo_button)
    assert window.controller.pad(0).sample is None
    assert window.redo_button.isEnabled()
    click(window.redo_button)
    assert window.controller.pad(0).sample is not None
    assert not window.redo_button.isEnabled()
    window.controller.undo()
    click(window.grid.pads[1])  # a recording running: nothing to redo meanwhile
    assert window.controller.recording_pad == 1 and not window.redo_button.isEnabled()
    assert window.redo_button.text() == "Wiederholen" and window.undo_button.text() == "Zurück"


def test_redo_shortcuts_are_wired(window, clock):
    keys = {s.key().toString() for s in window.redo_shortcuts}
    assert keys == {"Ctrl+Y", "Ctrl+Shift+Z"}
    for shortcut in window.redo_shortcuts:
        record_pad(window, clock, 2)
        window.undo_shortcut.activated.emit()
        assert window.controller.pad(2).sample is None
        shortcut.activated.emit()
        assert window.controller.pad(2).sample is not None
        window.undo_shortcut.activated.emit()  # empty again for the next round
        assert window.controller.pad(2).sample is None


def test_keyboard_redo_reaches_the_window(window, clock):
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    record_pad(window, clock, 3)
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.controller.pad(3).sample is None
    QTest.keyClick(window, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert window.controller.pad(3).sample is not None
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window, Qt.Key.Key_Z,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window.controller.pad(3).sample is not None


def click_at(widget, point):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def test_the_latest_change_shows_a_back_badge_on_its_pad_only(window, clock):
    pads = window.grid.pads
    assert not any(p.badge for p in pads)
    record_pad(window, clock, 0)
    record_pad(window, clock, 1)
    assert [p.index for p in pads if p.badge] == [1]
    assert [p.index for p in pads if p.badge_button is not None and p.badge_button.isVisible()] == [1]
    pads[1].grab()  # paints without errors

    click(pads[1].badge_button)  # the badge takes back pad 1 only
    controller = window.controller
    assert controller.pad(1).sample is None and controller.pad(0).sample is not None
    assert [p.index for p in pads if p.badge] == [0]
    assert window.redo_button.isEnabled()
    assert controller.recording_pad is None  # the badge did not press the pad

    record_pad(window, clock, 3)
    controller.delete_all()  # a change of many pads (pads 0 and 3) has no single pad
    assert not any(p.badge for p in pads)


def test_pad_press_outside_the_badge_still_presses_the_pad(window, clock):
    pad = window.grid.pads[2]
    record_pad(window, clock, 2)
    assert pad.badge
    click_at(pad, QPoint(pad.width() // 2, pad.height() // 2))
    assert window.controller.pad(2).sample is not None  # plays, does not undo
    assert ("play", 2, False) in window.controller.audio.calls


def test_badge_is_hidden_while_recording(window, clock):
    record_pad(window, clock, 0)
    assert window.grid.pads[0].badge
    click(window.grid.pads[5])  # recording on another pad
    window.refresh()
    assert not any(p.badge for p in window.grid.pads)


def test_the_whole_window_fits_a_1024_px_wide_screen(window):
    assert window.minimumSizeHint().width() <= 1024


def test_the_action_row_fits_a_1024_px_wide_window(window):
    """Zurück, Wiederholen and Alles still stay inside 1024 px (margins 2 x 24, gaps 14)."""
    buttons = [window.undo_button, window.redo_button, window.stop_button]
    needed = sum(b.minimumSizeHint().width() for b in buttons) + 14 * len(buttons) + 48
    assert needed <= 1024
    window.resize(1280, 800)
    QTest.qWait(10)
    assert all(b.width() >= b.minimumSizeHint().width() for b in buttons)
