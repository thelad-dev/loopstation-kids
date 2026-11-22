"""Sets page of the parents' area and the session swap in ``app.run`` (offscreen, no hardware)."""

from __future__ import annotations

import zipfile
from datetime import datetime

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from test_session import SET_SETTINGS, Running, content, sound_card, two_takes

from loopstation import app as app_module
from loopstation import sets
from loopstation.gui.main_window import MainWindow
from loopstation.gui.sets_page import (
    SetsPage,
    clean_name,
    format_loop,
    format_size,
    target_path,
)
from loopstation.session import SetSession

NOW = datetime(2026, 11, 20, 16, 48)


@pytest.fixture
def running(tmp_path, clock):
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text("# test\nvolume = 0.5\n", encoding="utf-8")
    run = Running(tmp_path / "live", clock, settings_file)
    two_takes(run)
    yield run
    run.close()


def dialog_for(running, qapp, opened=None):
    dialog = SetsPage(running.session, opened.append if opened is not None else None, clock=lambda: NOW)
    return dialog


# ----------------------------------------------------------------- helpers


def test_names_are_safe_file_names_and_never_overwrite(tmp_path):
    assert clean_name('  Mias: Trommel/Lied?  ') == "Mias Trommel Lied"
    assert clean_name("...") == "Set"
    assert clean_name("") == "Set"
    first = target_path(tmp_path, "Mias", True, NOW)
    assert first.name == "Mias 2026-11-20.loopset"
    first.write_text("x")
    assert target_path(tmp_path, "Mias", True, NOW).name == "Mias 2026-11-20 (2).loopset"
    assert target_path(tmp_path, "Mias", False, NOW).name == "Mias 2026-11-20"


def test_number_formats():
    assert format_size(11_400_000) == "11,4 MB"
    assert format_size(3_000) == "< 0,1 MB"
    assert format_loop(None) == "frei"
    assert format_loop({"frames": 20000, "rate": 8000}) == "2,5 s Loop"


# ------------------------------------------------------------- save page


def test_save_page_shows_the_summary_and_the_target_name(running, qapp):
    dialog = dialog_for(running, qapp)
    values = dialog.summary_values
    assert values["Pads mit Aufnahme"].text() == "2 von 12"
    assert values["Aufnahmen inkl. Verlauf"].text() == "3 WAV"
    assert "bleiben erhalten" in values["Zurück-Schritte"].text()
    assert values["Einstellungen"].text() == "Kopie settings.toml"
    assert dialog.target_label.text() == "Datei: Loopstation 2026-11-20.loopset"
    dialog.name_edit.setText("Mias Trommel-Lied")
    assert dialog.target_label.text() == "Datei: Mias Trommel-Lied 2026-11-20.loopset"
    dialog.folder_radio.setChecked(True)
    assert dialog.target_label.text() == "Ordner: Mias Trommel-Lied 2026-11-20"
    assert dialog.save_tab.isChecked() and not dialog.open_tab.isChecked()


def test_save_writes_the_set_and_the_child_carries_on(running, qapp):
    dialog = dialog_for(running, qapp)
    dialog.name_edit.setText("Mias Trommel-Lied")
    dialog.save_button.click()
    target = running.sets_folder / "Mias Trommel-Lied 2026-11-20.loopset"
    assert target.is_file() and zipfile.is_zipfile(target)
    assert "Gespeichert" in dialog.message.text()
    # Saving again the same day never overwrites the first set.
    dialog.save_button.click()
    assert (running.sets_folder / "Mias Trommel-Lied 2026-11-20 (2).loopset").is_file()
    # The sets of the folder are listed on the other tab.
    dialog.open_tab.click()
    assert len(dialog.rows) == 2
    # Saved: no question when opening.
    assert running.session.unsaved() is False


def test_save_into_a_folder_set(running, qapp):
    dialog = dialog_for(running, qapp)
    dialog.folder_radio.setChecked(True)
    dialog.save_button.click()
    folder = running.sets_folder / "Loopstation 2026-11-20"
    assert (folder / sets.MANIFEST_NAME).is_file()


