"""The installed Qt binding must not leak references to None (Python 3.11 only).

PySide6 6.12.0 frees one reference to None too many on every Qt call without a return value
under Python 3.11. None is not immortal there, so the main window dies after a few dozen frames
with "Fatal Python error: none_dealloc". Since Python 3.12 None is immortal and the count is
meaningless, so the test is skipped there.

The check runs in a child process: the real main window is drawn offscreen many times and plain
void Qt calls are made, and the child reports the reference count of None before and after.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FRAMES = 40
VOID_CALLS = 2000

CHILD = textwrap.dedent(
    f"""
    import sys, tempfile
    from pathlib import Path
    sys.path.insert(0, {str(ROOT / "tests")!r})
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication([])
    from conftest import FakeAudio, FakeClock, make_settings
    from loopstation.controller import Controller
    from loopstation.gui.main_window import MainWindow
    from loopstation.store import EventStore

    tmp = Path(tempfile.mkdtemp())
    clock = FakeClock()
    settings = make_settings(tmp / "live")
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    window = MainWindow(controller, None, [], config_path=tmp / "settings.toml")
    window.timer.stop()
    window.resize(1280, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    app.processEvents()

    before = sys.getrefcount(None)
    for _ in range({FRAMES}):
        window._tick()
        window.repaint()
        app.processEvents()
    for _ in range({VOID_CALLS}):
        window.update()
        window.setEnabled(True)
    after = sys.getrefcount(None)
    print("None refcount", before, after, flush=True)
    window.close()
    store.close()
    """
)


@pytest.mark.skipif(sys.version_info >= (3, 12), reason="None is immortal since Python 3.12")
def test_drawing_the_window_and_void_qt_calls_keep_the_references_to_none(tmp_path):
    script = tmp_path / "none_refcount.py"
    script.write_text(CHILD, encoding="utf-8")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-2000:])
    line = next(row for row in done.stdout.splitlines() if row.startswith("None refcount"))
    before, after = (int(value) for value in line.split()[2:])
    # A leaking binding loses at least one reference per void call (thousands here); normal
    # bookkeeping moves the count by a handful at most.
    assert before - after < 100, f"lost {before - after} references to None"


GC_CHILD = textwrap.dedent(
    f"""
    import gc, sys, tempfile
    from pathlib import Path
    sys.path.insert(0, {str(ROOT / "tests")!r})
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from conftest import FakeAudio, FakeClock, make_settings
    from loopstation.controller import Controller
    from loopstation.gui.advanced_page import AdvancedPage
    from loopstation.store import EventStore

    tmp = Path(tempfile.mkdtemp())
    clock = FakeClock()
    settings = make_settings(tmp / "live")
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    controller.startup()
    for _ in range(3):
        page = AdvancedPage(controller, None)
        del page
        gc.collect()
    print("collected", flush=True)
    store.close()
    """
)


def test_a_dropped_loop_page_is_collected_without_a_crash(tmp_path):
    """PySide6 before 6.12 crashes when the garbage collector clears a cycle through a widget; the
    loop page holds itself only weakly, so dropping it frees it at once and nothing is left to clear."""
    script = tmp_path / "gc_loop_page.py"
    script.write_text(GC_CHILD, encoding="utf-8")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-2000:])
    assert "collected" in done.stdout
