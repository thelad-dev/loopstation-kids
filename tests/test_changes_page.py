"""Changes page of the parents' area (mockup 12): list, back/forward, per-pad undo, delete all."""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtWidgets import QDialog, QLabel

from loopstation.controller import Controller, Mode
from loopstation.gui.changes_page import ChangesPage, describe_change
from loopstation.store import EventStore


class Answer(QDialog):
    """Stands in for the confirm dialog: ``exec`` returns a fixed result."""

    result_code = QDialog.DialogCode.Accepted
    asked = 0

    def __init__(self, parent=None):
        super().__init__(parent)

    def exec(self):
        type(self).asked += 1
        return type(self).result_code


@pytest.fixture
def parts(qapp, tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    page = ChangesPage(controller)
    page.confirm_factory = Answer
    Answer.asked = 0
    Answer.result_code = QDialog.DialogCode.Accepted
    page.resize(760, 600)
    page.show()
    return controller, page, clock


def record(controller, clock, pad, seconds=1.0, mode=Mode.PLAY):
    controller.set_mode(mode)
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)
    clock.advance(60)


def texts(page):
    return [" ".join(label.text() for label in row.findChildren(QLabel)) for row in page.rows]


def test_empty_page_has_nothing_to_do(parts):
    _controller, page, _clock = parts
    assert page.rows == []
    assert not page.back_button.isEnabled() and not page.forward_button.isEnabled()
    assert "nichts mehr möglich" in page.back_label.text()
    assert "nichts zu wiederholen" in page.forward_label.text()


def test_list_follows_recording_and_deleting(parts):
    controller, page, clock = parts
    record(controller, clock, 0)
    record(controller, clock, 4)
    assert [entry.pads for entry in page.row_entries] == [(4,), (0,)]  # newest first
    assert "Pad 5 · neue Aufnahme" in texts(page)[0]
    assert "Pad 1 · neue Aufnahme" in texts(page)[1]
    assert page.back_label.text() == "Zurück möglich: 2 Schritte"

    controller.set_free(0, True)
    controller.delete_all()
    assert "Alle Pads gelöscht" in texts(page)[0]
    assert page.back_label.text() == "Zurück möglich: 4 Schritte"
    controller.undo()
    controller.undo()
    assert [entry.undone for entry in page.row_entries[:2]] == [True, True]
    assert "Alle Pads gelöscht" in texts(page)[0]
    assert "freier Modus an" in texts(page)[1]
    assert page.forward_label.text().startswith("Wiederholen möglich: 2 Schritte")


def test_descriptions_of_each_kind(parts):
    controller, page, clock = parts
    record(controller, clock, 2)
    record(controller, clock, 2, mode=Mode.RECORD)  # replaces the first take
    controller.set_free(2, True)
    controller.restore(2, controller.history(2)[0].sample)
    controller.set_mode(Mode.PLAY)
    shown = [describe_change(entry) for entry in controller.changes()]
    assert shown[0] == "Pad 3 · älterer Take zurückgeholt"
    assert shown[1] == "Pad 3 · freier Modus an"
    assert shown[2].startswith("Pad 3 · neue Aufnahme (") and shown[2].endswith("ersetzt die vorherige")
    assert shown[3].startswith("Pad 3 · neue Aufnahme (") and "ersetzt" not in shown[3]


def test_time_comes_from_the_event_not_from_showing(parts):
    controller, page, clock = parts
    record(controller, clock, 1)
    expected = datetime.fromtimestamp(clock() - 60)  # the fake clock stood here when the event was written
    when = controller.changes()[0].when
    assert abs((when - expected).total_seconds()) < 2
    assert when.strftime("%H:%M") in texts(page)[0]
    clock.advance(3 * 3600)  # showing it later changes nothing
    page.refresh()
    assert controller.changes()[0].when == when
    # an undone change keeps the time of the change itself, not of the undo
    controller.undo()
    assert controller.changes()[0].undone and controller.changes()[0].when == when


