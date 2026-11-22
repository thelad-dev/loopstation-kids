"""The parents' view as a state of the main window (Loopstation 2, variant A), offscreen, no hardware.

The lock and the sum as a layer over the window, the parents' view with its tiles, keys and tools,
the lock time and the idle return, the Launchpad in the parents' view, and the look against the mockup.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QWidget

from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import FREE_HOLD_SECONDS, Controller, Mode
from loopstation.gui.main_window import MainWindow
from loopstation.gui.parent_gate import GateOverlay
from loopstation.gui.parent_view import ParentView, bar_lines
from loopstation.session import SetSession
from loopstation.store import EventStore

REPO = Path(__file__).resolve().parent.parent
MOCKUP = REPO / "mockups" / "L2-02_eltern_pad_ansicht_A.png"


class ShapedAudio(FakeAudio):
    """A recording with a rising and falling loudness, so the mini waves have a shape (as in the mockup)."""

    def stop_recording(self):
        data = super().stop_recording()
        if data is None:
            return None
        t = np.arange(len(data)) / self.sample_rate
        return (data * (0.3 + 0.7 * np.sin(2 * np.pi * 1.6 * t) ** 8)).astype(np.float32)


class FakePad:
    """Stands in for the Launchpad: the test queues key events, the window polls them."""

    status_text = ""
    connected = True

    def __init__(self):
        self.events: list[tuple[int, bool]] = []
        self.colors: dict[int, str] = {}

    def poll_events(self):
        events, self.events = self.events, []
        return events

    def set_colors(self, colors):
        self.colors = dict(colors)

    def close(self):
        pass


class World:
    def __init__(self, tmp_path, clock, size=(1280, 800), **overrides):
        self.clock = clock
        self.settings = make_settings(tmp_path / "live", **overrides)
        self.audio = ShapedAudio(clock)
        self.store = EventStore(self.settings.log_dir, self.settings.pad_count, clock=clock)
        self.controller = Controller(self.store, self.audio, self.settings, clock=clock)
        self.config = tmp_path / "settings.toml"
        self.session = SetSession(self.controller, self.config, clock=clock, sets_folder=tmp_path / "sets")
        self.launchpad = FakePad()
        self.window = MainWindow(self.controller, self.launchpad, [], config_path=self.config,
                                 set_session=self.session)
        self.window.timer.stop()  # the test ticks itself
        self.window.clock = clock  # lock and idle time on the test clock
        self.window.resize(*size)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)

    def record(self, pad: int, seconds: float) -> None:
        self.controller.press(pad)
        self.clock.advance(seconds)
        self.controller.press(pad)

    def like_the_mockup(self) -> None:
        """Five pads with a sound, two of them loop; one free pad (round)."""
        self.record(0, 2.5)  # the first take sets the bar: 2.5 s, 96 BPM in 4/4
        self.record(1, 5.0)
        self.record(4, 5.0)
        self.record(6, 2.5)
        self.controller.set_free(5, True)
        self.record(5, 3.1)
        self.controller.set_mode(Mode.LOOP)
        self.controller.press(0)
        self.controller.press(4)
        self.controller.set_mode(Mode.PLAY)
        self.controller.set_max_level_db(-5.0)  # the ceiling and the volume of the mockup
        self.controller.set_volume(0.3)

    def close(self) -> None:
        self.window.timer.stop()
        self.window.close()
        self.store.close()


@pytest.fixture
def world(qapp, tmp_path, clock):
    w = World(tmp_path, clock)
    yield w
    w.close()


@pytest.fixture
def lock_world(qapp, tmp_path, clock):
    w = World(tmp_path, clock, parent_unlock_minutes=5)
    yield w
    w.close()


def hold_the_lock(window: MainWindow) -> None:
    entry = window.parent_entry
    QTest.mousePress(entry, Qt.MouseButton.LeftButton)
    entry._timer.timeout.emit()  # two seconds have passed
    QTest.mouseRelease(entry, Qt.MouseButton.LeftButton)


def type_answer(window: MainWindow, right: bool) -> None:
    overlay = window.gate_overlay
    answer = overlay.card.question.answer + (0 if right else 1)
    QTest.keyClicks(overlay.card.answer_edit, str(answer))
    QTest.keyClick(overlay.card.answer_edit, Qt.Key.Key_Return)


def open_parents(window: MainWindow) -> ParentView:
    hold_the_lock(window)
    if window.gate_overlay is not None:
        type_answer(window, right=True)
    assert window.parent_view is not None
    return window.parent_view


def tap(widget: QWidget, point: QPointF | QPoint) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     point.toPoint() if isinstance(point, QPointF) else point)


def calls(audio: FakeAudio, name: str) -> list[tuple]:
    return [c for c in audio.calls if c[0] == name]


# ------------------------------------------------------------------ the way in


def test_holding_the_lock_lays_the_sum_over_the_window(lock_world):
    window = lock_world.window
    hold_the_lock(window)
    overlay = window.gate_overlay
    assert overlay is not None and overlay.isVisible()
    assert overlay.geometry() == window.view_host.rect()  # it covers the whole window
    assert window.findChildren(QDialog) == []  # no modal dialog
    assert overlay.keep_open.isVisible() and overlay.keep_open.text() == "Sperre 5 Minuten offen lassen"
    assert not overlay.keep_open.isChecked()  # off unless the parents turn it on


def test_a_wrong_answer_goes_back_to_the_child_page(world):
    window = world.window
    hold_the_lock(window)
    type_answer(window, right=False)
    assert window.gate_overlay is None and not window.parent_mode
    assert window.view_stack.currentWidget() is window.frame


def test_the_right_answer_shows_the_parents_view_in_the_same_window(world):
    window = world.window
    hold_the_lock(window)
    type_answer(window, right=True)
    assert window.parent_mode and window.gate_overlay is None
    assert window.view_stack.currentWidget() is window.parent_view
    assert window.parent_view.isVisible() and not window.frame.isVisible()
    assert window.parent_view.mode_switch.parents_button.isChecked()


def test_cancel_and_escape_close_the_sum(world):
    window = world.window
    hold_the_lock(window)
    window.gate_overlay.card.cancel_button.click()
    assert window.gate_overlay is None and not window.parent_mode
    hold_the_lock(window)
    QTest.keyClick(window.gate_overlay.card.answer_edit, Qt.Key.Key_Escape)
    assert window.gate_overlay is None and not window.parent_mode


def test_the_music_goes_on_under_the_sum_and_nothing_reaches_the_pads(world):
    window, audio, controller = world.window, world.audio, world.controller
    world.record(0, 2.0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.set_mode(Mode.PLAY)
    assert 0 in audio.voices
    before = list(audio.calls)
    hold_the_lock(window)
    overlay = window.gate_overlay
    window._tick()
    assert 0 in audio.voices  # the loop plays on
    # A click where pad 3 is lands on the layer, not on the pad.
    pad = window.grid.pads[3]
    point = pad.mapTo(window.view_host, pad.rect().center())
    hit = window.view_host.childAt(point)
    assert hit is overlay or overlay.isAncestorOf(hit)
    tap(hit, hit.mapFrom(window.view_host, point))
    # Keys go to the answer, never to a pad (digits, the letters of the parents' view, the space bar).
    for key in (Qt.Key.Key_R, Qt.Key.Key_L, Qt.Key.Key_Space, Qt.Key.Key_Delete):
        QTest.keyClick(overlay.card.answer_edit, key)
        QTest.keyClick(window, key)
    QTest.keyClick(overlay.card.answer_edit, Qt.Key.Key_3)
    assert overlay.card.answer_edit.text() == "3"
    assert controller.recording_pad is None and audio.calls == before
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)  # no undo under the sum
    assert audio.calls == before and controller.pad(0).sample is not None


def test_after_the_sum_the_keyboard_works_again(world):
    window, controller = world.window, world.controller
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    world.record(3, 1.0)
    hold_the_lock(window)
    assert QApplication.focusWidget() is window.gate_overlay.card.answer_edit
    type_answer(window, right=False)
    assert QApplication.focusWidget() is not None
    assert not isinstance(QApplication.focusWidget().parentWidget(), GateOverlay)
    target = QApplication.focusWidget() or window
    QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert controller.pad(3).sample is None  # Strg+Z took the recording back
    controller.set_mode(Mode.DELETE)
    QTest.keyClick(QApplication.focusWidget() or window, Qt.Key.Key_Escape)
    assert controller.mode == Mode.PLAY  # Esc leaves the mode again


# ------------------------------------------------------------- the parents' view


def test_a_tap_on_the_symbol_plays_a_tap_on_the_tile_only_chooses(world):
    window, audio, controller = world.window, world.audio, world.controller
    world.record(2, 1.0)
    view = open_parents(window)
    tile = view.tiles[2]
    before = list(audio.calls)
    tap(tile, tile.body().center())  # the middle of the tile: only chosen
    assert view.selected == 2 and audio.calls == before
    tap(tile, tile.start_field().center())  # the symbol: plays like a tap on the child page
    assert calls(audio, "play")[-1] == ("play", 2, False)
    empty = view.tiles[7]
    tap(empty, empty.start_field().center())  # an empty pad records
    assert controller.recording_pad == 7
    world.clock.advance(1.0)
    tap(empty, empty.start_field().center())
    assert controller.recording_pad is None and controller.pad(7).sample is not None


def test_a_new_take_of_the_same_length_and_its_undo_update_the_tile(world):
    """Same colour, same length, a new sample: the tile must follow (and the window keep ticking)."""
    window, controller, clock = world.window, world.controller, world.clock
    world.record(0, 2.5)
    world.record(1, 2.5)
    view = open_parents(window)
    window._tick()
    first = view.tiles[1].look.wave
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_R)  # a new take on pad 2, as long as the old one
    clock.advance(2.5)
    QTest.keyClick(window, Qt.Key.Key_R)
    window._tick()
    assert controller.mode == Mode.PLAY and controller.recording_pad is None
    second = view.tiles[1].look.wave
    assert second is not None and second is not first
    view.undo_button.click()  # back to the first take
    window._tick()
    assert view.tiles[1].look.wave is first
    view.redo_button.click()
    window._tick()
    assert view.tiles[1].look.wave is second
    assert world.launchpad.colors[1] == "yellow"


def test_the_view_and_the_window_are_freed(qapp, tmp_path, clock):
    import gc
    import weakref

    from PySide6.QtCore import QCoreApplication, QEvent

    w = World(tmp_path, clock)
    w.record(0, 1.0)
    view = weakref.ref(open_parents(w.window))
    w.window.leave_parent_mode()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert view() is None
    open_parents(w.window)  # the window ends in the parents' view
    window = weakref.ref(w.window)
    w.window.timer.stop()
    w.window.close()
    w.window.deleteLater()
    w.store.close()
    w.window = None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert window() is None


def test_closing_the_window_in_the_parents_view_leaves_it_and_takes_the_input_watch_off(world):
    """Left on, the watch outlived a window closed in the parents' view (a fixture closing it after a
    failed test, too): under PySide6 6.11 every widget built later ran into it ("'MainWindow' object has
    no attribute 'parent_view'"), and one failing GUI test made dozens of later ones fail."""
    window, clock = world.window, world.clock
    view = open_parents(window)
    view.toolbar.buttons["system"].click()
    panels = window.settings_panels
    spin = panels.editors["parent_idle_minutes"]._spin
    spin.setValue(9)  # waits for its pause
    window.close()
    assert window.parent_view is None  # left as with the switch: the number in its pause is saved
    assert "parent_idle_minutes = 9" in world.config.read_text(encoding="utf-8")
    # Input elsewhere no longer reaches the closed window.
    stamp = window._last_input
    clock.advance(30)
    other = QWidget()
    other.show()
    QTest.keyClick(other, Qt.Key.Key_A)
    QTest.mouseClick(other, Qt.MouseButton.LeftButton)
    assert window._last_input == stamp
    other.close()


CLOSE_IN_THE_PARENTS_VIEW = """
import sys, tempfile
from pathlib import Path
import loopstation.audio as audio_pkg
from loopstation import app as app_module
from loopstation.audio.null_backend import NullAudio
from loopstation.config import Settings
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

audio_pkg.create_audio = lambda settings: (NullAudio(), None)
tmp = Path(tempfile.mkdtemp())
settings = Settings(data_dir=tmp, sample_rate=8000, launchpad=False)
app = QApplication([])

def poke():
    from loopstation.gui.main_window import MainWindow
    window = [w for w in app.topLevelWidgets() if isinstance(w, MainWindow)][0]
    window.enter_parent_mode()  # the sum was answered
    window.open_tool("system")
    window.settings_panels.editors["parent_idle_minutes"]._spin.setValue(7)  # waits for its pause
    window.close()  # the cross of the window, in the parents' view: the app ends

QTimer.singleShot(300, poke)
code = app_module.run(settings, tmp / "settings.toml")
saved = (tmp / "settings.toml").read_text(encoding="utf-8").count("parent_idle_minutes = 7")
print("run returned", code, saved, flush=True)
"""


def test_the_app_ends_cleanly_when_the_window_closes_in_the_parents_view(tmp_path):
    import os
    import subprocess
    import sys

    script = tmp_path / "close_in_parents_view.py"
    script.write_text(CLOSE_IN_THE_PARENTS_VIEW, encoding="utf-8")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(REPO)}
    done = subprocess.run([sys.executable, str(script)], cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-2000:])
    assert "run returned 0 1" in done.stdout, done.stdout  # the waiting number was saved on the way out
    for sign in ("Traceback", "Error calling Python override", "RuntimeError", "AttributeError"):
        assert sign not in done.stderr, done.stderr[-2000:]


