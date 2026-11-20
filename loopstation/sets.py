"""Sets: a complete session saved as a folder or a ``.loopset`` ZIP and opened again.

A set is a frozen copy of a session. Folder and ZIP have the same layout::

    manifest.toml       format_version, app_version, created_at, sample_rate,
                        pad_count, grid, payload_bytes, samples, missing_samples
    settings.toml       copy of the settings file (only if one was given)
    data/events.jsonl   the active log from its last snapshot on
    samples/*.wav       exactly the samples the state still refers to

The latest snapshot already carries the full state (current samples, history
and undo stack), so ``replay`` never needs ``data/archive/``; the archive is
therefore not part of a set. Samples are the ones named by the current pads,
their history and the undo stack, and nothing else.

``open_set`` extracts into a work folder that is itself a valid ``data_dir``
(``data/``, ``samples/``, ``settings.toml``), so ``EventStore(work / "data", ...)``
loads the saved state, undo stack included. The redo stack is not persisted
by the store and therefore starts empty.

Format versions: ``FORMAT_VERSION`` is the version this code writes. Newer
sets are refused (``SetTooNewError``). There is no older version yet; when
one exists, the migration from it belongs into ``_check_version``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
import time
import tomllib
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import loopstation
from loopstation import events as ev
from loopstation.state import AppState, replay
from loopstation.store import LOG_NAME

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
SET_SUFFIX = ".loopset"

MANIFEST_NAME = "manifest.toml"
SETTINGS_NAME = "settings.toml"
LOG_MEMBER = f"data/{LOG_NAME}"
SAMPLES_PREFIX = "samples/"


class SetError(Exception):
    """A set could not be written or opened."""


class SetTooNewError(SetError):
    """The set was written by a newer Loopstation."""


class SetCorruptError(SetError):
    """The set is damaged or not a set at all."""


@dataclass(frozen=True)
class SetManifest:
    """The contents of ``manifest.toml``."""

    format_version: int
    app_version: str
    created_at: str
    sample_rate: int
    pad_count: int
    grid: dict[str, int] | None
    payload_bytes: int
    samples: tuple[str, ...]
    missing_samples: tuple[str, ...] = ()


# ---------------------------------------------------------------- references


def valid_sample_name(name: object) -> bool:
    """True for a plain ``*.wav`` file name (no folders, no traversal)."""
    return (
        isinstance(name, str)
        and name.lower().endswith(".wav")
        and name == os.path.basename(name)
        and "/" not in name
        and "\\" not in name
        and "\0" not in name
        and ":" not in name
        and not name.startswith(".")
    )


def referenced_samples(state: AppState) -> set[str]:
    """Every sample the state can still reach: pads, history and undo targets."""
    names: set[str] = set()
    for pad in state.pads.values():
        if pad.sample is not None:
            names.add(pad.sample)
        names.update(pad.history)
    for entry in state.undo_stack:
        names.update(sample for sample in entry["pads"].values() if sample is not None)
    return names


# ------------------------------------------------------------------- writing


def write_set(
    target: Path,
    *,
    log_dir: Path,
    samples_dir: Path,
    sample_rate: int,
    pad_count: int,
    settings_file: Path | None = None,
    clock: Callable[[], float] = time.time,
) -> SetManifest:
    """Write the session as a set; a ``.loopset`` target is a ZIP, anything else a folder.

    The set is built next to ``target`` under a temporary name, flushed to
    disk and then moved into place, so an existing set at ``target`` is
    either replaced completely or left as it was.
    """
    target = Path(target)
    log_bytes, state = _snapshot_of_log(Path(log_dir) / LOG_NAME)
    names = sorted(referenced_samples(state))
    for name in names:
        if not valid_sample_name(name):
            raise SetError(f"Das Protokoll nennt einen ungültigen Sample-Namen: {name!r}")
    samples_dir = Path(samples_dir)
    present = [name for name in names if (samples_dir / name).is_file()]
    missing = tuple(name for name in names if name not in present)
    if missing:
        log.warning("set: %d referenced sample(s) missing on disk: %s", len(missing), ", ".join(missing))

    members: list[tuple[str, bytes | Path]] = []
    settings_path = Path(settings_file) if settings_file is not None else None
    if settings_path is not None and settings_path.is_file():
        members.append((SETTINGS_NAME, settings_path))
    members.append((LOG_MEMBER, log_bytes))
    members.extend((SAMPLES_PREFIX + name, samples_dir / name) for name in present)

    payload = sum(len(src) if isinstance(src, bytes) else src.stat().st_size for _, src in members)
    manifest = SetManifest(
        format_version=FORMAT_VERSION,
        app_version=loopstation.__version__,
        created_at=ev.format_ts(clock()),
        sample_rate=sample_rate,
        pad_count=pad_count,
        grid=None if state.master is None else dict(state.master),
        payload_bytes=payload,
        samples=tuple(present),
        missing_samples=missing,
    )
    members.insert(0, (MANIFEST_NAME, _manifest_to_toml(manifest).encode("utf-8")))

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == SET_SUFFIX:
        _write_zip(target, members)
    else:
        _write_folder(target, members)
    return manifest


def _snapshot_of_log(path: Path) -> tuple[bytes, AppState]:
    """The log from its last snapshot on (as bytes) and the state it yields.

    A torn last line (the store is appending right now) is dropped.
    """
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        raise SetError(f"Das Protokoll {path} lässt sich nicht lesen: {exc}") from exc
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    parsed: list[ev.Event] = []
    for index, line in enumerate(lines):
        try:
            parsed.append(ev.Event.from_json(line))
        except ev.EventFormatError as exc:
            if index == len(lines) - 1:
                lines = lines[:index]
                break
            raise SetError(f"Das Protokoll {path} ist beschädigt (Zeile {index + 1}: {exc})") from exc
    start = next((i for i in range(len(parsed) - 1, -1, -1) if parsed[i].type == ev.SNAPSHOT), None)
    if start is None:
        raise SetError(f"Das Protokoll {path} enthält keinen Snapshot")
    kept = lines[start:]
    state = replay(parsed[start:], 0)
    return ("".join(line + "\n" for line in kept)).encode("utf-8"), state


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def _manifest_to_toml(manifest: SetManifest) -> str:
    def str_list(items: tuple[str, ...]) -> str:
        return "[" + ", ".join(_toml_str(item) for item in items) + "]"

    lines = [
        f"format_version = {manifest.format_version}",
        f"app_version = {_toml_str(manifest.app_version)}",
        f"created_at = {_toml_str(manifest.created_at)}",
        f"sample_rate = {manifest.sample_rate}",
        f"pad_count = {manifest.pad_count}",
        f"payload_bytes = {manifest.payload_bytes}",
        f"samples = {str_list(manifest.samples)}",
        f"missing_samples = {str_list(manifest.missing_samples)}",
    ]
    if manifest.grid is not None:
        lines += ["", "[grid]", f"frames = {manifest.grid['frames']}", f"rate = {manifest.grid['rate']}"]
    return "\n".join(lines) + "\n"


def _fsync_path(path: Path) -> None:
    """Fsync a file, or a directory on POSIX (a rename inside it is then durable)."""
    if path.is_dir() and os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY if path.is_dir() else os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _is_replaceable_folder(path: Path) -> bool:
    """An existing folder may be replaced if it is empty or already a set."""
    return path.is_dir() and (not any(path.iterdir()) or (path / MANIFEST_NAME).is_file())


def _write_folder(target: Path, members: list[tuple[str, bytes | Path]]) -> None:
    if target.exists() and not _is_replaceable_folder(target):
        raise SetError(f"{target} existiert und ist kein Set; es wird nicht überschrieben")
    tmp = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    backup: Path | None = None
    try:
        for arcname, source in members:
            dest = tmp / arcname
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, bytes):
                dest.write_bytes(source)
            else:
                shutil.copyfile(source, dest)
            _fsync_path(dest)
        for folder in {tmp, *(path.parent for path in tmp.rglob("*"))}:
            _fsync_path(folder)
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{target.name}.old-", dir=target.parent))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(tmp, target)
        except BaseException:
            if backup is not None:
                os.replace(backup, target)
                backup = None
            raise
        _fsync_path(target.parent)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def _write_zip(target: Path, members: list[tuple[str, bytes | Path]]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
            for arcname, source in members:
                if isinstance(source, bytes):
                    archive.writestr(arcname, source)
                else:
                    archive.write(source, arcname)
            handle.flush()
        _fsync_path(tmp)
        os.replace(tmp, target)
        _fsync_path(target.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


# ------------------------------------------------------------------- opening


def read_manifest(source: Path) -> SetManifest:
    """Read and check only the manifest of a set (folder or ZIP)."""
    source = Path(source)
    if source.is_dir():
        path = source / MANIFEST_NAME
        if not path.is_file():
            raise SetCorruptError(f"{source} enthält kein {MANIFEST_NAME}")
        return _parse_manifest(path.read_bytes())
    with _open_zip(source) as archive:
        _check_member_names(archive.namelist())
        try:
            return _parse_manifest(archive.read(MANIFEST_NAME))
        except KeyError as exc:
            raise SetCorruptError(f"{source} enthält kein {MANIFEST_NAME}") from exc
        except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, OSError) as exc:
            raise SetCorruptError(f"{source}: {MANIFEST_NAME} ist unlesbar ({exc})") from exc


def open_set(source: Path, work_dir: Path) -> SetManifest:
    """Check a set and extract it into ``work_dir``, which must not hold anything yet.

    Everything is extracted and verified in a temporary folder next to
    ``work_dir`` and moved into place at the end, so a damaged set never
    leaves a half-filled work folder behind.
    """
    source, work_dir = Path(source), Path(work_dir)
    if work_dir.exists() and (not work_dir.is_dir() or any(work_dir.iterdir())):
        raise SetError(f"Der Arbeitsordner {work_dir} ist nicht leer")
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{work_dir.name}.tmp-", dir=work_dir.parent))
    try:
        manifest = _extract_folder(source, tmp) if source.is_dir() else _extract_zip(source, tmp)
        _verify(tmp, manifest)
        if work_dir.exists():
            work_dir.rmdir()
        os.replace(tmp, work_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest


def _open_zip(source: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise SetCorruptError(f"{source} ist kein gültiges Set (ZIP beschädigt)") from exc
    except OSError as exc:
        raise SetError(f"{source} lässt sich nicht öffnen: {exc}") from exc


def _check_member_names(names: list[str]) -> None:
    """Allow only the set layout; refuses traversal, absolute paths and extras."""
    seen: set[str] = set()
    for name in names:
        if name.endswith("/") and name.rstrip("/") in {"data", "samples"}:
            continue
        ok = name in {MANIFEST_NAME, SETTINGS_NAME, LOG_MEMBER} or (
            name.startswith(SAMPLES_PREFIX) and valid_sample_name(name[len(SAMPLES_PREFIX):])
        )
        if not ok:
            raise SetCorruptError(f"Unzulässiger Eintrag im Set: {name!r}")
        if name in seen:
            raise SetCorruptError(f"Eintrag doppelt im Set: {name!r}")
        seen.add(name)


def _extract_zip(source: Path, tmp: Path) -> SetManifest:
    with _open_zip(source) as archive:
        names = archive.namelist()
        _check_member_names(names)
        if MANIFEST_NAME not in names:
            raise SetCorruptError(f"{source} enthält kein {MANIFEST_NAME}")
        try:
            manifest = _parse_manifest(archive.read(MANIFEST_NAME))
            bad = archive.testzip()
            if bad is not None:
                raise SetCorruptError(f"{source}: Eintrag {bad!r} ist beschädigt")
            for name in names:
                if name.endswith("/"):
                    continue
                dest = tmp / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError, OSError, RuntimeError) as exc:
            raise SetCorruptError(f"{source} ist beschädigt ({exc})") from exc
    return manifest


def _extract_folder(source: Path, tmp: Path) -> SetManifest:
    manifest = read_manifest(source)
    samples = (SAMPLES_PREFIX + name for name in manifest.samples)
    members = [MANIFEST_NAME, SETTINGS_NAME, LOG_MEMBER, *samples]
    for name in members:
        if name == SETTINGS_NAME and not (source / name).is_file():
            continue
        src = source / name
        if not src.is_file():
            raise SetCorruptError(f"{source}: {name} fehlt")
        dest = tmp / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return manifest


def _parse_manifest(raw: bytes) -> SetManifest:
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SetCorruptError(f"{MANIFEST_NAME} ist unlesbar ({exc})") from exc
    _check_version(data.get("format_version"))

    def integer(key: str, minimum: int) -> int:
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise SetCorruptError(f"{MANIFEST_NAME}: '{key}' ist ungültig ({value!r})")
        return value

    def text(key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str):
            raise SetCorruptError(f"{MANIFEST_NAME}: '{key}' fehlt oder ist kein Text")
        return value

    def names(key: str, required: bool) -> tuple[str, ...]:
        value: Any = data.get(key, None if required else [])
        if not isinstance(value, list) or not all(valid_sample_name(item) for item in value):
            raise SetCorruptError(f"{MANIFEST_NAME}: '{key}' ist keine Liste gültiger Sample-Namen")
        return tuple(value)

    grid_raw = data.get("grid")
    grid = None
    if grid_raw is not None:
        raw = grid_raw if isinstance(grid_raw, dict) else {}
        frames, rate = raw.get("frames"), raw.get("rate")
        if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (frames, rate)):
            raise SetCorruptError(f"{MANIFEST_NAME}: 'grid' ist ungültig")
        grid = {"frames": frames, "rate": rate}
    return SetManifest(
        format_version=data["format_version"],
        app_version=text("app_version"),
        created_at=text("created_at"),
        sample_rate=integer("sample_rate", 1),
        pad_count=integer("pad_count", 0),
        grid=grid,
        payload_bytes=integer("payload_bytes", 0),
        samples=names("samples", required=True),
        missing_samples=names("missing_samples", required=False),
    )


def _check_version(version: object) -> None:
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SetCorruptError(f"{MANIFEST_NAME}: 'format_version' fehlt oder ist ungültig ({version!r})")
    if version > FORMAT_VERSION:
        raise SetTooNewError(
            f"Dieses Set hat das Format {version}, diese Loopstation kennt nur bis {FORMAT_VERSION}. "
            "Eine neuere Loopstation ist nötig."
        )
    # Versions below FORMAT_VERSION: none exist yet, so there is nothing to migrate.


def _verify(root: Path, manifest: SetManifest) -> None:
    """The extracted set must replay and must hold every sample the state needs."""
    log_path = root / LOG_MEMBER
    if not log_path.is_file():
        raise SetCorruptError(f"Das Set enthält kein Protokoll ({LOG_MEMBER})")
    events: list[ev.Event] = []
    try:
        for number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            event = ev.Event.from_json(line)
            if events and event.seq <= events[-1].seq:
                raise SetCorruptError(f"Protokoll: Zeile {number} hat eine unpassende seq")
            events.append(event)
    except (ev.EventFormatError, UnicodeDecodeError) as exc:
        raise SetCorruptError(f"Das Protokoll im Set ist beschädigt ({exc})") from exc
    if not events or events[0].type != ev.SNAPSHOT:
        raise SetCorruptError("Das Protokoll im Set beginnt nicht mit einem Snapshot")
    state = replay(events, manifest.pad_count)
    for name in sorted(referenced_samples(state)):
        if not valid_sample_name(name):
            raise SetCorruptError(f"Das Protokoll nennt einen ungültigen Sample-Namen: {name!r}")
        if name not in manifest.missing_samples and not (root / SAMPLES_PREFIX / name).is_file():
            raise SetCorruptError(f"Das Sample {name} fehlt im Set")
