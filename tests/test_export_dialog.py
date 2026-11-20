"""Export page of the parents' area (offscreen, no hardware)."""

from __future__ import annotations

import soundfile
from conftest import make_settings
from test_export import session
from test_parent_area import AutoDialog

from loopstation.gui.export_dialog import (
    ExportDialog,
    default_export_dir,
    frames_text,
    rate_text,
    unique_path,
)
from loopstation.gui.settings_page import ParentAction, SettingsDialog


def texts(widget):
    from PySide6.QtWidgets import QAbstractButton, QLabel

    found = [w.text() for w in widget.findChildren(QLabel)]
    found += [w.text() for w in widget.findChildren(QAbstractButton)]
    return " | ".join(found)


def make(qapp, tmp_path, clock, **overrides):
    controller, _audio = session(tmp_path, clock, **overrides)
    dialog = ExportDialog(controller, None, export_dir=tmp_path / "out", clock=clock)
    dialog.resize(1280, 800)
    return dialog, controller


def test_default_choices_match_the_mockup(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    assert dialog.bars == 8
    assert not dialog.all_pads and not dialog.one_shots.isChecked() and dialog.fade_out.isChecked()
    shown = texts(dialog)
    assert "Summe exportieren" in shown and "Wie viele Takte?" in shown
    assert "Nur was gerade loopt" in shown and "Alle belegten Pads als Loop" in shown
    assert "Einmal-Pads am Anfang einrechnen" in shown and "Kurzer Ausklang am Ende" in shown
    assert "15 ms Fade gegen Knacken" in shown and "WAV" in shown and "Standard" in shown
    assert "Summe als WAV exportieren" in shown


def test_there_is_no_mp3_anywhere_on_the_page(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    shown = texts(dialog).lower()
    assert "mp3" not in shown and "ffmpeg" not in shown


def test_length_and_frames_follow_the_bar_count(qapp, tmp_path, clock):
    dialog, controller = make(qapp, tmp_path, clock)
    rate, grid = controller.sample_rate, controller.grid_frames()
    assert dialog.length_label.text() == "8 Takte × 1,00 s = 8,0 s"
    assert dialog.frames_label.text() == f"{frames_text(8 * grid)} Frames · {rate_text(rate)}"
    dialog.bar_chips[16].click()
    assert dialog.bars == 16 and dialog.length_label.text().startswith("16 Takte")
    dialog.bar_chips[0].click()
    assert dialog.custom_row.isVisibleTo(dialog)
    dialog.custom_spin.setValue(12)
    assert dialog.bars == 12 and dialog.length_label.text().startswith("12 Takte")


def test_pad_counts_and_the_preview_follow_the_scope(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    assert dialog.running_count.text() == "2 Pads" and dialog.all_count.text() == "3 Pads"
    assert [r[0] for r in dialog.preview.rows] == ["Pad 1", "Pad 3"]
    dialog.scope_all.setChecked(True)
    assert [(r[0], r[1]) for r in dialog.preview.rows] == [("Pad 1", 1.0), ("Pad 2", 2.0), ("Pad 3", 1.0)]
    dialog.scope_running.setChecked(True)
    dialog.one_shots.setChecked(True)
    assert [r[2] for r in dialog.preview.rows] == [False, False, True]  # the one-shot is marked


def test_export_writes_a_wav_with_the_exact_length(qapp, tmp_path, clock):
    dialog, controller = make(qapp, tmp_path, clock)
    path = dialog.export_sum()
    assert path is not None and path.parent == tmp_path / "out" and path.suffix == ".wav"
    assert path.name.startswith("summe_8takte_") and dialog.last_path == path
    with soundfile.SoundFile(str(path)) as handle:
        assert len(handle) == 8 * controller.grid_frames() and handle.subtype == "PCM_24"
    assert str(path) in dialog.sum_message.text()


def test_the_export_button_exports(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    dialog.export_button.click()
    assert dialog.last_path is not None and dialog.last_path.exists()
    assert dialog.export_button.isChecked()  # stays filled, it is the main action


def test_a_second_export_in_the_same_minute_does_not_overwrite(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    first, second = dialog.export_sum(), dialog.export_sum()
    assert first != second and first.exists() and second.exists()
    assert unique_path(tmp_path / "out", first.name) not in (first, second)


def test_without_a_grid_the_page_explains_and_offers_the_stand_in(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock, loop_sync=False)
    assert dialog.stand_in_widgets.isVisibleTo(dialog)
    assert "keinen Takt" in dialog.length_label.text()
    assert dialog.export_sum() is None
    assert "keinen Takt" in dialog.sum_message.text() and not (tmp_path / "out").exists()
    dialog.stand_in.setChecked(True)
    assert "Takte ×" in dialog.length_label.text()
    path = dialog.export_sum()
    with soundfile.SoundFile(str(path)) as handle:
        assert "NOTBEHELF" in handle.comment


def test_with_a_grid_the_stand_in_is_not_offered(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    assert not dialog.stand_in_widgets.isVisibleTo(dialog)


def test_nothing_to_export_says_so(qapp, tmp_path, clock):
    from test_controller import build

    controller, _ = build(tmp_path, clock)
    dialog = ExportDialog(controller, None, export_dir=tmp_path / "out", clock=clock)
    assert dialog.export_sum() is None
    assert "nichts zu exportieren" in dialog.sum_message.text()
    assert not dialog.loop_button.isEnabled() and dialog.selected_loop_pad() is None


def test_single_loop_export_writes_the_sample_unchanged(qapp, tmp_path, clock):
    dialog, controller = make(qapp, tmp_path, clock)
    assert dialog.selected_loop_pad() == 0  # first pad with a recording
    assert not dialog.pad_chips[3].isEnabled()  # empty pad
    dialog.pad_chips[1].click()
    assert "Pad 2 · Aufnahme 2,00 s · 2 Takte · im Raster" in dialog.loop_info.text()
    dialog.loop_button.click()
    path = dialog.last_path
    assert path is not None and path.name.startswith("pad02_")
    data, rate = soundfile.read(str(path), dtype="float32")
    expected = controller.sample_audio(controller.pad(1).sample)
    assert rate == controller.sample_rate and len(data) == len(expected)
    assert abs(data - expected).max() < 1e-4


def test_limit_note_names_the_parents_ceiling(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock, max_level_db=-12.0)
    assert "-12 dBFS" in dialog.limit_label.text()


def test_the_default_folder_is_below_documents(qapp):
    assert default_export_dir().parts[-2:] == ("Loopstation", "Export")


# ---------------------------------------------- way in from the parents' area


def test_settings_page_shows_an_export_button_that_opens_the_page(qapp, tmp_path):
    opened = []
    action = ParentAction("download", "Export", lambda parent: opened.append(parent))
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [],
                            None, None, [action])
    dialog.action_buttons["Export"].click()
    assert opened == [dialog]


def test_settings_page_without_actions_has_no_extra_buttons(qapp, tmp_path):
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
    assert dialog.action_buttons == {}


def test_main_window_offers_the_export_only_behind_the_gate(qapp, tmp_path, clock):
    from conftest import FakeAudio
    from PySide6.QtWidgets import QDialog

    from loopstation.controller import Controller
    from loopstation.gui.main_window import MainWindow
    from loopstation.store import EventStore

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    win = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")
    try:
        # The child page has no export control at all.
        from PySide6.QtWidgets import QAbstractButton

        child = [b.text() for b in win.frame.findChildren(QAbstractButton)]
        assert not any("xport" in t for t in child)
        shown, exports = [], []
        win.gate_factory = lambda _parent: AutoDialog(QDialog.DialogCode.Accepted)
        win.settings_factory = lambda *a: shown.append(a) or AutoDialog(QDialog.DialogCode.Rejected)
        win.export_factory = lambda c, p: exports.append((c, p)) or AutoDialog(QDialog.DialogCode.Rejected)
        win.open_parent_area()
        actions = shown[0][5]
        assert [a.label for a in actions] == ["Export"]
        actions[0].open(win)
        assert exports == [(controller, win)]
    finally:
        win.timer.stop()
        win.close()
        store.close()

