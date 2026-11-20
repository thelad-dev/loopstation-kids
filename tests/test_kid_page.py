"""The child page of the mockups 01-07: pulse strip, lock tile, bottom row, history card (offscreen)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QScrollArea

from loopstation.controller import Controller, Mode
from loopstation.gui.history_dialog import HistoryDialog, relative_time
from loopstation.gui.main_window import MainWindow
from loopstation.gui.pulse_strip import beat_glow, glow_levels
from loopstation.store import EventStore


@pytest.fixture
def rig(qapp, tmp_path, clock):
    settings = make_settings(tmp_path / "live", auto_grid=True)
    audio = FakeAudio(clock)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")
    window.resize(1280, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    yield window, controller, audio, clock
    window.timer.stop()
    window.close()
    store.close()


def record(controller, clock, pad, seconds=1.0):
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def start_loop(controller, clock, pad=0):
    record(controller, clock, pad)
    controller.set_mode(Mode.LOOP)
    controller.press(pad)
    controller.set_mode(Mode.PLAY)


# ------------------------------------------------------------------ pulse strip


def test_the_glow_swells_softly_and_fades_without_a_jump():
    assert beat_glow(0.0) == 0.0 and beat_glow(0.999) < 0.01 and beat_glow(1.5) == 0.0
    steps = [beat_glow(i / 200) for i in range(200)]
    assert max(steps) == pytest.approx(1.0, abs=0.01)
    assert max(abs(a - b) for a, b in zip(steps, steps[1:], strict=False)) < 0.1  # no blinking edge


def test_exactly_one_dot_is_bright_at_any_position():
    for position in (0.3, 1.2, 2.5, 3.7):
        levels = glow_levels(4, position)
        assert sum(1 for v in levels if v > 0.5) <= 1
    assert glow_levels(4, None) == (0.0,) * 4
    assert len(glow_levels(3, 1.0)) == 3


def test_the_strip_rests_without_a_grid_and_without_playing_loops(rig):
    window, controller, _audio, clock = rig
    strip = window.pulse_strip
    window.refresh()
    assert strip.levels == (0.0,) * strip.beats
    record(controller, clock, 1)  # a grid now, but the pad does not loop
    clock.advance(10)  # the confirmation is over
    window.refresh()
    assert not any(strip.levels)


def test_the_strip_follows_the_grid_while_a_loop_plays(rig):
    window, controller, audio, clock = rig
    start_loop(controller, clock)
    info = controller.grid_info()
    assert info is not None and window.pulse_strip.beats == info.beats
    audio.boundary_in = controller.bar_seconds() * (1 - 1.3 / info.beats)  # 1.3 beats into the bar
    window.refresh()
    levels = window.pulse_strip.levels
    assert levels[1] > 0.5 and levels[0] < levels[1] and levels[2] == 0.0


def test_a_new_grid_shows_the_pulse_for_a_moment_even_without_a_loop(rig):
    window, controller, _audio, clock = rig
    window.refresh()
    record(controller, clock, 3)  # sets the grid
    clock.advance(0.1)
    window.refresh()
    assert window._pulse_until > clock()
    clock.advance(0.3)
    window.refresh()
    assert any(window.pulse_strip.levels)
    clock.advance(20)
    window.refresh()
    assert not any(window.pulse_strip.levels)


def test_the_strip_carries_the_status_text_and_the_word_puls(rig):
    window, _controller, _audio, _clock = rig
    assert window.status_label is window.pulse_strip.status_label
    window.refresh()
    assert window.status_label.text() == ""  # the strip then paints its caption "Puls"
    window.device_status = ["Kein Mikrofon gefunden"]
    window.refresh()
    assert window.status_label.text() == "Kein Mikrofon gefunden"


# --------------------------------------------------------------- lock tile and bottom row


def test_the_lock_tile_is_bottom_right_and_the_row_keeps_the_mockup_order(rig):
    window, *_ = rig
    row = [window.undo_button, window.redo_button, window.stop_button, window.pulse_strip,
           window.parent_entry]
    xs = [w.mapTo(window, w.rect().topLeft()).x() for w in row]
    assert xs == sorted(xs)
    assert window.parent_entry.text() == "Eltern"
    right = window.parent_entry.mapTo(window, window.parent_entry.rect().bottomRight())
    assert window.width() - right.x() <= 40 and window.height() - right.y() <= 40
    # All six sit on one row of the same height.
    tops = {w.mapTo(window, w.rect().topLeft()).y() for w in row}
    assert len(tops) == 1


def test_the_outer_margins_are_those_of_the_mockups(rig):
    window, *_ = rig
    left = window.mode_buttons[Mode.PLAY].mapTo(window, window.rect().topLeft()).x()
    top = window.mode_buttons[Mode.PLAY].mapTo(window, window.rect().topLeft()).y()
    assert (left, top) == (28, 24)


# ------------------------------------------------------------------------ history card


def test_relative_times():
    now = datetime(2026, 11, 20, 12, 0, 0)
    assert relative_time(None, now) == ""
    assert relative_time(now - timedelta(seconds=20), now) == "gerade eben"
    assert relative_time(now - timedelta(minutes=2, seconds=5), now) == "vor 2 Min."
    assert relative_time(now - timedelta(hours=3), now) == "vor 3 Std."
    assert relative_time(now - timedelta(days=1, hours=2), now) == "vor 1 Tag"
    assert relative_time(now - timedelta(days=3), now) == "vor 3 Tagen"
    assert relative_time(now - timedelta(days=30), now) == "21.10."


def test_history_tiles_show_the_age_of_the_take_not_the_time_of_opening(rig):
    window, controller, _audio, clock = rig
    controller.set_mode(Mode.RECORD)
    for gap in (300, 180):
        record(controller, clock, 4)
        clock.advance(gap)
    record(controller, clock, 4)
    clock.advance(120)
    first, second, third = controller.pad(4).history
    dialog = HistoryDialog(controller, 4, window)
    assert dialog.tile_labels == ["Jetzt", "Vorher", "Davor"]
    assert set(dialog.listen_buttons) == set(dialog.take_buttons) == {first, second, third}
    assert dialog.take_buttons[third].isHidden()  # on the pad now
    dialog.close()


def test_history_age_texts_come_from_the_stamps(rig):
    window, controller, _audio, clock = rig
    controller.set_mode(Mode.RECORD)
    record(controller, clock, 4)
    clock.advance(300)
    record(controller, clock, 4)
    clock.advance(120)
    dialog = HistoryDialog(controller, 4, window)
    words = [label.text() for label in dialog.findChildren(QLabel)]
    assert "vor 7 Min." in words and "vor 2 Min." in words
    assert "Pad 5 - frühere Aufnahmen" in words
    assert dialog.close_button.text() == "Schließen"
    dialog.close()


def test_many_versions_scroll_in_a_dark_bar_and_the_card_fits_1024(rig):
    window, controller, _audio, clock = rig
    controller.set_mode(Mode.RECORD)
    for _ in range(7):
        record(controller, clock, 2)
        clock.advance(60)
    dialog = HistoryDialog(controller, 2, window)
    assert dialog.minimumSizeHint().width() <= 1024
    dialog.resize(1024, 768)
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    area = dialog.findChild(QScrollArea)
    assert area.verticalScrollBar().maximum() > 0 and area.verticalScrollBar().isVisible()
    assert "#17171B" in area.styleSheet()
    assert dialog.tile_labels[:4] == ["Jetzt", "Vorher", "Davor", "Früher"]
    dialog.close()


# ------------------------------------------------------------------ waiting pad (mockup 03)


def _waiting_pad(qapp, monkeypatch, now):
    from loopstation.gui import pad_button
    from loopstation.gui.pad_button import PadButton

    monkeypatch.setattr(pad_button.time, "monotonic", lambda: now[0])
    pad = PadButton(1)
    pad.resize(200, 200)
    pad.set_look("yellow", "loop", None, 0.0, waiting=0.5)
    return pad


def _glow_pixel(pad, now, at):
    """One pixel of the glow ring just outside the pad, at time ``at``."""
    now[0] = at
    image = pad.grab().toImage()
    rect = pad._pad_rect()
    return image.pixelColor(round(rect.center().x()), round(rect.top()) - 4)


def test_waiting_pad_keeps_its_full_colour_and_symbol(qapp, monkeypatch):
    from PySide6.QtGui import QColor

    from loopstation.gui.widgets import PAD_COLORS

    now = [0.0]
    pad = _waiting_pad(qapp, monkeypatch, now)
    now[0] = 0.7
    image = pad.grab().toImage()
    rect = pad._pad_rect()
    # Right of the symbol, in the middle of the gradient: the pad colour itself, not dimmed.
    seen = image.pixelColor(round(rect.left() + rect.width() * 0.85), round(rect.center().y()))
    want = QColor(PAD_COLORS["yellow"])
    assert max(abs(seen.red() - want.red()), abs(seen.green() - want.green()),
               abs(seen.blue() - want.blue())) <= 16  # a dimmed pad would be off by 80+
    # The loop symbol is still drawn in the middle (darker ink over the yellow).
    middle = image.pixelColor(round(rect.center().x()), round(rect.center().y()))
    assert pad.overlay == "loop"
    centre_ink = [image.pixelColor(round(rect.center().x() + dx), round(rect.center().y() + dy))
                  for dx in range(-30, 31, 3) for dy in range(-30, 31, 3)]
    assert any(c.value() < seen.value() - 20 for c in centre_ink + [middle])


def test_waiting_pulse_is_slow_soft_and_periodic(qapp, monkeypatch):
    from loopstation.gui.pad_button import WAIT_PULSE_HZ

    assert 0 < WAIT_PULSE_HZ < 1  # calm and predictable, nothing that flashes
    now = [0.0]
    pad = _waiting_pad(qapp, monkeypatch, now)

    def alpha_level(at):
        c = _glow_pixel(pad, now, at)
        return c.red() + c.green() + c.blue()

    period = 1 / WAIT_PULSE_HZ
    start = alpha_level(0.3)
    assert abs(alpha_level(0.3 + 0.01) - start) <= 6  # steady between two near moments
    assert alpha_level(0.3 + period) == start  # the same after one full period
    levels = [alpha_level(period * k / 8) for k in range(8)]
    assert max(levels) - min(levels) > 30  # it does swell
    step = 0.4 * (max(levels) - min(levels))  # no jump from one eighth of a period to the next
    assert all(abs(b - a) <= step for a, b in zip(levels, levels[1:], strict=False))
