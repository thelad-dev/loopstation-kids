"""Parents' area: the gate, the entry in the window, the settings page (offscreen, no hardware)."""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from loopstation.config import Settings, load_settings
from loopstation.controller import Controller
from loopstation.gui import settings_page
from loopstation.gui.parent_gate import ENTRY_SIZE, HOLD_MS, GateQuestion, ParentGate, new_question
from loopstation.gui.parent_tile import TILE_HEIGHT, TILE_WIDTH
from loopstation.gui.settings_page import NOTES, Field, SettingsDialog, ToggleSwitch, register_field
from loopstation.store import EventStore


class AutoDialog(QDialog):
    """Stands in for a modal dialog: ``exec`` returns at once with a fixed result."""

    opened = 0

    def __init__(self, result, on_exec=None):
        super().__init__()
        self._result = result
        self._on_exec = on_exec

    def exec(self):
        type(self).opened += 1
        if self._on_exec:
            self._on_exec()
        return self._result


# ------------------------------------------------------------------ gate


def test_questions_are_two_digit_sums_with_carry():
    rng = random.Random(1)
    for _ in range(200):
        question = new_question(rng)
        a, b = (int(x) for x in question.text.split(" = ")[0].split(" + "))
        assert 12 <= a <= 49 and 12 <= b <= 49
        assert a % 10 + b % 10 >= 10
        assert question.answer == a + b


def test_wrong_answer_opens_nothing_and_just_closes(qapp):
    for wrong in ("41", "", "0"):
        gate = ParentGate(question=GateQuestion("17 + 25 = ?", 42))
        gate.answer_edit.setText(wrong)
        assert gate.check() is False
        assert gate.result() == QDialog.DialogCode.Rejected  # back to the child page, no alarm


def test_number_pad_types_and_deletes_digits(qapp):
    gate = ParentGate(question=GateQuestion("17 + 25 = ?", 42))
    assert gate.question_label.text() == "Wie viel ist 17 + 25 ?"
    gate.keys["4"].click()
    gate.keys["3"].click()
    gate.keys["⌫"].click()
    gate.keys["2"].click()
    assert gate.answer_edit.text() == "42"
    gate.keys["OK"].click()
    assert gate.result() == QDialog.DialogCode.Accepted


def test_right_answer_opens(qapp):
    gate = ParentGate(question=GateQuestion("17 + 25 = ?", 42))
    gate.answer_edit.setText("42")
    assert gate.check() is True
    assert gate.result() == QDialog.DialogCode.Accepted


def test_cancel_rejects(qapp):
    gate = ParentGate(question=GateQuestion("17 + 25 = ?", 42))
    gate.cancel_button.click()
    assert gate.result() == QDialog.DialogCode.Rejected


# ---------------------------------------------------------------- window


@pytest.fixture
def parts(qapp, tmp_path, clock):
    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    config_path = tmp_path / "settings.toml"
    win = MainWindow(controller, None, [], config_path=config_path)
    win.resize(1280, 800)
    win.show()
    QTest.qWaitForWindowExposed(win)
    yield win, controller, config_path
    win.timer.stop()
    win.close()
    store.close()


def test_entry_is_small_dim_and_needs_a_hold(parts):
    win, _controller, _path = parts
    entry = win.parent_entry
    # A small tile in the bottom right corner (mockup 01): lock and the word "Eltern".
    assert (entry.width(), entry.height()) == (TILE_WIDTH, TILE_HEIGHT) and entry.text() == "Eltern"
    assert ENTRY_SIZE < TILE_WIDTH  # the bare lock of the gate itself stays small
    assert HOLD_MS == 2000  # mockup 08: two seconds
    # It sits beside the buttons of the bottom row: it covers no mode button, pad or action button.
    box = entry.geometry()
    for widget in [*win.mode_buttons.values(), *win.grid.pads, win.undo_button, win.stop_button,
                   win.delete_all_button]:
        top_left = widget.mapTo(win.frame, QPoint(0, 0))
        assert not box.intersects(widget.rect().translated(top_left))
    held = []
    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Rejected)
    entry.held.connect(lambda: held.append(1))
    QTest.mouseClick(entry, Qt.MouseButton.LeftButton)  # a tap is not enough
    QTest.qWait(50)
    assert held == []
    QTest.mousePress(entry, Qt.MouseButton.LeftButton)
    entry._timer.timeout.emit()  # the hold time has passed
    QTest.mouseRelease(entry, Qt.MouseButton.LeftButton)
    assert held == [1]


def test_wrong_gate_answer_never_shows_the_settings(parts):
    win, _controller, _path = parts
    shown = []
    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Rejected)
    win.settings_factory = lambda *a: shown.append(a) or AutoDialog(QDialog.DialogCode.Accepted)
    win.open_parent_area()
    assert shown == []
    assert win._dialog_open is False


def test_right_gate_answer_shows_the_settings(parts):
    win, controller, path = parts
    shown = []
    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Accepted)
    win.settings_factory = lambda *a: shown.append(a) or AutoDialog(QDialog.DialogCode.Rejected)
    win.open_parent_area()
    assert len(shown) == 1
    assert shown[0][0] == path and shown[0][1] is controller.settings


def test_pads_are_locked_while_the_parents_area_is_open(parts):
    win, controller, _path = parts
    seen = []

    def during():
        win.press(0)
        seen.append(controller.recording_pad)

    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Rejected, during)
    win.open_parent_area()
    win.settings_factory = lambda *_a: AutoDialog(QDialog.DialogCode.Rejected, during)
    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Accepted)
    win.open_parent_area()
    assert seen == [None, None]
    win.press(0)  # open to the children again
    assert controller.recording_pad == 0


