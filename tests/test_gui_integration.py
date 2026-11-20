"""Integration checks of the whole GUI (offscreen): thin child page, 1024 px, scroll bars, clean shutdown."""

from __future__ import annotations

import gc
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import FakeAudio, make_settings
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMenuBar,
    QScrollArea,
    QSpinBox,
    QWidget,
)

from loopstation.controller import Controller, Mode
from loopstation.gui.advanced_page import AdvancedDialog
from loopstation.gui.export_dialog import ExportDialog
from loopstation.gui.history_dialog import HistoryDialog
from loopstation.gui.main_window import MainWindow
from loopstation.gui.parent_gate import ParentEntryButton, ParentGate
from loopstation.gui.sets_page import SetsDialog
from loopstation.gui.settings_page import SettingsDialog
from loopstation.gui.volume_slider import VolumeSlider
from loopstation.gui.widgets import DARK_SCROLLBAR_QSS
from loopstation.session import SetSession
from loopstation.store import EventStore

REPO = Path(__file__).resolve().parent.parent
MIN_WINDOW_WIDTH = 1024


class World:
    """A window on a controller with fake audio and a sets session, and every parents' page."""

    def __init__(self, tmp_path, clock, **overrides):
        overrides.setdefault("auto_grid", True)
        self.settings = make_settings(tmp_path / "live", **overrides)
        self.audio = FakeAudio(clock)
        self.audio.clap_times = [0.5, 1.0]
        self.store = EventStore(self.settings.log_dir, self.settings.pad_count, clock=clock)
        self.clock = clock
        self.controller = Controller(self.store, self.audio, self.settings, clock=clock)
        self.controller.startup()
        self.config = tmp_path / "settings.toml"
        self.config.write_text("# test\nvolume = 0.5\n", encoding="utf-8")
        self.session = SetSession(self.controller, self.config, clock=clock, sets_folder=tmp_path / "sets")
        self.window = MainWindow(self.controller, None, [], config_path=self.config, set_session=self.session)

    def record(self, pad: int, seconds: float = 1.0) -> None:
        self.controller.press(pad)
        self.clock.advance(seconds)
        self.controller.press(pad)

    def parent_pages(self) -> dict[str, QWidget]:
        pages = self.window.parent_pages()
        return {
            "settings": SettingsDialog(self.config, self.controller.settings, self.window.apply_settings,
                                       None, self.window, pages),
            # The areas are widgets of the parents' area; on their own they are top level windows here.
            "advanced": AdvancedDialog(self.controller, None),
            "sets": SetsDialog(self.session, None, None),
            "export": ExportDialog(self.controller, None, export_dir=self.config.parent / "out",
                                   clock=self.clock),
            "history": HistoryDialog(self.controller, 0, self.window),
        }

    def close(self) -> None:
        self.window.timer.stop()
        self.window.close()
        self.store.close()


@pytest.fixture
def world(qapp, tmp_path, clock):
    w = World(tmp_path, clock)
    w.record(0, 3.0)
    w.record(1, 2.0)
    yield w
    w.close()


# --------------------------------------------------------------- 2. the child page stays thin

# What the child may touch (plan 3 and mockups 01-07). "Alle löschen" is not among them: it lives
# only in the parents' area (history page, mockup 12).
CHILD_BUTTONS = {
    "Spielen", "Aufnehmen", "Loop", "Löschen", "Verlauf",
    "Zurück", "Wiederholen", "Alles still",
    "Eltern",  # the small lock tile (mockup 01)
    "\u21b6",  # the back badge of a pad (mockup 05)
}
# Terms the plan gives to the parents' pages: they must not show up as words on the child page.
PARENT_TERMS = re.compile(
    r"BPM|dBFS|\bdB\b|Takt|Taktart|Tempo|Marker|Wellenform|Export|\bSet\b|Sets|Limiter|Trim|Gain|Latenz|"
    r"Ger[aä]t|Mikrofon|Lautsprecher|WAV|MP3|Hz|ASIO|Grid|Onset|Metronom|Einstellung|Eltern(?!-)",
    re.IGNORECASE,
)


# Words of the child page that the vocabulary check would flag but the mockups show on it:
# the lock tile "Eltern" (the way in, held for two seconds) and, painted by the pulse strip, "Puls".
CHILD_WORDS = {"Eltern", "Puls"}


def visible_texts(root: QWidget) -> list[str]:
    texts = [w.text() for w in root.findChildren(QLabel) if w.text()]
    texts += [w.text() for w in root.findChildren(QAbstractButton) if w.text()]
    return texts


