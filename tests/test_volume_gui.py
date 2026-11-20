"""GUI smoke test (offscreen): the volume control and the "too loud" sign."""

from __future__ import annotations

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from loopstation.audio.dynamics import db_to_gain
from loopstation.controller import Controller
from loopstation.gui.volume_slider import position_to_volume, volume_to_position
from loopstation.store import EventStore

CEILING = db_to_gain(-6.0)


@pytest.fixture
def window(qapp, tmp_path, clock):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path, volume=0.3, max_level_db=-6.0)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    win = MainWindow(controller, None, [])
    win.resize(1280, 800)
    win.show()
    QTest.qWaitForWindowExposed(win)
    yield win
    win.timer.stop()
    win.close()
    store.close()


def press_at(slider, position: float) -> None:
    """Click the slider where a handle at ``position`` (0..1 of the track) would sit."""
    x = int(slider._x_of(position))
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(x, slider.height() // 2))


def test_slider_curve_round_trips():
    for volume in (0.0, 0.1, 0.5, 1.0):
        assert position_to_volume(volume_to_position(volume)) == pytest.approx(volume)
    assert position_to_volume(2.0) == 1.0 and position_to_volume(-1.0) == 0.0


def test_slider_is_large_and_sits_in_the_top_right_corner(window):
    slider = window.volume_slider
    top_left = slider.mapTo(window, QPoint(0, 0))
    assert slider.height() >= 100 and slider.width() >= 300
    assert top_left.x() + slider.width() >= window.width() - 40  # flush right
    assert top_left.y() < 40  # in the top row
    # The same row as the mode buttons, to the right of all of them.
    for button in window.mode_buttons.values():
        assert button.mapTo(window, QPoint(button.width(), 0)).x() <= top_left.x()
    assert top_left.y() + slider.height() <= window.grid.mapTo(window, QPoint(0, 0)).y()
    assert slider.accessibleName() == "Lautstärke"


def test_slider_shows_the_controller_value(window):
    slider = window.volume_slider
    assert slider.volume == pytest.approx(0.3)
    assert slider.limit == pytest.approx(CEILING)
    window.controller.set_volume(0.45)
    assert slider.volume == pytest.approx(0.45)  # the listener refreshes the window


def test_dragging_the_slider_sets_the_controller_volume(window):
    slider = window.volume_slider
    press_at(slider, 0.5)
    assert window.controller.volume == pytest.approx(0.25, abs=0.01)
    assert window.controller.audio.volume == window.controller.volume
    press_at(slider, 0.0)
    assert window.controller.volume == 0.0


def test_child_cannot_pass_the_parents_ceiling(window):
    slider = window.volume_slider
    press_at(slider, 1.0)
    assert window.controller.volume == pytest.approx(CEILING)
    assert slider.volume <= slider.limit + 1e-9
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(slider.width() - 2, slider.height() // 2))
    assert window.controller.volume == pytest.approx(CEILING)


def test_handle_slides_down_when_the_ceiling_drops(window):
    slider = window.volume_slider
    press_at(slider, 1.0)
    before = slider._x_of(volume_to_position(slider.volume))
    window.controller.set_max_level_db(-24.0)
    after = slider._x_of(volume_to_position(slider.volume))
    assert after < before
    assert slider.volume == pytest.approx(db_to_gain(-24.0))
    assert slider.limit == pytest.approx(db_to_gain(-24.0))
    assert window.controller.volume == pytest.approx(db_to_gain(-24.0))
    slider.grab()  # painting the blocked part works


def test_wheel_moves_the_volume_in_steps(window):
    slider = window.volume_slider
    before = slider.volume
    center = QPointF(slider.width() / 2, slider.height() / 2)
    event = QWheelEvent(center, slider.mapToGlobal(center), QPoint(0, 0), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    slider.wheelEvent(event)
    assert slider.volume > before and window.controller.volume == pytest.approx(slider.volume)


def test_clip_sign_shows_on_the_recording_pad_only_while_the_input_clips(window, clock):
    controller = window.controller
    pads = window.grid.pads
    QTest.mouseClick(pads[0], Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(pads[0].width() // 2, pads[0].height() // 2))
    assert controller.recording_pad == 0 and pads[0].clip is False
    quiet = pads[0].grab().toImage()

    controller.audio.clips = 1
    controller.tick()
    window.refresh()
    assert pads[0].clip is True and all(not p.clip for p in pads[1:])
    loud = pads[0].grab().toImage()
    assert loud != quiet  # the badge is drawn: a white shape on the red pad

    clock.advance(2.0)
    window.refresh()
    assert pads[0].clip is False


def test_recording_pad_shows_a_coarse_three_step_level(window):
    controller = window.controller
    pad = window.grid.pads[0]
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(pad.width() // 2, pad.height() // 2))
    assert pad.level == 0
    for peak, stage in ((0.001, 0), (0.1, 1), (0.4, 2), (0.9, 3)):
        controller.audio.input_peak = peak
        controller.tick()
        window.refresh()
        assert controller.input_level_stage() == stage and pad.level == stage
    assert all(p.level == 0 for p in window.grid.pads[1:])
    controller.press(0)  # stop
    assert controller.input_level_stage() == 0


def test_parent_peak_meter_follows_the_switch_and_the_recording(window):
    controller = window.controller
    meter = window.peak_meter
    pad = window.grid.pads[0]
    QTest.mouseClick(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(pad.width() // 2, pad.height() // 2))
    controller.audio.input_peak = 0.5
    controller.tick()
    window.refresh()
    assert not meter.isVisibleTo(window)  # switch is off

    controller.set_peak_meter(True)
    window.refresh()
    assert meter.isVisibleTo(window)
    assert meter.position == pytest.approx(54.0 / 60.0, abs=0.01)

    controller.press(0)  # stop
    window.refresh()
    assert not meter.isVisibleTo(window)
