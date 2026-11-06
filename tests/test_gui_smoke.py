"""GUI smoke test (offscreen): the window builds and is wired to the controller."""

from __future__ import annotations

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

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


def test_delete_all_asks_first(window, clock):
    controller = window.controller
    click(window.grid.pads[0])
    clock.advance(1)
    click(window.grid.pads[0])

    class Answer(QDialog):
        result_code = QDialog.DialogCode.Rejected

        def exec(self):
            return self.result_code

    window.confirm_factory = lambda parent: Answer(parent)
    click(window.delete_all_button)
    assert controller.pad(0).sample is not None
    Answer.result_code = QDialog.DialogCode.Accepted
    click(window.delete_all_button)
    assert controller.pad(0).sample is None


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