def test_global_buttons_undo_and_redo(parts):
    controller, page, clock = parts
    record(controller, clock, 0)
    assert page.back_button.isEnabled() and not page.forward_button.isEnabled()
    page.back_button.click()
    assert controller.pad(0).sample is None
    assert not page.back_button.isEnabled() and page.forward_button.isEnabled()
    assert page.row_entries[0].undone
    page.forward_button.click()
    assert controller.pad(0).sample is not None
    assert not page.forward_button.isEnabled()
    assert not page.row_entries[0].undone


def test_only_this_pad_takes_back_just_that_pad(parts):
    controller, page, clock = parts
    record(controller, clock, 0)
    record(controller, clock, 1)
    record(controller, clock, 2)
    first = page.row_buttons[2]  # pad 1, the oldest row
    assert first is not None and first.isEnabled()
    first.click()
    assert controller.pad(0).sample is None
    assert controller.pad(1).sample is not None and controller.pad(2).sample is not None
    assert controller.can_redo(0)
    assert page.row_entries[0].undone and page.row_entries[0].pads == (0,)  # shown as undone


def test_only_the_latest_row_of_a_pad_has_an_active_button(parts):
    controller, page, clock = parts
    record(controller, clock, 3)
    record(controller, clock, 3, mode=Mode.RECORD)
    newest, older = page.row_buttons
    assert newest.isEnabled() and not older.isEnabled()
    assert older.toolTip()
    newest.click()  # now the older row is the latest of the pad
    assert controller.pad(3).sample == controller.history(3)[0].sample
    record(controller, clock, 5)
    controller.delete_all()  # a change of many pads has no per-pad button
    assert page.row_buttons[0] is None
    assert not any(button is not None and button.isEnabled() for button in page.row_buttons[1:])


def test_delete_all_asks_and_can_be_undone(parts):
    controller, page, clock = parts
    record(controller, clock, 0)
    record(controller, clock, 7)

    Answer.result_code = QDialog.DialogCode.Rejected
    page.delete_button.click()
    assert Answer.asked == 1
    assert controller.pad(0).sample is not None and controller.pad(7).sample is not None
    assert len(page.rows) == 2  # nothing happened

    Answer.result_code = QDialog.DialogCode.Accepted
    page.delete_button.click()
    assert Answer.asked == 2
    assert controller.pad(0).sample is None and controller.pad(7).sample is None
    assert "Alle Pads gelöscht" in texts(page)[0]

    page.back_button.click()
    assert controller.pad(0).sample is not None and controller.pad(7).sample is not None


def test_default_confirm_is_the_existing_dialog(qapp, tmp_path, clock):
    from loopstation.gui.confirm_dialog import ConfirmDialog

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    page = ChangesPage(Controller(store, FakeAudio(clock), settings, clock=clock))
    assert page.confirm_factory is ConfirmDialog


def test_page_is_narrow_enough_and_scrolls_dark(parts):
    _controller, page, _clock = parts
    assert page.minimumSizeHint().width() <= 760
    assert "QScrollBar:vertical" in page.styleSheet()


def test_refresh_skips_unchanged_state_and_caps_rows(parts, monkeypatch):
    controller, page, clock = parts
    record(controller, clock, 0)
    row = page.rows[0]
    page.refresh()
    assert page.rows[0] is row  # unchanged: not rebuilt
    monkeypatch.setattr("loopstation.gui.changes_page.MAX_ROWS", 2)
    for pad in (1, 2, 3):
        record(controller, clock, pad)
    assert len(page.rows) == 2
    assert any("ältere Schritte" in label.text() for label in page.findChildren(QLabel))


def test_page_survives_its_own_destruction(parts):
    controller, page, clock = parts
    page.deleteLater()
    del page
    record(controller, clock, 0)  # the weak listener finds nothing and does nothing