def test_entering_sets_the_children_mode_to_play(world):
    world.controller.set_mode(Mode.DELETE)
    open_parents(world.window)
    assert world.controller.mode == Mode.PLAY


def test_tiles_take_their_colours_from_the_controller(world):
    world.like_the_mockup()
    view = open_parents(world.window)
    colors = world.controller.pad_colors()
    assert [t.look.color for t in view.tiles] == [colors[i] for i in range(12)]
    looks = {t.index: t.look for t in view.tiles}
    assert looks[0].looping and looks[0].length == "1 Takt" and looks[0].wave is not None
    assert looks[1].length == "2 Takte" and not looks[1].looping
    assert looks[5].free and looks[5].length == "frei 3,1 s"
    assert not looks[3].filled and looks[3].wave is None
    assert [t.symbol() for t in view.tiles[:4]] == ["loop", "play", "record", "record"]
    assert bar_lines(world.controller.grid_info()) == ("96 BPM · 4/4", "aus Aufnahmelänge · 2,50 s")


def test_the_launchpad_plays_in_the_parents_view(world):
    window, audio = world.window, world.audio
    world.record(4, 1.0)
    open_parents(window)
    world.launchpad.events = [(4, True), (4, False)]
    window._tick()
    assert calls(audio, "play")[-1] == ("play", 4, False)
    assert world.launchpad.colors[4] == "green"


