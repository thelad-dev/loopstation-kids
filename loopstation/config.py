"""Settings loaded from a small, commented ``settings.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAME = "settings.toml"


class ConfigError(ValueError):
    """Invalid configuration; the message names the file and the key."""


@dataclass(frozen=True)
class Settings:
    rows: int = 3
    cols: int = 4
    max_record_seconds: float = 10.0
    sample_rate: int = 44100
    sound_effects: bool = True
    fullscreen: bool = False
    launchpad: bool = True
    # Relative paths are resolved against the current working directory.
    data_dir: Path = Path(".")

    @property
    def pad_count(self) -> int:
        return self.rows * self.cols

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "data"


def _check_int(source: str, key: str, value: Any, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ConfigError(
            f"{source}: Schlüssel '{key}' muss eine ganze Zahl von {low} bis {high} sein, "
            f"ist aber {value!r}"
        )
    return value


def _check_float(source: str, key: str, value: Any, low: float, high: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not low <= value <= high:
        raise ConfigError(
            f"{source}: Schlüssel '{key}' muss eine Zahl von {low:g} bis {high:g} sein, "
            f"ist aber {value!r}"
        )
    return float(value)


def _check_bool(source: str, key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{source}: Schlüssel '{key}' muss true oder false sein, ist aber {value!r}")
    return value


def _check_str(source: str, key: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: Schlüssel '{key}' muss ein nicht leerer Text sein, ist aber {value!r}")
    return value


def parse_settings(raw: dict[str, Any], source: str = DEFAULT_CONFIG_NAME) -> Settings:
    """Validate a parsed TOML table and build ``Settings`` (defaults for missing keys)."""
    known = {f.name for f in fields(Settings)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"{source}: unbekannter Schlüssel '{unknown[0]}'")

    values: dict[str, Any] = {}
    if "rows" in raw:
        values["rows"] = _check_int(source, "rows", raw["rows"], 1, 16)
    if "cols" in raw:
        values["cols"] = _check_int(source, "cols", raw["cols"], 1, 16)
    if "max_record_seconds" in raw:
        values["max_record_seconds"] = _check_float(
            source, "max_record_seconds", raw["max_record_seconds"], 1, 120
        )
    if "sample_rate" in raw:
        values["sample_rate"] = _check_int(source, "sample_rate", raw["sample_rate"], 8000, 192000)
    for key in ("sound_effects", "fullscreen", "launchpad"):
        if key in raw:
            values[key] = _check_bool(source, key, raw[key])
    if "data_dir" in raw:
        values["data_dir"] = Path(_check_str(source, "data_dir", raw["data_dir"]))
    return Settings(**values)


def load_settings(path: Path | None = None) -> Settings:
    """Load settings.

    ``path`` given: the file must exist. ``path`` omitted: ``settings.toml`` in
    the working directory is used if present, otherwise the defaults.
    """
    if path is None:
        path = Path(DEFAULT_CONFIG_NAME)
        if not path.exists():
            return Settings()
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: Datei nicht gefunden") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: ungültiges TOML ({exc})") from exc
    return parse_settings(raw, str(path))
