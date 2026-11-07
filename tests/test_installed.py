"""Data folder handling of the installed (bundled) app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loopstation import installed
from loopstation.config import load_settings


def test_user_data_dir_prefers_localappdata(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path / "local"), "APPDATA": str(tmp_path / "roaming")}
    assert installed.user_data_dir(env) == tmp_path / "local" / "Loopstation"


def test_user_data_dir_falls_back_to_appdata_then_xdg(tmp_path: Path) -> None:
    assert installed.user_data_dir({"APPDATA": str(tmp_path)}) == tmp_path / "Loopstation"
    assert installed.user_data_dir({"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "Loopstation"


def test_bundled_settings_is_the_repo_default_and_valid() -> None:
    path = installed.bundled_settings()
    assert path.is_file()
    assert load_settings(path).data_dir == Path(".")


def test_prepare_copies_default_settings_once(tmp_path: Path) -> None:
    default = tmp_path / "default.toml"
    default.write_text("rows = 3\n", encoding="utf-8")
    data_dir = tmp_path / "Loopstation"

    installed.prepare_data_dir(data_dir, default)
    assert (data_dir / "settings.toml").read_text(encoding="utf-8") == "rows = 3\n"

    # A changed settings file survives the next start and a newer default.
    (data_dir / "settings.toml").write_text("rows = 5\n", encoding="utf-8")
    default.write_text("rows = 4\n", encoding="utf-8")
    installed.prepare_data_dir(data_dir, default)
    assert (data_dir / "settings.toml").read_text(encoding="utf-8") == "rows = 5\n"
    assert sorted(p.name for p in data_dir.iterdir()) == ["settings.toml"]


def test_prepare_without_default_only_creates_folder(tmp_path: Path) -> None:
    data_dir = tmp_path / "a" / "Loopstation"
    installed.prepare_data_dir(data_dir, tmp_path / "missing.toml")
    assert data_dir.is_dir()
    assert not (data_dir / "settings.toml").exists()


def test_open_log_appends_and_rotates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installed, "LOG_MAX_BYTES", 10)
    with installed.open_log(tmp_path) as log:
        log.write("first start\n")
    with installed.open_log(tmp_path) as log:
        log.write("second start\n")
    assert (tmp_path / "loopstation.log").read_text(encoding="utf-8") == "second start\n"
    assert (tmp_path / "loopstation.log.1").read_text(encoding="utf-8") == "first start\n"


def test_main_runs_app_in_data_dir_and_logs_without_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    seen: dict[str, object] = {}

    def fake_app_main(argv: list[str] | None) -> int:
        seen["cwd"] = Path.cwd()
        seen["argv"] = argv
        print("hello from the app", file=sys.stderr)
        return 7

    monkeypatch.setattr("loopstation.app.main", fake_app_main)
    log = None
    try:
        assert installed.main(["--config", "x.toml"]) == 7
        log = sys.stderr
    finally:
        if log is not None:
            log.close()

    data_dir = tmp_path / "Loopstation"
    assert seen == {"cwd": data_dir, "argv": ["--config", str(tmp_path / "x.toml")]}
    assert (data_dir / "settings.toml").is_file()
    assert "hello from the app" in (data_dir / "loopstation.log").read_text(encoding="utf-8")
    assert os.path.samefile(Path.cwd(), data_dir)


def test_make_icon_writes_a_multi_size_ico(tmp_path: Path) -> None:
    import importlib.util
    import struct

    from PySide6.QtGui import QGuiApplication, QImage

    script = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "make_icon.py"
    spec = importlib.util.spec_from_file_location("make_icon", script)
    assert spec is not None and spec.loader is not None
    make_icon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_icon)

    _app = QGuiApplication.instance() or QGuiApplication([])
    out = tmp_path / "icon.ico"
    assert make_icon.main([str(out)]) == 0
    data = out.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, len(make_icon.SIZES))
    widths = [data[6 + 16 * i] or 256 for i in range(count)]
    assert widths == sorted(make_icon.SIZES)
    assert not QImage(str(out)).isNull()


def test_config_arg_is_resolved_against_start_folder(tmp_path: Path) -> None:
    absolute = str(tmp_path / "abs.toml")
    relative = installed.absolute_config_arg(["--config", "a.toml"], tmp_path)
    assert relative == ["--config", str(tmp_path / "a.toml")]
    assert installed.absolute_config_arg(["--config=a.toml"], tmp_path) == [f"--config={tmp_path / 'a.toml'}"]
    assert installed.absolute_config_arg(["--config", absolute], Path("/elsewhere")) == ["--config", absolute]
    assert installed.absolute_config_arg([], tmp_path) == []


def test_open_log_keeps_appending_when_rotation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installed, "LOG_MAX_BYTES", 1)
    (tmp_path / "loopstation.log").write_text("old\n", encoding="utf-8")

    def locked(*_args: object) -> None:
        raise PermissionError("in use by the running instance")

    monkeypatch.setattr(installed.os, "replace", locked)
    with installed.open_log(tmp_path) as log:
        log.write("new\n")
    assert (tmp_path / "loopstation.log").read_text(encoding="utf-8") == "old\nnew\n"