def test_the_child_page_has_only_the_allowed_controls(world):
    window = world.window
    window.show()
    QTest.qWaitForWindowExposed(window)
    buttons = {b.text() for b in window.findChildren(QAbstractButton) if b.text()}
    assert buttons == CHILD_BUTTONS
    assert "Alle löschen" not in buttons  # only in the parents' area (history page)
    assert not hasattr(window, "delete_all_button")
    assert len(window.grid.pads) == 12
    # No form controls, no menus, no scrolling: those belong to the parents' pages.
    for kind in (QComboBox, QSpinBox, QLineEdit, QCheckBox, QAbstractScrollArea, QMenuBar):
        assert window.findChildren(kind) == [], kind.__name__
    # The only other custom controls: the volume control and the small lock that opens the gate.
    assert len(window.findChildren(VolumeSlider)) == 1
    assert len(window.findChildren(ParentEntryButton)) == 1
    assert window.menuBar().actions() == []


def test_the_child_page_shows_no_parent_vocabulary_in_any_state(world):
    window, controller, audio = world.window, world.controller, world.audio
    window.show()
    QTest.qWaitForWindowExposed(window)
    states = []

    def check(label: str) -> None:
        window.refresh()
        words = visible_texts(window)
        bad = [t for t in words if t not in CHILD_WORDS and PARENT_TERMS.search(t)]
        assert not bad, f"{label}: {bad}"
        # Numbers belong to the parents too; the pad numbers are painted by the pads themselves.
        assert not [t for t in words if re.search(r"\d", t)], f"{label}: {words}"
        states.append(label)

    check("play")
    for mode in Mode:
        controller.set_mode(mode)
        check(mode.name)
    controller.set_mode(Mode.PLAY)
    controller.press(5)  # recording
    world.clock.advance(2.0)
    audio.input_peak = 0.99
    audio.clips += 1
    check("too loud")
    controller.press(5)
    controller.press_down(1)
    world.clock.advance(0.5)
    check("holding")
    controller.press_up(1)
    controller.stop_all()
    check("all quiet")
    assert len(states) >= 8


def test_the_child_volume_control_names_no_units(world):
    slider = world.window.volume_slider
    assert slider.findChildren(QLabel) == []  # captions (percent, dBFS limit) are for the parents
    assert not slider._captions  # no percent, no dBFS limit text: those are for the parents' copy


def test_the_parents_pages_are_not_reachable_without_the_gate(world):
    window = world.window
    pages = (SettingsDialog, AdvancedDialog, SetsDialog, ExportDialog)
    assert [d for d in window.findChildren(QDialog) if isinstance(d, pages)] == []


# ------------------------------------------------------------------ 3. usable at 1024 px width


def test_the_main_window_fits_1024_px(world):
    assert world.window.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    world.window.resize(MIN_WINDOW_WIDTH, 768)
    world.window.show()
    QTest.qWaitForWindowExposed(world.window)
    window = world.window
    assert window.width() == MIN_WINDOW_WIDTH
    # Nothing cut off: every bar button is as wide as its word needs, all mode buttons equal.
    for button in [*window.mode_buttons.values(), window.undo_button, window.redo_button,
                   window.stop_button]:
        assert button.width() >= button.minimumSizeHint().width() - 1, button.text()
    widths = {b.width() for b in window.mode_buttons.values()}
    assert max(widths) - min(widths) <= 1, widths
    for widget in (*window.mode_buttons.values(), window.volume_slider, window.undo_button,
                   window.redo_button, window.stop_button):
        assert widget.mapTo(window, widget.rect().topLeft()).x() >= 0
        assert widget.mapTo(window, widget.rect().bottomRight()).x() <= MIN_WINDOW_WIDTH


@pytest.mark.parametrize("name", ["settings", "advanced", "sets", "export", "history"])
def test_every_parents_page_fits_1024_px_without_a_sideways_scroll_bar(world, name):
    dialog = world.parent_pages()[name]
    assert dialog.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
    dialog.resize(MIN_WINDOW_WIDTH, 768)
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    QTest.qWait(30)
    if name == "sets":
        dialog.open_tab.click()
        assert dialog.minimumSizeHint().width() <= MIN_WINDOW_WIDTH
        dialog.save_tab.click()
    assert dialog.width() == MIN_WINDOW_WIDTH, f"{name} grew to {dialog.width()} px"
    for area in dialog.findChildren(QScrollArea):
        assert area.horizontalScrollBar().maximum() == 0, f"{name}: sideways scroll bar"
    dialog.close()


def test_the_gate_fits_1024_px(world):
    assert ParentGate(world.window).minimumSizeHint().width() <= MIN_WINDOW_WIDTH


# ------------------------------------------------- 4. dark scroll bars on every scrolling page


def lightest_pixel(widget: QWidget) -> int:
    image = widget.grab().toImage()
    pixels = ((x, y) for x in range(image.width()) for y in range(image.height()))
    return max(image.pixelColor(x, y).lightness() for x, y in pixels)


