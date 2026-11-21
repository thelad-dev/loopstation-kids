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
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QWidget

from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import FREE_HOLD_SECONDS, Controller, Mode
from loopstation.gui.main_window import MainWindow
from loopstation.gui.parent_gate import GateOverlay
from loopstation.gui.parent_view import ParentView, bar_lines
from loopstation.gui.settings_page import SettingsDialog
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
        return (data * (0.35 + 0.65 * np.abs(np.sin(2 * np.pi * 1.6 * t)))).astype(np.float32)


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


class AutoDialog(QDialog):
    def __init__(self, on_exec=None):
        super().__init__()
        self._on_exec = on_exec

    def exec(self):
        if self._on_exec:
            self._on_exec()
        return QDialog.DialogCode.Rejected


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

    def close(self) -> None:
        self.window.timer.stop()
        self.window.close()
        self.store.close()


@pytest.fixture
def world(qapp, tmp_path, clock):
    w = World(tmp_path, clock)
    yield w
    w.close()


def hold_the_lock(window: MainWindow) -> None:
    entry = window.parent_entry
    QTest.mousePress(entry, Qt.MouseButton.LeftButton)
    entry._timer.timeout.emit()  # two seconds have passed
    QTest.mouseRelease(entry, Qt.MouseButton.LeftButton)


def type_answer(window: MainWindow, right: bool) -> None:
    overlay = window.gate_overlay
    answer = overlay.question.answer + (0 if right else 1)
    QTest.keyClicks(overlay.answer_edit, str(answer))
    QTest.keyClick(overlay.answer_edit, Qt.Key.Key_Return)


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


def test_holding_the_lock_lays_the_sum_over_the_window(world):
    window = world.window
    hold_the_lock(window)
    overlay = window.gate_overlay
    assert overlay is not None and overlay.isVisible()
    assert overlay.geometry() == window.view_host.rect()  # it covers the whole window
    assert window.findChildren(QDialog) == []  # no modal dialog
    assert overlay.keep_open.isVisible() and overlay.keep_open.text() == "Sperre 5 Minuten offen lassen"


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
    window.gate_overlay.cancel_button.click()
    assert window.gate_overlay is None and not window.parent_mode
    hold_the_lock(window)
    QTest.keyClick(window.gate_overlay.answer_edit, Qt.Key.Key_Escape)
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
        QTest.keyClick(overlay.answer_edit, key)
        QTest.keyClick(window, key)
    QTest.keyClick(overlay.answer_edit, Qt.Key.Key_3)
    assert overlay.answer_edit.text() == "3"
    assert controller.recording_pad is None and audio.calls == before
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)  # no undo under the sum
    assert audio.calls == before and controller.pad(0).sample is not None


def test_after_the_sum_the_keyboard_works_again(world):
    window, controller = world.window, world.controller
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    world.record(3, 1.0)
    hold_the_lock(window)
    assert QApplication.focusWidget() is window.gate_overlay.answer_edit
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


def test_the_lock_stays_open_for_the_set_minutes(world):
    window, clock = world.window, world.clock
    open_parents(window)
    window.leave_parent_mode()
    clock.advance(4 * 60)
    hold_the_lock(window)
    assert window.parent_mode and window.gate_overlay is None  # no sum within five minutes
    window.leave_parent_mode()
    clock.advance(61)
    hold_the_lock(window)
    assert window.gate_overlay is not None and not window.parent_mode  # asked again


def test_the_lock_can_be_closed_at_once(world):
    window = world.window
    hold_the_lock(window)
    window.gate_overlay.keep_open.click()  # "Sperre 5 Minuten offen lassen" off
    type_answer(window, right=True)
    window.leave_parent_mode()
    hold_the_lock(window)
    assert window.gate_overlay is not None


def test_zero_minutes_always_asks_and_the_setting_acts_at_once(world):
    window = world.window
    open_parents(window)
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


def test_no_idle_return_while_a_parents_dialog_is_open_and_zero_means_never(world):
    window, clock = world.window, world.clock
    open_parents(window)

    def long_visit():
        clock.advance(30 * 60)
        window._tick()

    window.settings_factory = lambda *a: AutoDialog(long_visit)
    window.parent_view.toolbar.buttons["levels"].click()
    assert window.parent_mode
    window.apply_settings(replace(world.controller.settings, parent_idle_minutes=0))
    clock.advance(120 * 60)
    window._tick()
    assert window.parent_mode


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
                                       ("advanced", "advanced"), ("chip", "tempo")])
def test_every_tool_opens_the_settings_on_its_area(world, tool, page):
    window = world.window
    seen = []

    class Parents(SettingsDialog):
        def exec(self):
            seen.append(self.current_key())
            return QDialog.DialogCode.Rejected

    window.settings_factory = Parents
    view = open_parents(window)
    button = view.bar_chip if tool == "chip" else view.toolbar.buttons[tool]
    button.click()
    assert seen == [page]
    assert window.parent_mode and not window._dialog_open


@pytest.mark.parametrize("way,parents", [("button", False), ("escape", True)])
def test_leaving_the_settings(world, way, parents):
    """"Zur Kinderseite" in the settings leads to the children, Esc only back to the parents' view."""
    window = world.window

    class Parents(SettingsDialog):
        def exec(self):
            if way == "button":
                self.close_button.click()
            else:
                QTest.keyClick(self, Qt.Key.Key_Escape)
            return self.result()

    window.settings_factory = Parents
    view = open_parents(window)
    view.toolbar.buttons["devices"].click()
    assert window.parent_mode is parents


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
    assert (Settings().parent_unlock_minutes, Settings().parent_idle_minutes) == (5, 10)
    parsed = parse_settings({"parent_unlock_minutes": 0, "parent_idle_minutes": 30})
    assert (parsed.parent_unlock_minutes, parsed.parent_idle_minutes) == (0, 30)
    for bad in (-1, 241, 2.5, "5", True):
        with pytest.raises(ConfigError):
            parse_settings({"parent_idle_minutes": bad})


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


# The parents' view at 1280 x 800 against the mockup. At 64 x 40 one cell is 20 x 20 px, so the
# check sees the layout (tool bar, header, which tiles are coloured where, the detail line) and not
# the type. Differences that remain on purpose: the mockup shows pad names, a sixth pad with a sound
# (pad 10) and the tabs of the detail field (later parts). Measured with the test font: about 11.5.
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