def test_f1_and_the_switch_lead_back_to_the_children(world):
    window = world.window
    view = open_parents(window)
    view.mode_switch.kids_button.click()
    assert not window.parent_mode and window.view_stack.currentWidget() is window.frame
    open_parents(window)
    QTest.keyClick(window, Qt.Key.Key_F1)
    assert not window.parent_mode
    QTest.keyClick(window, Qt.Key.Key_F1)  # F1 never leads the other way
    assert not window.parent_mode and window.gate_overlay is None


def test_the_child_page_is_as_before_after_a_visit(world):
    window = world.window
    before = sorted(b.text() for b in window.findChildren(QAbstractButton) if b.text())
    open_parents(window)
    window.leave_parent_mode()
    QApplication.sendPostedEvents(None, 0)
    QTest.qWait(10)
    assert window.findChildren(ParentView) == [] and window.findChildren(GateOverlay) == []
    after = sorted(b.text() for b in window.findChildren(QAbstractButton) if b.text())
    assert after == before


# -------------------------------------------------------------------- lock time


def test_the_default_asks_the_sum_again_after_leaving(world):
    window = world.window
    assert world.settings.parent_unlock_minutes == 0
    open_parents(window)
    window.leave_parent_mode()
    hold_the_lock(window)
    assert window.gate_overlay is not None and not window.parent_mode
    assert not window.gate_overlay.keep_open.isVisible()


def test_without_the_switch_the_sum_comes_back_even_with_minutes(lock_world):
    window = lock_world.window
    hold_the_lock(window)
    type_answer(window, right=True)  # the switch stays off
    assert window.parent_mode
    window.leave_parent_mode()
    hold_the_lock(window)
    assert window.gate_overlay is not None and not window.parent_mode


def test_the_lock_stays_open_for_the_set_minutes(lock_world):
    window, clock = lock_world.window, lock_world.clock
    hold_the_lock(window)
    window.gate_overlay.keep_open.click()  # the parents turn it on
    type_answer(window, right=True)
    assert window.parent_mode
    window.leave_parent_mode()
    clock.advance(4 * 60)
    hold_the_lock(window)
    assert window.parent_mode and window.gate_overlay is None  # no sum within five minutes
    window.leave_parent_mode()
    clock.advance(61)
    hold_the_lock(window)
    assert window.gate_overlay is not None and not window.parent_mode  # asked again


def test_the_lock_can_be_closed_at_once(lock_world):
    window = lock_world.window
    hold_the_lock(window)
    window.gate_overlay.keep_open.click()  # "Sperre 5 Minuten offen lassen" on
    window.gate_overlay.keep_open.click()  # and off again
    type_answer(window, right=True)
    window.leave_parent_mode()
    hold_the_lock(window)
    assert window.gate_overlay is not None


