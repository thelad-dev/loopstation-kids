"""Export page of the parents' area (offscreen, no hardware)."""

from __future__ import annotations

import soundfile
from conftest import make_settings
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget
from test_export import session
from test_parent_area import AutoDialog

from loopstation.gui.export_dialog import (
    WORD_JOINER,
    ExportDialog,
    default_export_dir,
    frames_text,
    rate_text,
    unique_path,
)
from loopstation.gui.parent_nav import ParentPage
from loopstation.gui.settings_page import SettingsDialog


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


def test_parents_area_has_an_export_area_that_is_built_on_the_first_visit(qapp, tmp_path):
    built = []
    page = ParentPage("export", "download", "Export", lambda: built.append(1) or QWidget())
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [],
                            None, None, [page])
    assert built == [] and "export" in dialog.nav.buttons
    assert dialog.nav.buttons["export"].text() == "Export"
    dialog.nav.buttons["export"].click()
    assert built == [1] and dialog.current_key() == "export"
    dialog.nav.buttons["levels"].click()
    dialog.nav.buttons["export"].click()
    assert built == [1]  # built once, then kept


def test_parents_area_without_further_areas_has_only_the_three_settings_pages(qapp, tmp_path):
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
    assert list(dialog.nav.buttons) == ["levels", "devices", "tempo"]


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
        win.settings_factory = lambda *a: shown.append(a) or AutoDialog(QDialog.DialogCode.Rejected)
        win.export_factory = lambda c, p: exports.append((c, p)) or QWidget()
        win.enter_parent_mode()  # the sum was answered
        win.open_settings()
        pages = shown[0][5]
        assert [page.label for page in pages] == ["Verlauf & Undo", "Erweitert", "Export"]
        pages[-1].build()
        assert exports == [(controller, None)]
    finally:
        win.timer.stop()
        win.close()
        store.close()


# ------------------------------------------- scope chosen from what loops now


class ShowEvent(QShowEvent):
    """A show event whose origin the test decides (Qt sets ``spontaneous`` only for its own events)."""

    def __init__(self, spontaneous: bool) -> None:
        super().__init__()
        self._spontaneous = spontaneous

    def spontaneous(self) -> bool:
        return self._spontaneous


def silent_session(qapp, tmp_path, clock):
    """The session of ``make`` after "Alles still": three pads with a sample, none loops."""
    dialog, controller = make(qapp, tmp_path, clock)
    controller.stop_all()
    return dialog, controller


def test_when_nothing_loops_the_shown_page_takes_every_pad_as_a_loop(qapp, tmp_path, clock):
    import numpy as np

    from loopstation import export as ex

    dialog, controller = silent_session(qapp, tmp_path, clock)
    dialog.show()
    try:
        assert dialog.scope_all.isChecked() and not dialog.scope_running.isChecked()
        assert dialog.running_count.text() == "0 Pads" and dialog.all_count.text() == "3 Pads"
        assert dialog.preview.rows == [("Pad 1", 1.0, False), ("Pad 2", 2.0, False), ("Pad 3", 1.0, False)]
        dialog.bar_chips[4].click()
        path = dialog.export_sum()
        assert path is not None
        data, _rate = soundfile.read(str(path), dtype="float32")
        grid = controller.grid_frames()
        assert len(data) == 4 * grid
        expected = ex.render_sum(ex.build_spec(controller, 4, all_pads=True))
        assert np.abs(data - expected).max() < 1e-4
        # Pad 1 (one bar) repeats: every bar sounds, not only the first.
        assert all(np.abs(data[bar * grid:(bar + 1) * grid]).max() > 0.01 for bar in range(4))
    finally:
        dialog.close()


def test_while_something_loops_the_shown_page_keeps_only_what_loops(qapp, tmp_path, clock):
    dialog, _ = make(qapp, tmp_path, clock)
    dialog.show()
    try:
        assert dialog.scope_running.isChecked() and not dialog.all_pads
        assert [r[0] for r in dialog.preview.rows] == ["Pad 1", "Pad 3"]
    finally:
        dialog.close()


def test_the_parents_choice_on_the_open_page_is_kept(qapp, tmp_path, clock):
    dialog, _ = silent_session(qapp, tmp_path, clock)
    dialog.show()
    try:
        dialog.scope_running.click()
        dialog.bar_chips[16].click()
        dialog.one_shots.setChecked(True)
        assert dialog.scope_running.isChecked() and dialog.bars == 16
        # The window coming back (minimised and restored) is no new visit: the choice stays.
        dialog.showEvent(ShowEvent(spontaneous=True))
        assert dialog.scope_running.isChecked()
        # A new visit (the area shown again from the navigation) chooses anew from what loops now.
        dialog.showEvent(ShowEvent(spontaneous=False))
        assert dialog.scope_all.isChecked()
    finally:
        dialog.close()


