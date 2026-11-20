"""Sets and the running session: save a copy, tell unsaved changes, swap the session on open.

No Qt in here. The window and ``app.run`` call these functions.

Opening a set replaces the data of the session. The app does that between two
runs of its event loop (``app.run`` builds store, audio, controller and window
anew), so no live object ever points at the old data. The swap itself is
crash safe:

1. ``prepare_open`` extracts and verifies the set into ``<data_dir>/.set-opening``.
   Until then nothing of the session was touched; a damaged or too new set
   fails here.
2. ``commit_open`` (after the old session has been shut down) writes the marker
   ``.set-swap``, moves ``data/``, ``samples/`` and ``set-saved.json`` of the
   session to ``.replaced-*`` and moves the prepared ones into place.
3. ``recover_swap`` runs at every start. A marker means a swap was cut short:
   it is finished from the verified staging folder (roll forward), so the old
   log is never paired with the new samples. Without a marker, leftovers of a
   preparation or of a finished swap are deleted.

``set-saved.json`` holds the fingerprint of the content the last saved or
opened set had; a session whose fingerprint differs has unsaved changes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import tomllib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopstation import events as ev
from loopstation import sets
from loopstation.audio.devices import DeviceRef, resolve_device
from loopstation.sets import SetError, SetManifest
from loopstation.state import AppState, replay

log = logging.getLogger(__name__)

SAVED_NAME = "set-saved.json"
STAGING_NAME = ".set-opening"
MARKER_NAME = ".set-swap"
REPLACED_PREFIX = ".replaced-"
# What a session consists of below its data folder (a folder, a folder, a file).
SESSION_ITEMS = ("data", "samples", SAVED_NAME)

# Keys of the devices in the settings file of a set (``input_device`` and
# ``output_device`` as tables ``{name, hostapi, occurrence}``); the same shape
# ``audio.devices.DeviceRef`` has. A set without them just has nothing to check.
DEVICE_KEYS = {"input": "input_device", "output": "output_device"}


class SessionBusyError(SetError):
    """A set cannot be saved right now (a recording is running)."""


class SetUnsuitableError(SetError):
    """The set is valid but does not fit this Loopstation (pad grid or sample rate)."""


# ------------------------------------------------------------- fingerprint


def content_fingerprint(state: AppState) -> str:
    """Hash of what a set keeps: samples on the pads, their history, undo steps and loop length.

    Loops being switched on or off and snapshots in the log do not count.
    """
    raw = state.to_dict()
    content = {
        "pads": {pad_id: {"sample": pad["sample"], "history": pad["history"]}
                 for pad_id, pad in raw["pads"].items()},
        "undo_stack": raw["undo_stack"],
        "master": raw["master"],
    }
    text = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_saved_fingerprint(data_dir: Path) -> str | None:
    try:
        raw = json.loads((Path(data_dir) / SAVED_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = raw.get("fingerprint") if isinstance(raw, dict) else None
    return value if isinstance(value, str) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_saved_fingerprint(data_dir: Path, fingerprint: str) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    _write_json_atomic(Path(data_dir) / SAVED_NAME, {"fingerprint": fingerprint})


# ------------------------------------------------------------ set listing


@dataclass(frozen=True)
class SetInfo:
    """What the sets page shows about one set, read without opening it."""

    path: Path
    name: str
    manifest: SetManifest | None
    recorded_pads: int = 0
    undo_steps: int = 0
    error: str = ""
    too_new: bool = False
    # Hints about devices of the set this machine does not have (system default is used).
    notes: tuple[str, ...] = ()
    # One short line for the list: what is wrong or missing, empty if nothing.
    short: str = ""

    @property
    def usable(self) -> bool:
        return self.manifest is not None and not self.error


def _log_text(source: Path) -> str:
    if source.is_dir():
        return (source / sets.LOG_MEMBER).read_text(encoding="utf-8")
    with zipfile.ZipFile(source) as archive:
        return archive.read(sets.LOG_MEMBER).decode("utf-8")


def _settings_text(source: Path) -> str | None:
    try:
        if source.is_dir():
            path = source / sets.SETTINGS_NAME
            return path.read_text(encoding="utf-8") if path.is_file() else None
        with zipfile.ZipFile(source) as archive:
            if sets.SETTINGS_NAME in archive.namelist():
                return archive.read(sets.SETTINGS_NAME).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile):
        pass
    return None


def describe_set(source: Path, sd: Any | None = None) -> SetInfo:
    """Read manifest and log of a set; a problem becomes ``error`` instead of an exception."""
    source = Path(source)
    name = source.stem if source.is_file() else source.name
    try:
        manifest = sets.read_manifest(source)
    except sets.SetTooNewError as exc:
        short = (f"Format v{exc.version} – neuere Loopstation nötig" if exc.version
                 else "Neuere Loopstation nötig")
        return SetInfo(source, name, None, error=str(exc), too_new=True, short=short)
    except (SetError, OSError) as exc:
        return SetInfo(source, name, None, error=str(exc), short="Set ist beschädigt")
    try:
        events = [ev.Event.from_json(line) for line in _log_text(source).splitlines() if line.strip()]
        state = replay(events, manifest.pad_count)
    except (OSError, KeyError, ValueError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
        return SetInfo(source, name, manifest, error=f"Das Protokoll im Set ist unlesbar ({exc})",
                       short="Set ist beschädigt")
    recorded = sum(1 for pad in state.pads.values() if pad.sample is not None)
    notes = tuple(device_notes(_settings_text(source), sd))
    return SetInfo(source, name, manifest, recorded_pads=recorded, undo_steps=len(state.undo_stack),
                   notes=notes, short="; ".join(short_note(note) for note in notes))


def list_sets(folder: Path, sd: Any | None = None) -> list[SetInfo]:
    """The sets in ``folder`` (``.loopset`` files and set folders), newest first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = []
    for entry in folder.iterdir():
        if entry.name.startswith("."):
            continue
        if (entry.is_file() and entry.suffix.lower() == sets.SET_SUFFIX) or (
            entry.is_dir() and (entry / sets.MANIFEST_NAME).is_file()
        ):
            found.append(describe_set(entry, sd))
    return sorted(found, key=lambda info: (info.manifest.created_at if info.manifest else "", info.name),
                  reverse=True)