def test_zero_minutes_always_asks_and_the_setting_acts_at_once(lock_world):
    world = lock_world
    window = world.window
    hold_the_lock(window)
    window.gate_overlay.keep_open.click()
    type_answer(window, right=True)
    window.leave_parent_mode()
    window.apply_settings(replace(world.controller.settings, parent_unlock_minutes=0))
    hold_the_lock(window)
    assert window.gate_overlay is not None
    assert not window.gate_overlay.keep_open.isVisible()


def test_the_parents_view_goes_back_after_the_idle_time(world):
    window, clock = world.window, world.clock
    view = open_parents(window)
    clock.advance(9 * 60)
    window._tick()
    assert window.parent_mode
    QTest.keyClick(window, Qt.Key.Key_Right)  # an input starts the time again
    assert view.selected == 1
    clock.advance(9 * 60)
    window._tick()
    assert window.parent_mode
    clock.advance(61)
    window._tick()
    assert not window.parent_mode


def test_the_idle_time_closes_a_side_panel_left_open(world):
    window, clock = world.window, world.clock
    view = open_parents(window)
    view.toolbar.buttons["levels"].click()
    clock.advance(9 * 60)
    window._tick()
    assert window.parent_mode and view.panel_key == "levels"
    clock.advance(61)
    window._tick()
    assert not window.parent_mode and window.settings_panels is None  # the panel went with the view


def test_zero_idle_minutes_means_never(world):
    window, clock = world.window, world.clock
    open_parents(window)
    window.apply_settings(replace(world.controller.settings, parent_idle_minutes=0))
    clock.advance(120 * 60)
    window._tick()
    assert window.parent_mode


def test_the_idle_return_ends_the_lock_time_the_switch_does_not(lock_world):
    window, clock = lock_world.window, lock_world.clock
    hold_the_lock(window)
    window.gate_overlay.keep_open.click()  # the parents turn the lock time on
    type_answer(window, right=True)
    view = window.parent_view
    view.mode_switch.kids_button.click()  # the parents leave on purpose: the lock time stays
    hold_the_lock(window)
    assert window.parent_mode and window.gate_overlay is None
    clock.advance(10 * 60)
    window._tick()  # idle: back to the children, and the lock is shut again
    assert not window.parent_mode
    hold_the_lock(window)
    assert window.gate_overlay is not None and not window.parent_mode


def test_launchpad_taps_do_not_keep_the_parents_view_open(world):
    window, clock = world.window, world.clock
    world.record(0, 1.0)
    open_parents(window)
    for _ in range(11):
        clock.advance(60)
        world.launchpad.events = [(0, True), (0, False)]  # a child plays on the Launchpad
        window._tick()
    assert not window.parent_mode


def test_lock_and_idle_time_use_a_monotonic_clock(qapp, tmp_path, clock):
    import time

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    window = MainWindow(Controller(store, FakeAudio(clock), settings, clock=clock), None, [],
                        config_path=tmp_path / "settings.toml")
    try:
        assert window.clock is time.monotonic
    finally:
        window.timer.stop()
        window.close()
        store.close()


# ------------------------------------------------------------ the sum locks input


def test_the_launchpad_does_not_delete_under_the_sum(world):
    world.record(0, 2.0)
    world.controller.set_mode(Mode.DELETE)  # the child chose "Löschen", then held the lock
    hold_the_lock(world.window)
    world.launchpad.events = [(0, True), (0, False)]
    world.window._tick()
    assert world.controller.pad(0).sample is not None


def test_the_launchpad_does_not_record_under_the_sum_but_the_music_goes_on(world):
    world.record(1, 2.0)
    world.controller.set_mode(Mode.LOOP)
    world.controller.press(1)
    world.controller.set_mode(Mode.PLAY)
    hold_the_lock(world.window)
    world.launchpad.events = [(3, True), (3, False)]
    world.window._tick()
    world.window.press(4)
    assert world.controller.recording_pad is None
    assert 1 in world.audio.voices


def test_keep_open_follows_the_setting_and_the_switch(world):
    window = world.window
    overlay = GateOverlay(window.view_host, 5)  # never shown
    assert not overlay.keep_unlocked  # off by default
    overlay.keep_open.setChecked(True)
    assert overlay.keep_unlocked
    assert not GateOverlay(window.view_host, 0).keep_unlocked


# -------------------------------------------------------------------------- keys


def test_keys_of_the_parents_view(world):
    window, audio, controller = world.window, world.audio, world.controller
    world.record(0, 2.0)
    view = open_parents(window)
    for key, expected in ((Qt.Key.Key_Left, 0), (Qt.Key.Key_Up, 0), (Qt.Key.Key_Right, 1),
                          (Qt.Key.Key_Down, 5), (Qt.Key.Key_Down, 9), (Qt.Key.Key_Down, 9),
                          (Qt.Key.Key_Left, 8), (Qt.Key.Key_Up, 4), (Qt.Key.Key_Up, 0)):
        QTest.keyClick(window, key)
        assert view.selected == expected, key
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert calls(audio, "play")[-1] == ("play", 0, False)
    audio.finish(0)
    QTest.keyClick(window, Qt.Key.Key_L)
    assert controller.pad(0).looping and controller.mode == Mode.PLAY
    QTest.keyClick(window, Qt.Key.Key_L)
    assert not controller.pad(0).looping
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_R)
    assert controller.recording_pad == 1 and controller.mode == Mode.PLAY
    world.clock.advance(1.0)
    QTest.keyClick(window, Qt.Key.Key_R)
    assert controller.recording_pad is None and controller.pad(1).sample is not None
    QTest.keyClick(window, Qt.Key.Key_Delete)
    assert controller.pad(1).sample is None and controller.mode == Mode.PLAY
    view.undo_button.click()  # "Zurück" brings it back
    assert controller.pad(1).sample is not None


