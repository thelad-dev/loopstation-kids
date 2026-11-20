"""Wiring: load settings, open store, audio and MIDI, start the GUI."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from loopstation.config import ConfigError, Settings, load_settings, resolve_config_path

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from loopstation.session import PreparedOpen


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="loopstation", description="Kindgerechte Loopstation")
    parser.add_argument("--config", type=Path, default=None,
                        help="Pfad zur settings.toml (Standard: ./settings.toml, falls vorhanden)")
    return parser.parse_args(argv)


def _default_settings_text() -> str | None:
    """The commented default ``settings.toml`` a new settings file starts from."""
    from loopstation.installed import bundled_settings

    try:
        return bundled_settings().read_text(encoding="utf-8")
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Fehler in den Einstellungen: {exc}", file=sys.stderr)
        return 2
    # The settings page writes back to the file that was loaded (or, if there
    # is none yet, to the place the next start will look for it).
    return run(settings, resolve_config_path(args.config))


def run(settings: Settings, config_path: Path | None = None) -> int:
    """Run the app. Opening a set ends one session and starts the next in the same process.

    The window asks for the swap (``PreparedOpen``) and leaves the event loop;
    the data folders are replaced here, between two sessions, when no store,
    audio engine or controller exists. See ``loopstation.session``.
    """
    # Qt and the hardware layers are imported here so that config errors are
    # reported without loading them.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from loopstation.session import commit_open, recover_swap
    from loopstation.sets import SetError

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Loopstation")
    # Ctrl+C in a terminal and SIGTERM end the app cleanly. Python handles the
    # signal the next time it runs, which the 30 ms GUI timer guarantees.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    def fail(text: str) -> int:
        print(text, file=sys.stderr)
        QMessageBox.critical(None, "Loopstation", text)
        return 1

    # One lock for the whole run: it sits above the folders a swap replaces, so
    # a second instance cannot start in the middle of one.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    guard = QLockFile(str(settings.data_dir / ".session.lock"))
    if not guard.tryLock(100):
        return fail("Die Loopstation läuft schon.")
    try:
        notices: list[str] = []
        retry: tuple[list[str], list[str]] | None = None
        while True:
            finished = recover_swap(settings.data_dir)
            if retry is not None:
                done_notes, failed_notes = retry
                notices = done_notes if finished else failed_notes
                retry = None
            outcome = _run_session(app, settings, config_path, notices, fail)
            if isinstance(outcome, int):
                return outcome
            try:
                commit_open(settings.data_dir, outcome)
                notices = list(outcome.notes)
            except (SetError, OSError) as exc:
                # recover_swap at the top of the loop puts the session back in
                # order; if it rolls the swap forward, the set did open.
                retry = (
                    list(outcome.notes),
                    [f"Das Set konnte nicht geöffnet werden: {exc}"],
                )
    finally:
        guard.unlock()


def _run_session(
    app: QApplication,
    settings: Settings,
    config_path: Path | None,
    notices: list[str],
    fail: Callable[[str], int],
) -> int | PreparedOpen:
    """One session: from opening the store to the end of the event loop.

    Returns the exit code, or the set the parents asked to open.
    """
    from PySide6.QtCore import QLockFile, QTimer

    from loopstation.audio import create_audio
    from loopstation.controller import Controller
    from loopstation.gui.main_window import MainWindow
    from loopstation.midi.launchpad import LaunchpadController, MidoPorts
    from loopstation.session import SetSession
    from loopstation.store import EventStore, StoreCorruptError

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    # Two instances on the same data would interleave the event log.
    lock = QLockFile(str(settings.log_dir / "loopstation.lock"))
    if not lock.tryLock(100):
        return fail("Die Loopstation läuft schon.")

    try:
        store = EventStore(settings.log_dir, settings.pad_count)
    except (StoreCorruptError, OSError) as exc:
        lock.unlock()
        return fail(f"Das Ereignis-Protokoll kann nicht gelesen werden:\n{exc}")

    def make_launchpad(current: Settings) -> LaunchpadController | None:
        if not current.launchpad:
            return None
        return LaunchpadController(MidoPorts, current.rows, current.cols)

    audio, audio_status = create_audio(settings)
    launchpad = make_launchpad(settings)
    controller = Controller(store, audio, settings)
    controller.startup()

    requested: list[PreparedOpen] = []

    def open_set(prepared: PreparedOpen) -> None:
        requested.append(prepared)
        # Leave the event loop once the dialogs that asked have been closed.
        QTimer.singleShot(0, app.quit)

    session = SetSession(controller, config_path)
    session.notices = list(notices)
    window = MainWindow(
        controller, launchpad, [audio_status] if audio_status else [],
        config_path=config_path, launchpad_factory=make_launchpad,
        settings_template=_default_settings_text(),
        set_session=session, on_open_set=open_set,
    )

    finished = False

    def shutdown() -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        controller.shutdown()
        if window.launchpad is not None:
            window.launchpad.close()
        lock.unlock()

    app.aboutToQuit.connect(shutdown)
    if settings.fullscreen:
        window.showFullScreen()
    else:
        window.showMaximized()
    code = app.exec()
    shutdown()
    app.aboutToQuit.disconnect(shutdown)
    window.timer.stop()
    window.close()
    window.deleteLater()
    return requested[-1] if requested else code