# --------------------------------------------------------------- devices


def short_note(note: str) -> str:
    """``Gerät „Focusrite“ fehlt → Systemstandard`` out of the longer note ``resolve_device`` gives."""
    match = re.search(r"„(.+?)“", note)
    return f"Gerät „{match.group(1)}“ fehlt → Systemstandard" if match else note


def _default_sd() -> Any | None:
    try:
        import sounddevice
    except Exception:  # no PortAudio on this machine
        return None
    return sounddevice


def device_notes(settings_text: str | None, sd: Any | None = None) -> list[str]:
    """Hints for devices of a set's settings that this machine does not have.

    A missing device means the system default is used, which is what
    ``resolve_device`` already says in its note. No settings or no device keys
    give no hints; without PortAudio nothing can be checked.
    """
    if not settings_text:
        return []
    try:
        raw = tomllib.loads(settings_text)
    except tomllib.TOMLDecodeError:
        return []
    refs = []
    for kind, key in DEVICE_KEYS.items():
        entry = raw.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            occurrence = entry.get("occurrence", 0)
            refs.append((kind, DeviceRef(
                entry["name"], str(entry.get("hostapi", "")),
                occurrence if isinstance(occurrence, int) and not isinstance(occurrence, bool) else 0,
            )))
    if not refs:
        return []
    sd = sd if sd is not None else _default_sd()
    if sd is None:
        return []
    notes = []
    for kind, ref in refs:
        try:
            note = resolve_device(sd, ref, kind).note  # type: ignore[arg-type]
        except Exception as exc:  # a broken PortAudio must not stop opening a set
            log.warning("device check for %s failed: %s", ref.name, exc)
            continue
        if note:
            notes.append(note)
    return notes