def _key(window: MainWindow, key: Qt.Key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    """A key as the parents press it: to the widget that has the focus (the window while nothing has)."""
    QTest.keyClick(QApplication.focusWidget() or window, key, modifier)


def test_every_key_the_help_names_does_what_it_says(world):
    """The help behind "Tasten ?" lists the keys; each entry has a check here, and each check passes."""
    window, controller, audio = world.window, world.controller, world.audio
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    world.record(0, 2.0)
    view = open_parents(window)
    view.toolbar.keys_button.click()
    entries = [entry.split(" ", 1)[0] for entry in view.detail.help.split(" · ")]
    ctrl = Qt.KeyboardModifier.ControlModifier

    def arrows():
        _key(window, Qt.Key.Key_Right)
        _key(window, Qt.Key.Key_Down)
        assert view.selected == 5 and view.detail.pad == 5
        _key(window, Qt.Key.Key_Up)
        _key(window, Qt.Key.Key_Left)
        assert view.selected == 0

    def space():
        _key(window, Qt.Key.Key_Space)
        assert calls(audio, "play")[-1] == ("play", 0, False)
        audio.finish(0)

    def loop():
        _key(window, Qt.Key.Key_L)
        assert controller.pad(0).looping and controller.mode == Mode.PLAY
        _key(window, Qt.Key.Key_L)
        assert not controller.pad(0).looping

    def record():
        _key(window, Qt.Key.Key_Right)
        _key(window, Qt.Key.Key_R)
        assert controller.recording_pad == 1
        world.clock.advance(1.0)
        _key(window, Qt.Key.Key_R)
        assert controller.recording_pad is None and controller.pad(1).sample is not None

    def delete():
        _key(window, Qt.Key.Key_Delete)
        assert controller.pad(1).sample is None and controller.mode == Mode.PLAY

    def undo():
        _key(window, Qt.Key.Key_Z, ctrl)
        assert controller.pad(1).sample is not None  # the deletion is taken back

    def redo():
        _key(window, Qt.Key.Key_Y, ctrl)
        assert controller.pad(1).sample is None  # and done again
        _key(window, Qt.Key.Key_Z, ctrl)

    def enter():
        _key(window, Qt.Key.Key_Return)
        assert view.detail.is_open and view.detail.tab == "loop"
        _key(window, Qt.Key.Key_Return)
        assert not view.detail.is_open

    def marker():
        _key(window, Qt.Key.Key_Left)
        view.detail.open_tab("loop")
        wave = view.detail.loop_tab.waveform
        frame = wave.loop_frames // 3
        wave.pick(wave._x_of(frame), frame)  # a tap on the wave puts the cursor there
        _key(window, Qt.Key.Key_M)
        assert controller.markers(0) == [frame]

    def escape():
        view.toolbar.buttons["levels"].click()
        assert view.panel_key == "levels" and not view.detail.is_open
        view.detail.open_tab("pad")  # the detail panel unfolds, the side panel closes for it
        view.toolbar.buttons["system"].click()  # and the other way round
        _key(window, Qt.Key.Key_Escape)  # the top layer first: the side panel
        assert view.panel_key is None
        view.detail.open_tab("record")
        _key(window, Qt.Key.Key_Escape)  # then the unfolded detail panel
        assert not view.detail.is_open and window.parent_mode
        controller.set_mode(Mode.DELETE)  # nothing open: as before, Esc leaves a mode of the children
        _key(window, Qt.Key.Key_Escape)
        assert controller.mode == Mode.PLAY and window.parent_mode

    def f1():
        _key(window, Qt.Key.Key_F1)
        assert not window.parent_mode

    checks = {"Pfeile": arrows, "Leertaste": space, "L": loop, "R": record, "Entf": delete,
              "Enter": enter, "M": marker, "Esc": escape, "Strg+Z": undo, "Strg+Y": redo, "F1": f1}
    assert sorted(entries) == sorted(checks)  # nothing in the help without a check, nothing missing
    for entry in entries:  # in the order of the help
        checks[entry]()


def test_tab_never_lands_on_a_widget_out_of_sight_and_closing_gives_the_keys_back(world):
    window = world.window
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    world.like_the_mockup()
    view = open_parents(window)

    def walk(steps: int = 30) -> list[QWidget]:
        reached = []
        for _ in range(steps):
            _key(window, Qt.Key.Key_Tab)
            focus = QApplication.focusWidget()
            if focus is not None and focus is not window:
                assert focus.isVisible() and not focus.visibleRegion().isEmpty(), type(focus).__name__
                assert view.isAncestorOf(focus)  # never the hidden child page behind the view
                reached.append(focus)
        return reached

    assert walk() == []  # the pads alone: nothing to tab to, the keys stay with the pads
    for key in ("levels", "devices", "tempo", "system"):
        window.open_tool(key)
        reached = walk()
        assert reached and all(view.side_panel.isAncestorOf(w) for w in reached), key
        view.side_panel.close_button.click()  # the cross, with a field of the panel in focus
        before = view.selected
        _key(window, Qt.Key.Key_Right)
        assert view.selected == before + 1, key  # the keys belong to the pads again
        _key(window, Qt.Key.Key_Left)
    view.detail.open_tab("record")
    reached = walk()
    assert reached and all(view.detail.isAncestorOf(w) for w in reached)
    view.detail.fold_button.click()
    _key(window, Qt.Key.Key_Right)
    assert view.selected == 1
    view.detail.open_tab("record")
    walk(3)
    _key(window, Qt.Key.Key_Escape)  # Esc folds it from a field, too
    assert not view.detail.is_open
    _key(window, Qt.Key.Key_Right)
    assert view.selected == 2


def test_backspace_deletes_nothing(world):
    world.record(0, 2.0)
    open_parents(world.window)
    QTest.keyClick(world.window, Qt.Key.Key_Backspace)
    assert world.controller.pad(0).sample is not None


def test_the_keys_do_nothing_on_the_child_page(world):
    window, audio, controller = world.window, world.audio, world.controller
    world.record(0, 2.0)
    before = list(audio.calls)
    for key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Space,
                Qt.Key.Key_L, Qt.Key.Key_R, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        QTest.keyClick(window, key)
    assert audio.calls == before and controller.mode == Mode.PLAY
    assert controller.recording_pad is None and controller.pad(0).sample is not None
    assert not window.parent_mode


def test_a_held_pad_is_let_go_when_the_view_changes(world):
    window, controller, clock = world.window, world.controller, world.clock
    pad = window.grid.pads[2]
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pad.rect().center())
    clock.advance(FREE_HOLD_SECONDS * 0.5)
    assert controller.hold_progress(2) is not None
    window.enter_parent_mode()
    assert controller.hold_progress(2) is None
    QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pad.rect().center())
    assert controller.recording_pad is None and not controller.is_free(2)
    # The same for a start field held in the parents' view.
    tile = window.parent_view.tiles[3]
    QTest.mousePress(tile, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     tile.start_field().center().toPoint())
    assert controller.hold_progress(3) is not None
    window.leave_parent_mode()
    assert controller.hold_progress(3) is None and controller.recording_pad is None


