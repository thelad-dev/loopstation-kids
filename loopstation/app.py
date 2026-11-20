"""Wiring: load settings, open store, audio and MIDI, start the GUI."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from loopstation.config import ConfigError, Settings, load_settings, resolve_config_path


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

    def make_launchpad(current: Settings) -> LaunchpadController | None:
        if not current.launchpad:
            return None
        return LaunchpadController(MidoPorts, current.rows, current.cols)

    audio, audio_status = create_audio(settings)
    launchpad = make_launchpad(settings)
    controller = Controller(store, audio, settings)
    controller.startup()

    window = MainWindow(
        controller, launchpad, [audio_status] if audio_status else [],
        config_path=config_path, launchpad_factory=make_launchpad,
        settings_template=_default_settings_text(),
    )

    def shutdown() -> None:
        controller.shutdown()
        if window.launchpad is not None:
            window.launchpad.close()
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
