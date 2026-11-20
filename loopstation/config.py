"""Settings loaded from a small, commented ``settings.toml``."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_NAME = "settings.toml"

# Time signatures and the beats one bar holds (the session grid is one bar;
# 6/8 counts two dotted-quarter beats).
SIGNATURES: dict[str, int] = {"2/4": 2, "3/4": 3, "4/4": 4, "6/8": 2}


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
    # Cut recordings to the length of the first loop and keep loops in time.
    loop_sync: bool = True
    # Microphone plus speaker delay in ms; None ("auto") = what PortAudio reports.
    latency_ms: float | None = None
    # Relative paths are resolved against the current working directory.
    data_dir: Path = Path(".")
    # --- Loop seam (W1-NAHT) ---
    # Fade the first and last few milliseconds of every loop so it does not click.
    soft_seam: bool = True
    # Level chain: master volume (linear gain 0..1, never above the ceiling),
    # the parents' ceiling in dB(FS), microphone trim in dB, auto gain, peak meter.
    volume: float = 0.5
    max_level_db: float = -6.0
    input_gain_db: float = 0.0
    auto_gain: bool = False
    peak_meter: bool = True
    # --- Onset grid (W2-ONSET-GRID) ---
    # Off = the length of the first recording is the bar, as before. On = the
    # first recording starts at its first reliable onset and may take its bar
    # from the onset distances. Off until it has been tried with children's material.
    auto_grid: bool = False
    # Time signature of the session grid ("4/4": one bar = 4 beats), see ``SIGNATURES``.
    time_signature: str = "4/4"
    # Tempo window for a grid from onset distances (BPM of one beat).
    grid_bpm_min: float = 40.0
    grid_bpm_max: float = 200.0
    # --- Devices and audio system (W2-GERAETE-LIVE) ---
    # Saved by name, never by index. "" = system default of the audio system;
    # audio_hostapi "" = the default of the platform (Windows: WASAPI, Linux: ALSA).
    input_device: str = ""
    output_device: str = ""
    audio_hostapi: str = ""
    # Windows only: load the PortAudio build with ASIO (needs a restart).
    asio: bool = False
    # --- Stretch into the grid (W3-STRETCH-INT) ---
    # A recording on the grid that is within 10 % of a whole number of loops is
    # stretched to exactly that length instead of padded or cut.
    stretch_to_grid: bool = True
    # --- Metronome (W3-ERWEITERT) ---
    # A quiet tick on every beat of the session grid, through the master and
    # its ceiling. The child's page only ever shows the pulse.
    metronome_tone: bool = False
    # Level of the tick in dB(FS) before the master volume (kept quiet on purpose).
    metronome_level_db: float = -20.0
    # --- Free pad mode (W4-FREI) ---
    # A loop on a free pad keeps its own length. On: it still begins on the next
    # loop start of the other loops, so it falls in without losing length. Off:
    # it begins at once.
    free_pad_on_grid: bool = False
    # --- Markers (W4-MARKER) ---
    # An exported single loop carries its markers as WAV cue points (or as a
    # ``.markers.json`` next to it when the cue chunks cannot be written).
    export_cue_points: bool = True

    @property
    def beats_per_bar(self) -> int:
        return SIGNATURES[self.time_signature]

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


def _check_text(source: str, key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{source}: Schlüssel '{key}' muss ein Text sein, ist aber {value!r}")
    return value.strip()


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
    for key in ("sound_effects", "fullscreen", "launchpad", "loop_sync"):
        if key in raw:
            values[key] = _check_bool(source, key, raw[key])
    if "latency_ms" in raw and raw["latency_ms"] != "auto":
        if isinstance(raw["latency_ms"], str):
            raise ConfigError(
                f"{source}: Schlüssel 'latency_ms' muss \"auto\" oder eine Zahl von 0 bis 1000 sein, "
                f"ist aber {raw['latency_ms']!r}"
            )
        values["latency_ms"] = _check_float(source, "latency_ms", raw["latency_ms"], 0, 1000)
    if "data_dir" in raw:
        values["data_dir"] = Path(_check_str(source, "data_dir", raw["data_dir"]))
    # --- Loop seam (W1-NAHT) ---
    if "soft_seam" in raw:
        values["soft_seam"] = _check_bool(source, "soft_seam", raw["soft_seam"])
    # Level chain (volume, ceiling, trim, auto gain, peak meter).
    if "volume" in raw:
        values["volume"] = _check_float(source, "volume", raw["volume"], 0, 1)
    if "max_level_db" in raw:
        values["max_level_db"] = _check_float(source, "max_level_db", raw["max_level_db"], -30, 0)
    if "input_gain_db" in raw:
        values["input_gain_db"] = _check_float(source, "input_gain_db", raw["input_gain_db"], -24, 24)
    for key in ("auto_gain", "peak_meter"):
        if key in raw:
            values[key] = _check_bool(source, key, raw[key])
    # Onset grid (W2-ONSET-GRID).
    if "auto_grid" in raw:
        values["auto_grid"] = _check_bool(source, "auto_grid", raw["auto_grid"])
    if "time_signature" in raw:
        if raw["time_signature"] not in SIGNATURES:
            raise ConfigError(
                f"{source}: Schlüssel 'time_signature' muss einer der Werte "
                f"{', '.join(SIGNATURES)} sein, ist aber {raw['time_signature']!r}"
            )
        values["time_signature"] = raw["time_signature"]
    for key in ("grid_bpm_min", "grid_bpm_max"):
        if key in raw:
            values[key] = _check_float(source, key, raw[key], 20, 300)
    if values.get("grid_bpm_min", Settings.grid_bpm_min) > values.get("grid_bpm_max", Settings.grid_bpm_max):
        raise ConfigError(f"{source}: 'grid_bpm_min' darf nicht größer sein als 'grid_bpm_max'")
    # Devices and audio system (empty text = system default).
    for key in ("input_device", "output_device", "audio_hostapi"):
        if key in raw:
            values[key] = _check_text(source, key, raw[key])
    if "asio" in raw:
        values["asio"] = _check_bool(source, "asio", raw["asio"])
    # Stretch into the grid (W3-STRETCH-INT).
    if "stretch_to_grid" in raw:
        values["stretch_to_grid"] = _check_bool(source, "stretch_to_grid", raw["stretch_to_grid"])
    # Metronome (W3-ERWEITERT).
    if "metronome_tone" in raw:
        values["metronome_tone"] = _check_bool(source, "metronome_tone", raw["metronome_tone"])
    if "metronome_level_db" in raw:
        values["metronome_level_db"] = _check_float(
            source, "metronome_level_db", raw["metronome_level_db"], -40, -6
        )
    # Free pad mode (W4-FREI).
    if "free_pad_on_grid" in raw:
        values["free_pad_on_grid"] = _check_bool(source, "free_pad_on_grid", raw["free_pad_on_grid"])
    # Markers (W4-MARKER).
    if "export_cue_points" in raw:
        values["export_cue_points"] = _check_bool(source, "export_cue_points", raw["export_cue_points"])
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


# ---------------------------------------------------------------- writing
#
# The settings page writes ``settings.toml`` back. Instead of a TOML library
# the file is edited line by line: the value of a known key is replaced in
# place, every comment stays, and a key the file does not have yet is appended
# with its comment from ``SETTING_COMMENTS``. Values are scalars, so this is
# exact. A later package adds a setting by giving ``Settings`` a field, a
# check in ``parse_settings``, one entry in ``SETTING_COMMENTS`` (and in
# ``RESTART_KEYS`` if it only takes effect after a restart).

# Keys that only take effect after a restart: the pad grid, the audio format
# and the data folder are fixed once the window, the store and the audio
# engine exist. Every other key is applied while the app runs.
RESTART_KEYS = ("rows", "cols", "sample_rate", "data_dir", "asio")

# Comment written above a key that the file does not contain yet.
SETTING_COMMENTS: dict[str, str] = {
    "rows": "Zeilen des Pad-Rasters (1 bis 16). Wirkt erst nach einem Neustart.",
    "cols": "Spalten des Pad-Rasters (1 bis 16). Wirkt erst nach einem Neustart.",
    "max_record_seconds": "Längste Aufnahme in Sekunden (1 bis 120). Wirkt sofort.",
    "sample_rate": "Abtastrate für Aufnahme und Wiedergabe in Hz. Wirkt erst nach einem Neustart.",
    "sound_effects": "Kurzer Piepton beim Start und Ende einer Aufnahme. Wirkt sofort.",
    "fullscreen": "true = Vollbild ohne Fensterrahmen, false = maximiertes Fenster. Wirkt sofort.",
    "launchpad": "Novation Launchpad automatisch suchen und benutzen. Wirkt sofort.",
    "loop_sync": "Taktgenauer Schnitt der Loops (true) oder jede Aufnahme mit eigener Länge (false). "
                 "Wirkt sofort.",
    "latency_ms": "Verzögerung zwischen Lautsprecher und Mikrofon in Millisekunden (0 bis 1000) "
                  'oder "auto". Wirkt sofort.',
    "soft_seam": "Loop-Naht weich ein- und ausblenden (true) oder harter Sprung (false). Wirkt sofort.",
    "volume": "Lautstärke von 0 (still) bis 1, immer unter der Obergrenze. Wirkt sofort.",
    "max_level_db": "Obergrenze der Ausgabe in dB(FS) von -30 bis 0. Wirkt sofort.",
    "input_gain_db": "Mikrofonpegel in dB von -24 bis 24 (0 = unverändert). Wirkt sofort.",
    "auto_gain": "true = der Aufnahmepegel wird langsam ausgeglichen. Wirkt sofort.",
    "peak_meter": "true = Pegelanzeige bei der Aufnahme (Balken am Pad, Skala bei den Eltern). "
                  "Wirkt sofort.",
    "auto_grid": "true = die erste Aufnahme beginnt beim ersten Schlag und kann den Takt aus dem "
                 "Abstand der Schläge bekommen, false = die Aufnahmelänge ist der Takt. Wirkt sofort.",
    "time_signature": "Taktart der Sitzung: 2/4, 3/4, 4/4 oder 6/8. Wirkt bei der nächsten ersten Aufnahme.",
    "grid_bpm_min": "Langsamstes Tempo für einen Takt aus Schlägen in BPM (20 bis 300). Wirkt sofort.",
    "grid_bpm_max": "Schnellstes Tempo für einen Takt aus Schlägen in BPM (20 bis 300). Wirkt sofort.",
    "input_device": 'Aufnahmegerät (Name wie in der Liste), "" = Systemstandard. Wirkt sofort.',
    "output_device": 'Wiedergabegerät (Name wie in der Liste), "" = Systemstandard. Wirkt sofort.',
    "audio_hostapi": 'Audio-System (z. B. "Windows WASAPI", "ALSA"), "" = Standard der Plattform. '
                     "Wirkt sofort.",
    "asio": "Nur Windows: ASIO-Treiber zulassen (für Audio-Interfaces, oft exklusiv). "
            "Wirkt erst nach einem Neustart.",
    "stretch_to_grid": "true = eine Aufnahme knapp neben einem ganzen Takt wird weich auf den Takt gezogen, "
                       "false = immer mit Stille aufgefüllt oder geschnitten. Wirkt sofort.",
    "metronome_tone": "true = leiser Metronom-Ton auf jedem Schlag des Takts (nur im Elternbereich "
                      "einzustellen, das Kind sieht nur den Puls). Wirkt sofort.",
    "metronome_level_db": "Pegel des Metronom-Tons in dB(FS) von -40 bis -6, vor Lautstärke und "
                          "Obergrenze. Wirkt sofort.",
    "free_pad_on_grid": "true = ein Loop auf einem freien Pad beginnt am nächsten Loop-Anfang der anderen "
                        "Loops und behält seine eigene Länge, false = er beginnt sofort. Wirkt sofort.",
    "export_cue_points": "true = ein einzeln gesicherter Loop bekommt seine Marker als Cue-Punkte in die "
                         "WAV-Datei (oder als .markers.json daneben). Wirkt sofort.",
    "data_dir": "Ordner für die Daten (relativ zum Startordner). Wirkt erst nach einem Neustart.",
}


def restart_keys_changed(old: Settings, new: Settings) -> list[str]:
    """Keys in ``RESTART_KEYS`` whose value differs: they only act after a restart."""
    return [key for key in RESTART_KEYS if getattr(old, key) != getattr(new, key)]


def resolve_config_path(path: Path | None = None) -> Path:
    """Absolute path of the active ``settings.toml``, whether or not it exists yet.

    ``--config`` (``path``) wins; otherwise it is ``settings.toml`` in the
    working directory, which for the installed app is the folder in
    ``%LOCALAPPDATA%``. Call it before the working directory changes.
    """
    return (path if path is not None else Path(DEFAULT_CONFIG_NAME)).resolve()


def format_toml_value(key: str, value: Any) -> str:
    """The TOML text of one setting value (the inverse of what ``parse_settings`` reads)."""
    if key == "latency_ms" and value is None:
        return '"auto"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        value = value.as_posix()
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else repr(value)
    return str(value)


def settings_values(settings: Settings) -> dict[str, Any]:
    """All settings as the plain values that go into the file."""
    return {f.name: getattr(settings, f.name) for f in fields(Settings)}


# ``key = value`` at the start of a line; the value is a quoted string or a bare
# token, followed by whatever (a trailing comment) the line already had.
_ASSIGNMENT = re.compile(
    r'^(?P<head>(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*=\s*)'
    r'(?P<value>"(?:[^"\\]|\\.)*"|[^\s#]+)(?P<tail>.*)$'
)


def render_settings_text(text: str, settings: Settings) -> str:
    """``text`` (an existing settings file, may be empty) with every value set from ``settings``."""
    values = settings_values(settings)
    seen: set[str] = set()
    lines = []
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if match and match["key"] in values and match["key"] not in seen:
            key = match["key"]
            seen.add(key)
            line = f"{match['head']}{format_toml_value(key, values[key])}{match['tail']}"
        lines.append(line)
    missing = [key for key in values if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        for key in missing:
            comment = SETTING_COMMENTS.get(key)
            if comment:
                lines.append(f"# {comment}")
            lines.append(f"{key} = {format_toml_value(key, values[key])}")
            lines.append("")
        lines.pop()
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` atomically (temp file, fsync, rename)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_settings(path: Path, settings: Settings, template: str | None = None) -> None:
    """Write ``settings`` to ``path``, keeping the comments of the file already there.

    Without a file, ``template`` (the commented default file) is the starting
    point, so a new file is as readable as the shipped one.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = template or ""
    rendered = render_settings_text(text, settings)
    # Never write what the loader would refuse.
    try:
        parse_settings(tomllib.loads(rendered), str(path))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: ungültiges TOML ({exc})") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, rendered)