def test_a_second_opening_while_open_is_ignored(parts):
    win, _controller, _path = parts
    AutoDialog.opened = 0

    def reenter():
        win.open_parent_area()

    win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Rejected, reenter)
    win.open_parent_area()
    assert AutoDialog.opened == 1


def test_window_apply_settings_toggles_the_launchpad_and_reports_restart(parts):
    win, controller, _path = parts
    created = []

    class FakePad:
        status_text = ""
        closed = False

        def close(self):
            self.closed = True

        def poll(self):
            return []

        def set_colors(self, _colors):
            pass

    def factory(current):
        created.append(current.launchpad)
        return FakePad() if current.launchpad else None

    win.launchpad_factory = factory
    running = controller.settings
    assert win.apply_settings(replace(running, launchpad=True, rows=5)) == ["rows"]
    pad = win.launchpad
    assert isinstance(pad, FakePad)
    win.apply_settings(replace(running, launchpad=False))
    assert pad.closed and win.launchpad is None
    assert created == [True, False]


# ------------------------------------------------------------- the page


@pytest.fixture
def page(qapp, tmp_path):
    applied = []
    running = make_settings(tmp_path)

    def apply(new):
        applied.append(new)
        return [k for k in ("rows", "cols", "sample_rate", "data_dir")
                if getattr(new, k) != getattr(running, k)]

    path = tmp_path / "settings.toml"
    shipped = (Path(__file__).resolve().parent.parent / "settings.toml").read_text(encoding="utf-8")
    dialog = SettingsDialog(path, running, apply, template=shipped)
    yield dialog, path, applied, running
    dialog.close()


def test_page_shows_the_hints_for_parents(page):
    dialog, *_ = page
    texts = " ".join(label.text() for label in dialog.findChildren(type(dialog.message)))
    for note in NOTES:
        assert note in texts
    assert "Echo" in texts and "Bluetooth" in texts and "kabelgebundene" in texts
    assert "dB(FS)" in texts and "dB(SPL)" in texts


def test_page_has_a_row_for_every_current_setting(page):
    from dataclasses import fields

    dialog, *_ = page
    assert set(dialog.editors) == {f.name for f in fields(Settings)}


def test_restart_rows_are_marked_in_the_label(page):
    from PySide6.QtWidgets import QFormLayout

    dialog, *_ = page
    labels = set()
    for form in dialog.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            labels.add(form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text())
    marked = {label for label in labels if "wirkt nach Neustart" in label}
    assert len(marked) == 4  # rows, cols, sample_rate, data_dir (the ASIO switch is a switch row)
    assert not any("wirkt nach Neustart" in label for label in labels - marked)


def test_save_writes_the_file_applies_live_values_and_flags_restart(page):
    dialog, path, applied, running = page
    dialog.editors["loop_sync"]._box.setChecked(False)
    dialog.editors["max_record_seconds"]._dspin.setValue(30)
    dialog.editors["rows"]._spin.setValue(5)
    assert dialog.save() is True
    stored = load_settings(path)
    assert (stored.loop_sync, stored.max_record_seconds, stored.rows) == (False, 30.0, 5)
    assert applied[0] == stored
    assert dialog.message.text() == "Gespeichert, wirkt nach Neustart: Zeilen"
    # The comments of the shipped template are in the new file.
    assert "Wirkt sofort." in path.read_text(encoding="utf-8")
    assert running.rows == 3


def test_refused_value_is_shown_and_nothing_is_written_or_applied(page):
    dialog, path, applied, _running = page
    dialog.editors["data_dir"]._edit.setText("   ")
    assert dialog.save() is False
    assert "data_dir" in dialog.message.text()
    assert not path.exists()
    assert applied == []


def test_auto_latency_roundtrip(page):
    dialog, path, applied, _running = page
    editor = dialog.editors["latency_ms"]
    assert editor.value() == "auto"
    editor._manual.setChecked(True)
    editor._dspin.setValue(90)
    assert dialog.save()
    assert load_settings(path).latency_ms == 90.0
    editor._auto.setChecked(True)
    assert dialog.save()
    assert load_settings(path).latency_ms is None
    assert applied[-1].latency_ms is None


def test_pending_restart_values_are_shown_when_the_page_opens_again(page, qapp):
    dialog, path, applied, running = page
    dialog.editors["cols"]._spin.setValue(7)
    assert dialog.save()
    again = SettingsDialog(path, running, lambda new: [], template=None)
    assert "Spalten" in again.message.text()
    assert again.editors["cols"]._spin.value() == 7
    again.close()


def test_later_packages_add_a_field_with_one_line(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(settings_page, "FIELDS", list(settings_page.FIELDS))
    register_field(Field("fullscreen_hint", "Beispiel", "bool"), before="rows")
    keys = [f.key for f in settings_page.FIELDS]
    assert keys.index("fullscreen_hint") == keys.index("rows") - 1
    with pytest.raises(ValueError):
        register_field(Field("rows", "doppelt", "int"))


def test_bool_fields_are_toggle_switches(page):
    dialog, *_ = page
    boxes = {f.key for f in settings_page.FIELDS if f.kind == "bool"}
    assert boxes and all(isinstance(dialog.editors[k].widget, ToggleSwitch) for k in boxes)
