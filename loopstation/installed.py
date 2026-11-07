"""Entry point of the installed app (the Windows build made with PyInstaller).

``python -m loopstation`` works in the folder it is started from. An installed
app cannot do that: the program folder is read-only for normal users and is
replaced by every update. This entry point therefore

- uses a data folder in the user profile (``%LOCALAPPDATA%\\Loopstation``),
- copies the commented default ``settings.toml`` there on first start and never
  overwrites an existing one,
- changes into that folder, so ``settings.toml``, ``samples/`` and ``data/``
  live there and survive updates and uninstalling,
- writes output to ``loopstation.log`` in that folder when the app has no
  console (a windowed exe has ``sys.stderr = None``),

and then runs the normal ``loopstation.app.main``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from loopstation.config import DEFAULT_CONFIG_NAME

APP_DIR_NAME = "Loopstation"
LOG_NAME = "loopstation.log"
# The log is rotated once at start when it is bigger than this.
LOG_MAX_BYTES = 1_000_000


def user_data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Folder for settings, recordings and the event log of the installed app."""
    env = os.environ if environ is None else environ
    for key in ("LOCALAPPDATA", "APPDATA"):
        if env.get(key):
            return Path(env[key]) / APP_DIR_NAME
    # Not Windows: only used when the bundle is tried out on Linux.
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def bundled_settings() -> Path:
    """The commented default ``settings.toml`` shipped with the app."""
    bundle = getattr(sys, "_MEIPASS", None)
    root = Path(bundle) if bundle else Path(__file__).resolve().parent.parent
    return root / DEFAULT_CONFIG_NAME


def prepare_data_dir(data_dir: Path, default_settings: Path) -> None:
    """Create ``data_dir`` and put a copy of ``default_settings`` there if none exists."""
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / DEFAULT_CONFIG_NAME
    if target.exists() or not default_settings.is_file():
        return
    # Copy via a temporary file so a crash never leaves a half-written settings file.
    fd, tmp = tempfile.mkstemp(dir=data_dir, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(default_settings.read_bytes())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def open_log(data_dir: Path) -> TextIO:
    """Open ``loopstation.log`` for appending, keeping one older file as ``.1``."""
    log_path = data_dir / LOG_NAME
    try:
        if log_path.stat().st_size > LOG_MAX_BYTES:
            os.replace(log_path, log_path.with_name(LOG_NAME + ".1"))
    except OSError:
        # Missing, or held open by a running instance (Windows): keep appending.
        pass
    return open(log_path, "a", encoding="utf-8", buffering=1)


def absolute_config_arg(argv: list[str], cwd: Path) -> list[str]:
    """Resolve a relative ``--config`` path against ``cwd`` (the folder the exe was started from)."""
    result = list(argv)
    for index, arg in enumerate(result):
        if arg == "--config" and index + 1 < len(result):
            result[index + 1] = str(cwd / result[index + 1])
        elif arg.startswith("--config="):
            result[index] = "--config=" + str(cwd / arg.removeprefix("--config="))
    return result


def main(argv: list[str] | None = None) -> int:
    args = absolute_config_arg(sys.argv[1:] if argv is None else argv, Path.cwd())
    data_dir = user_data_dir()
    prepare_data_dir(data_dir, bundled_settings())
    os.chdir(data_dir)
    if sys.stderr is None or sys.stdout is None:
        log = open_log(data_dir)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    from loopstation.app import main as app_main

    return app_main(args)