def test_every_visit_of_the_kept_export_area_chooses_from_what_loops_then(qapp, tmp_path, clock):
    from loopstation.controller import Mode

    controller, _audio = session(tmp_path, clock)
    controller.stop_all()
    built = []

    def build():
        built.append(ExportDialog(controller, None, export_dir=tmp_path / "out", clock=clock))
        return built[-1]

    page = ParentPage("export", "download", "Export", build)
    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [],
                            None, None, [page])
    dialog.resize(1280, 800)
    dialog.show()
    try:
        dialog.nav.buttons["export"].click()
        assert built[0].scope_all.isChecked()
        dialog.nav.buttons["levels"].click()
        controller.set_mode(Mode.LOOP)
        controller.press(0)
        controller.set_mode(Mode.PLAY)
        dialog.nav.buttons["export"].click()
        assert len(built) == 1 and built[0].scope_running.isChecked()
        assert built[0].running_count.text() == "1 Pad"
        dialog.nav.buttons["levels"].click()
        controller.stop_all()
        dialog.nav.buttons["export"].click()
        assert built[0].scope_all.isChecked() and built[0].running_count.text() == "0 Pads"
    finally:
        dialog.close()


# ------------------------------------------------- the preview fits its rows


def lowest_painted_row(widget, width, height):
    """The lowest pixel row that differs from the background when ``widget`` is painted at this size."""
    widget.resize(width, height)
    image = widget.grab().toImage()
    background = image.pixel(width - 1, height - 1)
    for y in range(height - 1, -1, -1):
        if any(image.pixel(x, y) != background for x in range(width)):
            return y
    return -1


def test_the_preview_asks_for_room_for_every_row_and_the_bar_axis(qapp):
    from loopstation.gui.export_dialog import PreviewRows

    heights = {}
    for count in range(1, 17):
        preview = PreviewRows()
        preview.set_rows([(f"Pad {i + 1}", 1.0, False) for i in range(count)], 8)
        hint = preview.sizeHint().height()
        assert preview.minimumSizeHint().height() == hint == preview.minimumHeight()
        heights[count] = hint
        if count in (1, 3, 12, 16):
            # Rows and the axis ("Takt 1 ... 8", the lowest thing painted) lie inside the asked height.
            lowest = lowest_painted_row(preview, 400, hint + 200)
            assert hint - 12 <= lowest < hint, (count, lowest, hint)
    # One more row never makes the preview lower.
    assert all(heights[n] < heights[n + 1] for n in range(1, 16)), heights
    assert heights[12] <= 480  # many pads make the rows lower instead of growing without end


def test_the_preview_on_the_page_shows_all_rows_without_its_own_scrollbar(qapp, tmp_path, clock):
    from PySide6.QtWidgets import QScrollArea

    dialog, _ = silent_session(qapp, tmp_path, clock)
    dialog.resize(940, 640)  # its room inside the parents' area at 1280 x 800
    dialog.show()  # the page itself may scroll, the preview must not
    try:
        qapp.processEvents()
        assert len(dialog.preview.rows) == 3
        assert dialog.preview.height() >= dialog.preview.sizeHint().height()
        page_scroll = next(s for s in dialog.findChildren(QScrollArea) if s.parent() is dialog)
        content = page_scroll.widget()
        # No widget between the preview and the scrolled page content cuts it off.
        widget = dialog.preview.parentWidget()
        while widget is not content:
            shown = widget.rect()
            corner = dialog.preview.mapTo(widget, dialog.preview.rect().topLeft())
            assert shown.contains(corner) and shown.contains(
                corner + dialog.preview.rect().bottomRight()), widget
            widget = widget.parentWidget()
        # The page's own scroll area is the only one around the preview.
        around = [s for s in dialog.findChildren(QScrollArea) if s.isAncestorOf(dialog.preview)]
        assert around == [page_scroll]
    finally:
        dialog.close()


def test_the_cue_switch_title_does_not_break_inside_cue_punkte(qapp, tmp_path, clock):
    from PySide6.QtWidgets import QLabel

    dialog, _ = make(qapp, tmp_path, clock)
    title = next(w for w in dialog.findChildren(QLabel) if "Cue" in w.text() and "mitschreiben" in w.text())
    # The words are joined so that a narrow column breaks before "Cue-Punkte", not after "Cue-".
    assert title.text().replace(WORD_JOINER, "") == "Marker als Cue-Punkte mitschreiben"
    from PySide6.QtGui import QTextLayout

    width = title.fontMetrics().horizontalAdvance("Marker als Cue-")
    layout = QTextLayout(title.text(), title.font())
    layout.beginLayout()
    lines = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width + 4)
        lines.append(title.text()[line.textStart():line.textStart() + line.textLength()])
    layout.endLayout()
    assert not any(part.rstrip().endswith("Cue-") for part in lines), lines


def test_the_erweitert_page_names_the_cue_switch_the_same_way(qapp, tmp_path, clock):
    from PySide6.QtWidgets import QLabel

    from loopstation.gui.advanced_page import AdvancedPage

    controller, _ = session(tmp_path, clock)
    page = AdvancedPage(controller, export_dir=tmp_path / "out")
    titles = [w.text() for w in page.findChildren(QLabel) if "mitschreiben" in w.text()]
    assert titles == [f"Marker als Cue-{WORD_JOINER}Punkte mitschreiben"]