# ------------------------------------------------------------------------- tools


@pytest.mark.parametrize("tool,page", [("changes", "changes"), ("sets", "sets"), ("export", "export"),
                                       ("levels", "levels"), ("devices", "devices"),
                                       ("system", "system"), ("chip", "tempo")])
def test_every_tool_opens_its_side_panel(world, tool, page):
    window = world.window
    view = open_parents(window)
    button = view.bar_chip if tool == "chip" else view.toolbar.buttons[tool]
    button.click()
    assert view.panel_key == page and view.side_panel.isVisible()
    assert window.parent_mode and not window._dialog_open  # nothing modal
    button.click()  # the same tool again closes it
    assert view.panel_key is None


def test_pads_and_launchpad_play_while_a_panel_is_open(world):
    window, controller, audio = world.window, world.controller, world.audio
    world.record(0, 2.0)
    view = open_parents(window)
    view.toolbar.buttons["levels"].click()
    tile = view.tiles[0]
    tap(tile, tile.start_field().center())  # the start field of a tile beside the panel
    assert calls(audio, "play")[-1] == ("play", 0, False)
    audio.finish(0)
    world.launchpad.events = [(3, True), (3, False)]  # a child on the Launchpad
    window._tick()
    assert controller.recording_pad == 3
    assert view.panel_key == "levels"


def test_opening_a_set_from_the_panel_closes_it_and_stays_in_the_parents_view(world, tmp_path):
    window, controller = world.window, world.controller
    world.record(0, 1.0)
    handed = []
    window.on_open_set = handed.append
    world.session.save(tmp_path / "sets" / "Probe.loopset")
    view = open_parents(window)
    view.toolbar.buttons["sets"].click()
    sets = view.side_panel.current_page()
    sets.open_tab.click()
    sets.rows[0].click()
    button = sets.open_button if sets.open_button.isVisible() else sets.open_anyway_button
    button.click()
    assert len(handed) == 1 and handed[0] is sets.opened
    assert view.panel_key is None and window.parent_mode
    assert controller.pad(0).sample is not None  # the app swaps the session between two event loops