def test_choosing_another_place(running, qapp, tmp_path):
    dialog = dialog_for(running, qapp)
    other = tmp_path / "usb"
    other.mkdir()
    dialog.folder_chooser = lambda _parent, _start: str(other)
    dialog.choose_button.click()
    assert dialog.folder_edit.text() == str(other)
    dialog.save_button.click()
    assert (other / "Loopstation 2026-11-20.loopset").is_file()
    dialog.folder_chooser = lambda _parent, _start: ""  # cancelled: nothing changes
    dialog.choose_button.click()
    assert dialog.folder_edit.text() == str(other)


def test_save_during_a_recording_is_refused_with_a_message(running, qapp):
    running.controller.press(8)
    dialog = dialog_for(running, qapp)
    dialog.save_button.click()
    assert "Aufnahme" in dialog.message.text()
    assert dialog.message.styleSheet().count("#FF3B30") == 1
    assert not running.sets_folder.exists() or not list(running.sets_folder.iterdir())


def test_save_to_an_unwritable_place_says_so(running, qapp, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    dialog = dialog_for(running, qapp)
    dialog.folder_edit.setText(str(blocker / "sub"))
    dialog.save_button.click()
    assert dialog.message.styleSheet().count("#FF3B30") == 1 and dialog.message.text()


# ------------------------------------------------------------- open page


def make_sets(running):
    running.session.save(running.sets_folder / "Mias.loopset")
    running.clock.advance(60)
    running.session.save(running.sets_folder / "Regen.loopset")


def test_open_page_lists_sets_and_shows_the_details(running, qapp):
    make_sets(running)
    dialog = dialog_for(running, qapp)
    dialog.open_tab.click()
    assert [row.info.name for row in dialog.rows] == ["Regen", "Mias"]
    assert dialog.rows[0].isChecked()
    assert dialog.detail_title.text() == "Regen"
    values = dialog.detail_values
    assert values["Pads mit Aufnahme"].text() == "2"
    assert "bleiben" in values["Zurück-Schritte"].text()
    assert values["Wiederholen"].text() == "startet leer"
    assert values["Format"].text() == "v1 · passt"
    dialog.rows[1].click()
    assert dialog.detail_title.text() == "Mias"
    assert dialog.rows[1].isChecked() and not dialog.rows[0].isChecked()


def test_empty_folder_says_so(running, qapp):
    dialog = dialog_for(running, qapp)
    dialog.open_tab.click()
    assert dialog.rows == []
    assert not dialog.empty_label.isHidden()
    assert dialog.open_card.isHidden() and dialog.unsaved_card.isHidden()


def test_unsaved_session_asks_before_opening(running, qapp):
    make_sets(running)
    running.record(9, 1.0)  # new take after the sets were written
    assert running.session.unsaved()
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    assert not dialog.unsaved_card.isHidden() and dialog.open_card.isHidden()
    dialog.cancel_open_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected and opened == []
    assert running.store.state.pads[9].sample is not None  # nothing was replaced


def test_open_anyway_hands_the_set_over(running, qapp):
    make_sets(running)
    running.record(9, 1.0)
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    dialog.rows[1].click()
    dialog.open_anyway_button.click()
    assert len(opened) == 1 and opened[0].manifest.pad_count == 12
    assert dialog.opened is opened[0]
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_save_then_open_saves_first_under_its_own_name(running, qapp):
    make_sets(running)
    running.record(9, 1.0)
    before = {p.name for p in running.sets_folder.iterdir()}
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    dialog.save_then_open_button.click()
    after = {p.name for p in running.sets_folder.iterdir()}
    assert len(after - before) == 1 and next(iter(after - before)).startswith("Sicherung")
    assert len(opened) == 1
    assert running.session.unsaved() is False


def test_failed_backup_never_replaces_the_session(running, qapp, monkeypatch):
    make_sets(running)
    running.record(9, 1.0)
    monkeypatch.setattr(SetSession, "save", lambda self, target: (_ for _ in ()).throw(OSError("disk full")))
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    dialog.save_then_open_button.click()
    assert opened == [] and "disk full" in dialog.message.text()


def test_saved_session_opens_with_a_single_button(running, qapp):
    make_sets(running)
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    assert dialog.unsaved_card.isHidden() and not dialog.open_card.isHidden()
    dialog.open_button.click()
    assert len(opened) == 1


def test_too_new_set_cannot_be_opened_and_says_why(running, qapp):
    source = running.sets_folder / "alt.loopset"
    running.session.save(source)
    new = running.sets_folder / "zukunft.loopset"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(new, "w") as out:
        for item in src.namelist():
            raw = src.read(item)
            if item == sets.MANIFEST_NAME:
                raw = raw.replace(b"format_version = 1", b"format_version = 3")
            out.writestr(item, raw)
    opened = []
    dialog = dialog_for(running, qapp, opened)
    dialog.open_tab.click()
    row = next(r for r in dialog.rows if r.info.name == "zukunft")
    row.click()
    assert dialog.detail_values["Format"].text() == "zu neu"
    assert "neuere Loopstation" in dialog.detail_note.text()
    assert dialog.open_card.isHidden() and dialog.unsaved_card.isHidden()
    dialog.open_button.click()  # not reachable by hand, and a click does nothing either
    assert opened == []


def test_missing_device_is_shown_in_the_list_and_kept_as_a_hint(running, qapp, tmp_path):
    settings_file = tmp_path / "opa.toml"
    settings_file.write_text(SET_SETTINGS, encoding="utf-8")
    sets.write_set(
        running.sets_folder / "Opa.loopset", log_dir=running.settings.log_dir,
        samples_dir=running.settings.samples_dir, sample_rate=8000, pad_count=12,
        settings_file=settings_file,
    )
    running.session.sd = sound_card()
    dialog = dialog_for(running, qapp)
    dialog.open_tab.click()
    row = dialog.rows[0]
    assert "Focusrite" in row.hint and "Systemstandard" in row.hint
    assert "Focusrite" in dialog.detail_note.text()


def test_notices_of_the_started_session_are_shown(running, qapp):
    running.session.notices = ["Aufnahmegerät „Focusrite“ nicht gefunden, Systemstandard wird benutzt."]
    dialog = dialog_for(running, qapp)
    assert "Focusrite" in dialog.message.text()


def test_the_dialog_is_not_on_the_child_page(running, qapp):
    # Nothing about sets exists on the child page: no widget, no text.
    window = MainWindow(running.controller, None, [], set_session=running.session)
    try:
        texts = [w.text() for w in window.findChildren(object) if hasattr(w, "text") and callable(w.text)]
        assert not any("Set" in str(t) for t in texts if isinstance(t, str) and t and t != "Setzen")
    finally:
        window.timer.stop()
        window.close()


# -------------------------------------------------------- window wiring


def test_the_parents_view_has_a_sets_tool_only_with_a_session(running, qapp):
    with_session = MainWindow(running.controller, None, [], set_session=running.session,
                              config_path=running.settings_file)
    without = MainWindow(running.controller, None, [], config_path=running.settings_file)
    try:
        for window in (with_session, without):
            window.enter_parent_mode()  # the sum was answered
            window.open_tool("sets")
        assert not with_session.parent_view.toolbar.buttons["sets"].isHidden()
        assert with_session.parent_view.panel_key == "sets"
        assert without.parent_view.toolbar.buttons["sets"].isHidden()
        assert without.parent_view.panel_key is None  # no session: nothing to open
    finally:
        for window in (with_session, without):
            window.leave_parent_mode()
            window.timer.stop()
            window.close()


def test_opening_a_set_closes_the_sets_panel(running, qapp):
    make_sets(running)
    handed = []
    window = MainWindow(running.controller, None, [], set_session=running.session,
                        config_path=running.settings_file, on_open_set=handed.append)
    try:
        window.enter_parent_mode()  # the sum was answered
        window.open_tool("sets")
        sets_page = window.parent_view.side_panel.current_page()
        sets_page.open_tab.click()
        sets_page.open_button.click()
        assert len(handed) == 1 and sets_page.result() == QDialog.DialogCode.Accepted
        assert window.parent_view.panel_key is None and window.parent_mode
    finally:
        window.leave_parent_mode()
        window.timer.stop()
        window.close()


def test_cancelling_on_the_sets_panel_closes_it(running, qapp):
    window = MainWindow(running.controller, None, [], set_session=running.session,
                        config_path=running.settings_file)
    try:
        window.enter_parent_mode()
        window.open_tool("sets")
        sets_page = window.parent_view.side_panel.current_page()
        sets_page.cancel_button.click()
        assert window.parent_view.panel_key is None and sets_page.result() == QDialog.DialogCode.Rejected
    finally:
        window.leave_parent_mode()
        window.timer.stop()
        window.close()


# ------------------------------------------------------- app.run: the swap


def test_run_swaps_the_session_between_two_event_loops(tmp_path, clock, monkeypatch, qapp):
    """Open a set from inside the running app: the session is replaced, locks and folders stay right."""
    # A set made elsewhere, with a session of its own.
    source = Running(tmp_path / "other", clock)
    two_takes(source)
    expected = content(source.store.state)
    target = tmp_path / "from-a-friend.loopset"
    source.session.save(target)
    source.close()

    settings = make_settings(tmp_path / "live")
    monkeypatch.setattr(app_module, "_default_settings_text", lambda: None)
    import loopstation.audio as audio_pkg
    monkeypatch.setattr(
        audio_pkg, "create_audio", lambda s: (FakeAudio(clock, sample_rate=s.sample_rate), None))
    seen: dict = {}
    windows: list = []

    def mine() -> list:
        # Windows of this run only (earlier tests may have left theirs behind).
        return [w for w in qapp.topLevelWidgets()
                if isinstance(w, MainWindow) and w.controller.settings.data_dir == settings.data_dir]

    def step_one() -> None:
        window = mine()[0]
        windows.append(window)
        # The first session is empty and locked.
        seen["first_state"] = content(window.controller.store.state)
        seen["lock_first"] = (settings.log_dir / "loopstation.lock").exists()
        seen["guard"] = (settings.data_dir / ".session.lock").exists()
        prepared = window.set_session.prepare_open(target)
        window.on_open_set(prepared)

    def step_two() -> None:
        window = next(w for w in mine() if w not in windows)
        windows.append(window)
        seen["second_state"] = content(window.controller.store.state)
        seen["lock_second"] = (settings.log_dir / "loopstation.lock").exists()
        seen["leftovers"] = sorted(p.name for p in settings.data_dir.iterdir())
        seen["unsaved"] = window.set_session.unsaved()
        qapp.quit()

    real_exec = qapp.exec
    calls = []

    def exec_with_steps():
        calls.append(1)
        QTimer.singleShot(100, step_one if len(calls) == 1 else step_two)
        return real_exec()

    monkeypatch.setattr(qapp, "exec", exec_with_steps)
    code = app_module.run(settings, tmp_path / "live" / "settings.toml")
    assert code == 0 and len(calls) == 2
    assert seen["first_state"]["pads"]["0"]["sample"] is None
    assert seen["lock_first"] and seen["guard"] and seen["lock_second"]
    assert seen["second_state"] == expected
    assert seen["unsaved"] is False
    assert seen["leftovers"] == [".session.lock", "data", "samples", "set-saved.json"]
    # Everything is released at the end: a new start can lock again.
    from PySide6.QtCore import QLockFile
    assert QLockFile(str(settings.log_dir / "loopstation.lock")).tryLock(100)
    assert QLockFile(str(settings.data_dir / ".session.lock")).tryLock(100)