# ------------------------------------------------------------ open: prepare


@dataclass(frozen=True)
class PreparedOpen:
    """A verified set, extracted and waiting to replace the session."""

    staging: Path
    manifest: SetManifest
    notes: tuple[str, ...]


def prepare_open(
    data_dir: Path,
    source: Path,
    *,
    pad_count: int,
    sample_rate: int,
    sd: Any | None = None,
) -> PreparedOpen:
    """Check ``source`` and extract it next to the session; the session itself stays as it is.

    Raises ``SetTooNewError``, ``SetCorruptError``, ``SetUnsuitableError`` or
    ``SetError``; in every case the running session is untouched.
    """
    data_dir, source = Path(data_dir), Path(source)
    manifest = sets.read_manifest(source)  # version check first: it has the clearest message
    if manifest.pad_count != pad_count:
        raise SetUnsuitableError(
            f"Das Set hat {manifest.pad_count} Pads, diese Loopstation hat {pad_count}."
        )
    if manifest.sample_rate != sample_rate:
        raise SetUnsuitableError(
            f"Das Set wurde mit {manifest.sample_rate} Hz aufgenommen, diese Loopstation läuft mit "
            f"{sample_rate} Hz."
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    staging = data_dir / STAGING_NAME
    shutil.rmtree(staging, ignore_errors=True)
    sets.open_set(source, staging)
    try:
        (staging / "samples").mkdir(exist_ok=True)
        events = [ev.Event.from_json(line)
                  for line in (staging / sets.LOG_MEMBER).read_text(encoding="utf-8").splitlines()
                  if line.strip()]
        write_saved_fingerprint(staging, content_fingerprint(replay(events, pad_count)))
        # The session items sit directly in the staging folder: data/, samples/, set-saved.json.
        settings_file = staging / sets.SETTINGS_NAME
        notes = device_notes(
            settings_file.read_text(encoding="utf-8") if settings_file.is_file() else None, sd)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PreparedOpen(staging, manifest, tuple(notes))


def discard_prepared(prepared: PreparedOpen) -> None:
    shutil.rmtree(prepared.staging, ignore_errors=True)


# ------------------------------------------------------------- open: swap


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with contextlib.suppress(OSError):
            path.unlink()


def _roll_forward(data_dir: Path) -> None:
    """Finish a swap from the staging folder; safe to run again after any interruption."""
    staging = data_dir / STAGING_NAME
    for name in SESSION_ITEMS:
        new, target, old = staging / name, data_dir / name, data_dir / (REPLACED_PREFIX + name)
        if not new.exists():
            continue  # already in place
        if target.exists():
            _remove(old)  # stale from an earlier swap
            os.replace(target, old)
        os.replace(new, target)
    _fsync_dir(data_dir)


def _cleanup(data_dir: Path) -> None:
    _remove(data_dir / STAGING_NAME)
    for name in SESSION_ITEMS:
        _remove(data_dir / (REPLACED_PREFIX + name))
    for name in (MARKER_NAME, MARKER_NAME + ".tmp", SAVED_NAME + ".tmp"):
        with contextlib.suppress(OSError):
            (data_dir / name).unlink()


def commit_open(data_dir: Path, prepared: PreparedOpen) -> None:
    """Replace the session data with the prepared set. The old session must be shut down."""
    data_dir = Path(data_dir)
    if prepared.staging != data_dir / STAGING_NAME or not (prepared.staging / "data").is_dir():
        raise SetError("Das vorbereitete Set ist nicht mehr da")
    _write_json_atomic(data_dir / MARKER_NAME, {"staging": STAGING_NAME})
    _fsync_dir(data_dir)
    _roll_forward(data_dir)
    # The marker goes first: a crash while the old data is removed must not repeat the swap.
    with contextlib.suppress(OSError):
        (data_dir / MARKER_NAME).unlink()
    _cleanup(data_dir)


def recover_swap(data_dir: Path) -> bool:
    """Run at every start, before the store opens. True if a cut-short swap was finished."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return False
    finished = False
    if (data_dir / MARKER_NAME).exists():
        if (data_dir / STAGING_NAME).is_dir():
            log.warning("finishing an interrupted set swap in %s", data_dir)
            _roll_forward(data_dir)
            finished = True
        else:
            log.warning("set swap marker without staging folder in %s", data_dir)
    _cleanup(data_dir)
    return finished


# ------------------------------------------------------------ the session


class SetSession:
    """What the sets page works with: the running controller plus the folder it lives in."""

    def __init__(
        self,
        controller: Any,
        settings_file: Path | None,
        *,
        sd: Any | None = None,
        clock: Callable[[], float] = time.time,
        sets_folder: Path | None = None,
    ) -> None:
        self.controller = controller
        self.settings_file = settings_file
        self.sd = sd
        self._clock = clock
        self.sets_folder = sets_folder if sets_folder is not None else default_sets_folder()
        # Hints from the start of this session (devices the opened set had, a swap that failed);
        # the sets page shows them to the parents.
        self.notices: list[str] = []

    @property
    def data_dir(self) -> Path:
        return Path(self.controller.settings.data_dir)

    # -------------------------------------------------------------- state

    def recording(self) -> bool:
        return self.controller.recording_pad is not None

    def unsaved(self) -> bool:
        """Content on the pads that no saved or opened set has."""
        state = self.controller.store.state
        if not state.has_content():
            return False
        return content_fingerprint(state) != read_saved_fingerprint(self.data_dir)

    def summary(self) -> dict[str, Any]:
        """Numbers for the page "what is in the set"."""
        state = self.controller.store.state
        settings = self.controller.settings
        names = sets.referenced_samples(state)
        present = [n for n in names if (settings.samples_dir / n).is_file()]
        size = sum((settings.samples_dir / n).stat().st_size for n in present)
        return {
            "recorded_pads": sum(1 for pad in state.pads.values() if pad.sample is not None),
            "pad_count": len(state.pads),
            "samples": len(present),
            "undo_steps": len(state.undo_stack),
            "grid": None if state.master is None else dict(state.master),
            "has_settings": self.settings_file is not None and Path(self.settings_file).is_file(),
            "bytes": size,
        }

    # ---------------------------------------------------------------- save

    def save(self, target: Path) -> SetManifest:
        """Write a set of the running session. Refused while a recording runs."""
        if self.recording():
            raise SessionBusyError("Gerade läuft eine Aufnahme. Bitte erst beenden, dann sichern.")
        controller = self.controller
        settings = controller.settings
        manifest = sets.write_set(
            Path(target),
            log_dir=settings.log_dir,
            samples_dir=settings.samples_dir,
            sample_rate=controller.audio.sample_rate,
            pad_count=settings.pad_count,
            settings_file=self.settings_file,
            clock=self._clock,
        )
        write_saved_fingerprint(self.data_dir, content_fingerprint(controller.store.state))
        return manifest

    # ---------------------------------------------------------------- open

    def prepare_open(self, source: Path) -> PreparedOpen:
        if self.recording():
            raise SessionBusyError("Gerade läuft eine Aufnahme. Bitte erst beenden, dann öffnen.")
        return prepare_open(
            self.data_dir, source,
            pad_count=self.controller.settings.pad_count,
            sample_rate=self.controller.audio.sample_rate,
            sd=self.sd,
        )


def default_sets_folder() -> Path:
    """``Dokumente/Loopstation/Sets`` below the user's home (mockups 14 and 15)."""
    home = Path.home()
    documents = home / "Documents"
    if sys.platform == "win32" and not documents.exists():
        documents = home / "Dokumente"
    return documents / "Loopstation" / "Sets"

