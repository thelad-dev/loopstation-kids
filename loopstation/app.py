"""Wiring: load settings, open store, audio and MIDI, start the GUI."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from loopstation.config import ConfigError, Settings, load_settings


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="loopstation", description="Kindgerechte Loopstation")
    parser.add_argument("--config", type=Path, default=None,
                        help="Pfad zur settings.toml (Standard: ./settings.toml, falls vorhanden)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Fehler in den Einstellungen: {exc}", file=sys.stderr)
        return 2
    return run(settings)


def run(settings: Settings) -> int:
    # Qt and the hardware layers are imported here so that config errors are
    # reported without loading them.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from loopstation.audio import create_audio
    from loopstation.controller import Controller
    from loopstation.gui.main_window import MainWindow
    from loopstation.midi.launchpad import LaunchpadController, MidoPorts
    from loopstation.store import EventStore, StoreCorruptError

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Loopstation")

    def fail(text: str) -> int:
        print(text, file=sys.stderr)
        QMessageBox.critical(None, "Loopstation", text)
        return 1

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

    audio, audio_status = create_audio(settings)
    launchpad = (
        LaunchpadController(MidoPorts, settings.rows, settings.cols) if settings.launchpad else None
    )
    controller = Controller(store, audio, settings)
    controller.startup()

    window = MainWindow(controller, launchpad, [audio_status] if audio_status else [])

    def shutdown() -> None:
        controller.shutdown()
        if launchpad is not None:
            launchpad.close()
        lock.unlock()

    app.aboutToQuit.connect(shutdown)
    # Ctrl+C in a terminal and SIGTERM end the app cleanly. Python handles the
    # signal the next time it runs, which the 30 ms GUI timer guarantees.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    if settings.fullscreen:
        window.showFullScreen()
    else:
        window.showMaximized()
    return app.exec()