@pytest.mark.parametrize("name", ["settings", "advanced", "export"])
def test_scroll_bars_are_dark_not_the_white_native_ones(world, name):
    dialog = world.parent_pages()[name]
    dialog.resize(MIN_WINDOW_WIDTH, 360)  # short, so that every page has something to scroll
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    # Only the areas on show: the other areas of the parents' area sit hidden behind the shown one.
    areas = [a for a in dialog.findChildren(QScrollArea)
             if a.isVisible() and a.verticalScrollBar().maximum() > 0]
    assert areas, f"{name}: nothing to scroll in this state"
    for area in areas:
        bar = area.verticalScrollBar()
        assert bar.isVisible()
        assert bar.width() <= 28  # slim, no arrow buttons
        assert lightest_pixel(bar) < 120, f"{name}: bright pixels in the scroll bar"
    # The style is shared, not a copy per page (the child-sized history list keeps its own, wider bar).
    assert DARK_SCROLLBAR_QSS in dialog.styleSheet()
    dialog.close()


def test_every_scroll_area_in_the_app_is_styled():
    """A new QScrollArea in the GUI needs a scroll bar style: the white native bar is not allowed."""
    for path in sorted((REPO / "loopstation" / "gui").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "QScrollArea()" in text:
            assert "DARK_SCROLLBAR_QSS" in text or "QScrollBar:vertical" in text, path.name


# ---------------------------------------- 5. widgets are freed on time, the process ends cleanly


def test_widget_trees_are_freed_when_the_last_reference_goes(qapp, tmp_path, clock):
    """No reference cycle through a connection keeps a page alive until the interpreter exits.

    Pages that are only torn down at interpreter exit are destroyed in arbitrary order there,
    which aborted the process after a green run.
    """
    w = World(tmp_path, clock)
    w.record(0, 3.0)
    gone: list[str] = []

    def watch(name: str, obj: QObject) -> None:
        obj.destroyed.connect(lambda *_: gone.append(name))

    names = []
    for name, dialog in w.parent_pages().items():
        names.append(name)
        dialog.setParent(None)  # a top level page, as the tests and the app's own dialogs are
        watch(name, dialog)
        if name == "sets":
            dialog.open_tab.click()
        del dialog
    gate = ParentGate()
    watch("gate", gate)
    del gate
    gc.collect()
    qapp.processEvents()
    assert sorted(gone) == sorted([*names, "gate"]), gone

    # The window itself: the controller must not keep it alive through its listeners.
    window = w.window
    watch("window", window)
    window.timer.stop()
    window.close()
    del window
    w.window = None
    gc.collect()
    qapp.processEvents()
    assert "window" in gone
    w.store.close()


APP_SCRIPT = textwrap.dedent(
    """
    import sys, tempfile
    from pathlib import Path
    import loopstation.audio as audio_pkg
    from loopstation import app as app_module
    from loopstation.audio.null_backend import NullAudio
    from loopstation.config import Settings
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    audio_pkg.create_audio = lambda settings: (NullAudio(), None)
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(data_dir=tmp, sample_rate=8000, launchpad=False)
    app = QApplication([])

    def close_modal():
        widget = app.activeModalWidget()
        if widget is not None:
            widget.accept()

    def poke():
        from loopstation.gui.main_window import MainWindow
        window = [w for w in app.topLevelWidgets() if isinstance(w, MainWindow)][0]
        if sys.argv[1] == "dialogs":
            timer = QTimer()
            timer.setInterval(30)
            timer.timeout.connect(close_modal)
            timer.start()

            class Gate(QDialog):
                def exec(self):
                    return QDialog.DialogCode.Accepted

            def every_area(*args):
                from loopstation.gui.settings_page import SettingsDialog

                dialog = SettingsDialog(*args)
                for key in dialog.page_keys:  # history, Erweitert, sets and export are built on a visit
                    dialog.show_page(key)
                return dialog

            window.gate_factory = lambda parent: Gate(parent)
            window.settings_factory = every_area
            window.controller.press(0)
            window.open_history(0)
            for _ in range(2):
                window.open_parent_area()
            timer.stop()
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(300, poke)
    code = app_module.run(settings, tmp / "settings.toml")
    left = [type(w).__name__ for w in app.topLevelWidgets()]
    print("run returned", code, "widgets left", left, flush=True)
    """
)


@pytest.mark.parametrize("mode", ["plain", "dialogs"])
def test_the_app_starts_and_ends_with_exit_code_zero_and_no_widget_left_over(tmp_path, mode):
    """The real ``loopstation.app.run`` (null audio backend, no Launchpad), ended by a timer.

    Before the fix the main window and every dialog opened by the parents outlived the event loop
    and were destroyed at interpreter exit: the process died with SIGABRT or SIGSEGV.
    """
    script = tmp_path / "run_app.py"
    script.write_text(APP_SCRIPT, encoding="utf-8")
    env = {**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(REPO)}
    done = subprocess.run([sys.executable, str(script), mode], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-2000:])
    assert "run returned 0 widgets left []" in done.stdout, done.stdout