def test_the_sets_tool_is_there_only_with_a_session(qapp, tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")
    try:
        window.resize(1280, 800)
        window.show()
        window.enter_parent_mode()
        assert window.parent_view.toolbar.buttons["sets"].isHidden()
        assert not window.parent_view.toolbar.buttons["export"].isHidden()
    finally:
        window.timer.stop()
        window.close()
        store.close()


# ------------------------------------------------------------------------ settings


def test_the_two_new_settings_are_checked():
    assert (Settings().parent_unlock_minutes, Settings().parent_idle_minutes) == (0, 10)
    parsed = parse_settings({"parent_unlock_minutes": 15, "parent_idle_minutes": 30})
    assert (parsed.parent_unlock_minutes, parsed.parent_idle_minutes) == (15, 30)
    for bad in (-1, 241, 2.5, "5", True):
        with pytest.raises(ConfigError):
            parse_settings({"parent_idle_minutes": bad})
    for bad in (-1, 16, 240, 2.5, "5", True):
        with pytest.raises(ConfigError):
            parse_settings({"parent_unlock_minutes": bad})


# ---------------------------------------------------------------------- the look


def _small(image: QImage) -> np.ndarray:
    """``image`` shrunk to 64 x 40 (smooth), as an array of RGB values."""
    small = image.convertToFormat(QImage.Format.Format_RGB32).scaled(
        64, 40, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    raw = np.frombuffer(small.constBits(), np.uint8).reshape(40, small.bytesPerLine())[:, :64 * 4]
    return raw.reshape(40, 64, 4)[:, :, :3].astype(np.float64)


def _difference(a: QImage, b: QImage) -> float:
    """Mean colour difference per channel (0..255) of the two images at 64 x 40."""
    return float(np.mean(np.abs(_small(a) - _small(b))))


# The whole parents' view at 1280 x 800 against the mockup. At 64 x 40 one cell is 20 x 20 px, so the
# check sees the layout (tool bar, header, which tiles are coloured where, the detail line) and not
# the type. Differences that remain on purpose: the mockup shows pad names, a sixth pad with a sound
# (pad 10) and the tabs of the detail field (later parts). Measured with the test font: about 10.3.
# The counter-checks lie far above: the child page about 82, an empty dark window about 110, a black
# one about 124. The threshold leaves room for font rendering, not for a different layout.
LOOK_THRESHOLD = 15.0


def test_the_parents_view_looks_like_the_mockup(world):
    world.like_the_mockup()
    window = world.window
    view = open_parents(window)
    view.select(4)
    window._tick()
    QTest.qWait(20)
    shot = window.grab().toImage()
    assert (shot.width(), shot.height()) == (1280, 800)
    mockup = QImage(str(MOCKUP)).copy(0, 0, 1280, 800)  # below y = 800 is the caption of the mockup
    assert not mockup.isNull()
    difference = _difference(shot, mockup)
    assert difference < LOOK_THRESHOLD, difference
    # Counter-checks: an empty dark window and the child page do not pass.
    dark = QImage(1280, 800, QImage.Format.Format_RGB32)
    dark.fill(QColor("#0E0E10"))
    assert _difference(dark, mockup) > 2 * LOOK_THRESHOLD
    black = QImage(1280, 800, QImage.Format.Format_RGB32)
    black.fill(QColor("#000000"))
    assert _difference(black, mockup) > 2 * LOOK_THRESHOLD
    window.leave_parent_mode()
    QTest.qWait(20)
    assert _difference(window.grab().toImage(), mockup) > LOOK_THRESHOLD


def _box(widget: QWidget, root: QWidget):
    return widget.geometry().translated(widget.parentWidget().mapTo(root, QPoint(0, 0)))


@pytest.mark.parametrize("size", [(1024, 640), (1280, 800), (1920, 1080)])
def test_nothing_overlaps_at_any_size(qapp, tmp_path, clock, size):
    w = World(tmp_path, clock, size=size)
    try:
        w.like_the_mockup()
        window = w.window
        view = open_parents(window)
        QTest.qWait(20)
        root = window.view_host
        header = [view.mode_switch, view.bar_chip, view.undo_button, view.redo_button, view.stop_button,
                  view.volume_slider]
        boxes = [_box(x, root) for x in header]
        for i, a in enumerate(boxes):
            assert root.rect().contains(a), (size, header[i])
            for b in boxes[i + 1:]:
                assert not a.intersects(b), (size, a, b)
        assert view.volume_slider.width() >= 200
        tools = [b for b in view.toolbar.buttons.values() if not b.isHidden()] + [view.toolbar.keys_button]
        tool_boxes = [_box(b, root) for b in tools]
        for i, a in enumerate(tool_boxes):
            assert a.height() >= 50, (size, tools[i].text())
            for b in tool_boxes[i + 1:]:
                assert not a.intersects(b), (size, a, b)
        header_box, detail_box = _box(view.header, root), _box(view.detail, root)
        toolbar_box = _box(view.toolbar, root)
        for tile in view.tiles:
            body = tile.body().translated(QPointF(tile.mapTo(root, QPoint(0, 0))))
            assert body.width() > 100 and body.height() > 100, size
            for other in (header_box, detail_box, toolbar_box):
                assert not body.intersects(other.toRectF()), (size, tile.index)
        assert root.rect().contains(detail_box) and not header_box.intersects(detail_box)
        # The sum fits as well, the card inside the window.
        window.leave_parent_mode()
        window._unlocked_until = 0.0
        hold_the_lock(window)
        card = window.gate_overlay.card
        assert root.rect().contains(_box(card, root)), size
        assert card.height() >= card.minimumSizeHint().height(), size
    finally:
        w.close()


def _header_at(qapp, tmp_path, clock, size) -> tuple[float, tuple, list]:
    """The share of the header the volume track has, the bar chip's lines as drawn, and the switch."""
    w = World(tmp_path, clock, size=size)
    try:
        w.like_the_mockup()
        view = open_parents(w.window)
        QTest.qWait(20)
        share = view.volume_slider._track().width() / view.header.width()
        lines = view.bar_chip.shown_lines()
        segments = []
        for segment in (view.mode_switch.kids_button, view.mode_switch.parents_button):
            word = QFontMetrics(segment.label_font()).horizontalAdvance(segment.text())
            segments.append((segment.width(), segment.ICON + segment.ICON_GAP + word + 8))
        return share, lines, segments
    finally:
        w.close()


def test_at_1024_px_the_header_cuts_nothing_and_the_volume_keeps_its_track(qapp, tmp_path, clock):
    wide_share, wide_lines, _ = _header_at(qapp, tmp_path / "wide", clock, (1280, 800))
    share, lines, segments = _header_at(qapp, tmp_path / "narrow", clock, (1024, 640))
    assert share >= wide_share - 0.002, (share, wide_share)  # as much track for its width as at 1280
    assert [text for text, _font in wide_lines] == ["96 BPM · 4/4", "aus Aufnahmelänge · 2,50 s"]
    # The narrow chip says where the bar came from without its length (the tooltip has it all), uncut.
    assert [text for text, _font in lines] == ["96 BPM · 4/4", "aus Aufnahmelänge"]
    assert all(font.pixelSize() >= 11 for _text, font in lines)
    for width, needed in segments:  # "Kinder" and "Eltern" fit their half of the switch
        assert needed <= width, (width, needed)


def test_the_header_buttons_say_what_they_do_in_their_tooltips(world):
    view = open_parents(world.window)
    assert view.redo_button.text() == "Wieder" and "Wiederholen" in view.redo_button.toolTip()
    assert "Strg+Z" in view.undo_button.toolTip() and "Strg+Y" in view.redo_button.toolTip()
    world.like_the_mockup()
    world.window._tick()
    assert "aus Aufnahmelänge · 2,50 s" in view.bar_chip.toolTip()


def _part(image: QImage, box: tuple[int, int, int, int], width: int, height: int) -> np.ndarray:
    """The part ``box`` (x, y, w, h) of ``image`` shrunk to ``width`` x ``height`` (smooth), as RGB values."""
    part = image.copy(*box).convertToFormat(QImage.Format.Format_RGB32).scaled(
        width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    raw = np.frombuffer(bytes(part.constBits()), np.uint8).reshape(height, part.bytesPerLine())
    return raw[:, :width * 4].reshape(height, width, 4)[:, :, :3].astype(np.float64)


# Parts of the mockup at 1280 x 800: (x, y, w, h) and the size they are compared at, with the
# threshold. Measured with the test font: header 10.9, loop tile 3.7, its loop symbol 6.3, its wave
# 1.9, empty tile 0.4, its record symbol 3.1, detail badge 3.2, detail text 7.9. What is left are
# the mockup's annotation badges, its pad names and font. Each threshold lies between that and the
# matching counter-check below (Kinder lit 25, play symbol 14 / 7, no wave 4.8, no text 15.8).
# Cells are 8 px for areas, 4 px for symbols; a wave or a text block is compared as a vertical
# profile (one column), because single bars and letters do not line up with the mockup.
PARTS = {
    "header": ((108, 24, 1148, 64), (143, 8), 14.0),
    "loop_tile": ((108, 112, 276, 186), (34, 23), 6.0),
    "loop_symbol": ((118, 262, 32, 28), (8, 7), 10.0),
    "loop_wave": ((124, 160, 246, 110), (1, 24), 3.2),
    "empty_tile": ((980, 112, 276, 186), (34, 23), 4.0),
    "empty_symbol": ((990, 262, 32, 28), (8, 7), 5.0),
    "detail_badge": ((124, 732, 36, 36), (9, 9), 10.0),
    "detail_text": ((176, 724, 330, 48), (1, 12), 11.0),
}


def _part_difference(shot: QImage, mockup: QImage, name: str) -> float:
    box, (width, height), _threshold = PARTS[name]
    return float(np.mean(np.abs(_part(shot, box, width, height) - _part(mockup, box, width, height))))


def test_each_part_of_the_parents_view_looks_like_the_mockup(world):
    world.like_the_mockup()
    window = world.window
    view = open_parents(window)
    view.select(4)
    window._tick()
    QTest.qWait(20)
    mockup = QImage(str(MOCKUP)).copy(0, 0, 1280, 800)
    shot = window.grab().toImage()
    for name, (_box, _size, threshold) in PARTS.items():
        assert _part_difference(shot, mockup, name) < threshold, (name, _part_difference(shot, mockup, name))

    def fails(name: str) -> bool:
        QTest.qWait(10)
        return _part_difference(window.grab().toImage(), mockup, name) >= PARTS[name][2]

    # Counter-checks: each wrong state fails its part.
    loop_tile, empty_tile = view.tiles[0], view.tiles[3]
    good_loop, good_empty = loop_tile.look, empty_tile.look
    loop_tile.set_look(replace(good_loop, wave=None))
    assert fails("loop_wave")
    loop_tile.set_look(replace(good_loop, looping=False))  # play instead of the loop sign
    assert fails("loop_symbol")
    loop_tile.set_look(replace(good_loop, color="yellow"))
    assert fails("loop_tile")
    loop_tile.set_look(good_loop)
    empty_tile.set_look(replace(good_empty, filled=True))  # play instead of the record dot
    assert fails("empty_symbol")
    empty_tile.set_look(replace(good_empty, color="green"))
    assert fails("empty_tile")
    empty_tile.set_look(good_empty)
    view.mode_switch.parents_button.setChecked(False)
    view.mode_switch.kids_button.setChecked(True)
    assert fails("header")
    detail = view.detail
    content = (detail.number, detail.color, detail.title, detail.info, detail.help)
    detail.set_content(content[0], "white", *content[2:])
    assert fails("detail_badge")
    detail.set_content(content[0], content[1], "", "", "")
    assert fails("detail_text")



# ------------------------------------------------------ the look of a side panel (L2-05)

MOCKUP_PANEL = REPO / "mockups" / "L2-05_eltern_werkzeug_seitenleiste_pegel.png"
# The whole window with the panel "Pegel" open against mockup L2-05, at 64 x 40 as above. Measured with the
# test font: about 14.6. What is left on purpose: the pad names and pad 10 of the mockup, its filled level
# scale (no take was loud in the test) and the longer hints under the switches. The counter-checks lie far
# above: the same window with the panel closed about 76, the pad view of L2-02 about 78.
PANEL_LOOK_THRESHOLD = 18.0
# Parts: (x, y, w, h), the size they are compared at, and the threshold. Measured: the narrower pads 17.1,
# the foot of the panel beside the detail line 30.0, the tool bar with "Pegel" lit 4.6, the slider of the
# ceiling as a horizontal profile 12.5. Counter-checks: another tool lit 10.3, the slider row of "Geräte"
# 16.7, of "Export" 23.4 and of "System" 26.7; with the panel closed (pads and detail line as wide as the
# window) the pads and the foot fail (the foot about 88).
PANEL_PARTS = {
    "pads": ((108, 112, 640, 588), (80, 73), 21.0),
    "beside": ((760, 640, 496, 140), (62, 17), 45.0),
    "toolbar": ((20, 20, 76, 760), (9, 95), 7.0),
    "ceiling": ((796, 230, 440, 60), (55, 1), 14.5),
}


def _panel_part_difference(shot: QImage, mockup: QImage, name: str) -> float:
    box, (width, height), _threshold = PANEL_PARTS[name]
    return float(np.mean(np.abs(_part(shot, box, width, height) - _part(mockup, box, width, height))))


def test_the_level_panel_looks_like_the_mockup(world):
    world.like_the_mockup()
    window = world.window
    view = open_parents(window)
    view.select(4)
    world.controller.set_max_level_db(-6.0)  # the ceiling of the mockup
    view.toolbar.buttons["levels"].click()
    window._tick()
    QTest.qWait(20)
    mockup = QImage(str(MOCKUP_PANEL)).copy(0, 0, 1280, 800)  # below y = 800 is the caption
    assert not mockup.isNull()
    shot = window.grab().toImage()
    assert (shot.width(), shot.height()) == (1280, 800)
    difference = _difference(shot, mockup)
    assert difference < PANEL_LOOK_THRESHOLD, difference
    for name, (_box, _size, threshold) in PANEL_PARTS.items():
        assert _panel_part_difference(shot, mockup, name) < threshold, (name, _panel_part_difference(
            shot, mockup, name))

    def grab() -> QImage:
        window._tick()
        QTest.qWait(20)
        return window.grab().toImage()

    # Counter-checks: another panel fails the tool bar and the slider row; no panel fails the whole look.
    for other in ("devices", "export", "system"):
        view.toolbar.buttons[other].click()
        other_shot = grab()
        assert _panel_part_difference(other_shot, mockup, "toolbar") >= PANEL_PARTS["toolbar"][2], other
        assert _panel_part_difference(other_shot, mockup, "ceiling") >= PANEL_PARTS["ceiling"][2], other
    view.close_panel()
    closed = grab()
    assert _difference(closed, mockup) > 3 * PANEL_LOOK_THRESHOLD
    for name in ("pads", "beside"):
        assert _panel_part_difference(closed, mockup, name) >= PANEL_PARTS[name][2], name
    assert _difference(QImage(str(MOCKUP)).copy(0, 0, 1280, 800), mockup) > 3 * PANEL_LOOK_THRESHOLD
