"""Gentle time stretching for recordings that are almost a whole number of loops long.

``stretch_to_grid`` takes the recorded ``data`` and the loop ``grid`` (frames)
and returns data stretched to exactly ``n * grid`` frames, but only when the
recording is already close to that length (default: within 10 %). Anything
further off returns ``None`` and the caller keeps the hard grid behaviour of
``fit_to_grid`` (pad with silence, cut to a multiple). A single clap in a
standing grid must stay a clap, not become a smeared stretch.

The stretching itself sits behind the ``StretchEngine`` protocol. Two engines
exist: ``RubberBandEngine`` (Rubber Band through the ``pylibrb`` wheel, better
quality, GPL) and ``WsolaEngine`` (built in, always there). ``resolve_engine``
picks one by the ``stretch_engine`` setting and falls back to ``WsolaEngine``
whenever Rubber Band is missing or fails, so a stretch never breaks a recording.

``WsolaEngine`` is the built-in fallback: a simple pitch-preserving WSOLA
(waveform similarity overlap-add) in plain numpy, no native dependency. It is
an honest simple stretch, not Rubber-Band quality: voices can sound slightly
metallic or phasey, which is exactly why the application limit is narrow.
Meant to run once when a recording stops, not inside the audio callback.

``stretch_between_markers`` is the parents' tool (Erweitert): it cuts a loop at
their markers and stretches each piece so every marker lands on a beat line,
with the total length unchanged.
"""

from __future__ import annotations

import functools
import importlib
import logging
import sys
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# Plan section 1.1: apply only for a deviation below 8-10 % of the target.
DEFAULT_MAX_DEVIATION = 0.10


class StretchEngine(Protocol):
    """Anything that can stretch mono float32 ``data`` to exactly ``target`` frames."""

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray: ...


RUBBERBAND_BLOCK = 4096  # frames per study/process call (keeps Rubber Band's buffers from growing)


class WsolaEngine:
    """Pitch-preserving WSOLA stretch (fallback engine, simple quality)."""

    def __init__(self, frame_size: int = 2048, search: int = 512) -> None:
        if frame_size < 8 or frame_size % 2:
            raise ValueError("frame_size must be an even number of at least 8")
        self.frame_size = frame_size
        self.search = search

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray:
        if target <= 0:
            raise ValueError("target must be positive")
        data = np.asarray(data, dtype=np.float32)
        count = len(data)
        if count == target:
            return data
        if count == 0:
            return np.zeros(target, dtype=np.float32)
        frame = min(self.frame_size, max(8, (count // 4) // 2 * 2))
        if count < frame * 2:
            return _resample_tail(data, target)
        search = min(self.search, frame // 2)
        out = self._ola(data, target, frame, search)
        return _exact_length(out, target)

    @staticmethod
    def _ola(data: np.ndarray, target: int, frame: int, search: int) -> np.ndarray:
        hop = frame // 2
        ratio = target / len(data)
        window = np.hanning(frame + 1)[:frame].astype(np.float32)  # periodic: halves sum to 1
        first_window = window.copy()
        first_window[:hop] = 1.0  # nothing overlaps the start, so no fade-in
        # pad so every analysis window (plus search margin) stays inside the signal
        lead = np.zeros(search, np.float32)
        tail = np.zeros(frame + 2 * search, np.float32)
        padded = np.concatenate([lead, data, tail])
        frames = -(-target // hop) + 1
        out = np.zeros(frames * hop + frame, dtype=np.float32)
        previous_end = 0  # where the natural continuation of the last chosen segment starts
        for k in range(frames):
            ideal = int(round(k * hop / ratio))
            if k == 0:
                start = ideal
            else:
                template = padded[previous_end + search : previous_end + search + frame]
                lo = max(0, ideal - search)
                hi = min(len(padded) - frame, ideal + search)
                if hi <= lo:
                    start = min(lo, len(padded) - frame)
                else:
                    segment = padded[lo + search : hi + search + frame]
                    scores = np.correlate(segment, template, mode="valid")
                    start = lo + int(np.argmax(scores))
            chunk = padded[start + search : start + search + frame]
            out[k * hop : k * hop + frame] += chunk * (first_window if k == 0 else window)
            previous_end = start + hop
        return out


class RubberBandEngine:
    """Rubber Band (R3, offline mode) through the ``pylibrb`` wheel.

    Offline mode studies the whole recording first and delivers an exact start and
    length. The result is cut or padded to ``target`` frames if it is off by a
    few, and never louder than the loudest frame of the input, so the master
    ceiling is not approached by the engine. Anything the library raises falls
    back to ``WsolaEngine`` for that one stretch.
    """

    def __init__(self, sample_rate: int = 44100, fallback: StretchEngine | None = None) -> None:
        self.sample_rate = sample_rate
        self.fallback = fallback or WsolaEngine()

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray:
        if target <= 0:
            raise ValueError("target must be positive")
        data = np.asarray(data, dtype=np.float32)
        if len(data) == target:
            return data
        if len(data) == 0:
            return np.zeros(target, dtype=np.float32)
        try:
            out = self._run(data, target)
        except Exception as exc:  # a broken library must not lose the recording
            log.warning("Rubber Band failed (%s), using the simple stretch", exc)
            return self.fallback.stretch(data, target)
        out = _exact_length(out, target)
        peak_in = float(np.max(np.abs(data)))
        peak_out = float(np.max(np.abs(out)))
        if peak_out > peak_in > 0:
            out = out * np.float32(peak_in / peak_out)
        return out

    def _run(self, data: np.ndarray, target: int) -> np.ndarray:
        rb = _import_pylibrb()
        options = rb.Option.PROCESS_OFFLINE | rb.Option.ENGINE_FINER
        stretcher = rb.RubberBandStretcher(self.sample_rate, 1, options, target / len(data), 1.0)
        stretcher.set_max_process_size(RUBBERBAND_BLOCK)
        stretcher.set_expected_input_duration(len(data))
        samples_axis = rb.SAMPLES_AXIS
        audio = np.ascontiguousarray(data.reshape(-1, 1) if samples_axis == 0 else data.reshape(1, -1))
        starts = range(0, len(data), RUBBERBAND_BLOCK)

        def block(start: int) -> np.ndarray:
            end = start + RUBBERBAND_BLOCK
            return np.ascontiguousarray(audio[start:end] if samples_axis == 0 else audio[:, start:end])

        for start in starts:
            stretcher.study(block(start), start + RUBBERBAND_BLOCK >= len(data))
        pieces: list[np.ndarray] = []
        for start in starts:
            stretcher.process(block(start), start + RUBBERBAND_BLOCK >= len(data))
            while stretcher.available() > 0:
                pieces.append(stretcher.retrieve_available())
        while stretcher.available() > 0:
            pieces.append(stretcher.retrieve_available())
        if not pieces:
            raise RuntimeError("no output")
        result = np.concatenate(pieces, axis=samples_axis).reshape(-1)
        return np.nan_to_num(result, copy=False).astype(np.float32, copy=False)


def _import_pylibrb():
    """The ``pylibrb`` module. Rubber Band is never bundled with the Windows installer: the
    installer downloads it on request into a ``rubberband`` folder next to the program, which
    is searched here when the app is frozen. The app itself never uses the network."""
    try:
        return importlib.import_module("pylibrb")
    except ImportError:
        local = Path(sys.executable).parent / "rubberband"
        if not getattr(sys, "frozen", False) or not local.is_dir():
            raise
        sys.path.insert(0, str(local))
        return importlib.import_module("pylibrb")


NOT_INSTALLED = "nicht installiert"


@functools.cache
def rubberband_status() -> tuple[bool, str]:
    """Whether Rubber Band can be used, and a short detail (version, or why not).

    Checked once per run: imports ``pylibrb`` and stretches a few frames, so a
    wheel that is present but cannot load its library counts as unusable. The
    detail is ``NOT_INSTALLED`` when the package is simply not there.
    """
    try:
        pylibrb = _import_pylibrb()
    except ImportError:
        return False, NOT_INSTALLED
    except Exception as exc:  # a broken native library
        return False, f"lässt sich nicht laden: {exc}"
    try:
        probe = np.sin(np.arange(16384, dtype=np.float32) * 0.05)
        RubberBandEngine(44100)._run(probe, 16384 + 512)
    except Exception as exc:
        return False, f"läuft nicht: {exc}"
    return True, f"pylibrb {getattr(pylibrb, '__version__', '?')}"


def rubberband_available() -> bool:
    return rubberband_status()[0]


def resolve_engine(choice: str, sample_rate: int) -> StretchEngine:
    """The engine for the ``stretch_engine`` setting; the simple one whenever Rubber Band cannot run."""
    if choice != "simple" and rubberband_available():
        return RubberBandEngine(sample_rate)
    return WsolaEngine()


def install_hint() -> str:
    """How to add Rubber Band later (it is never loaded without the user's consent)."""
    if sys.platform == "win32":
        return ("Zum Nachinstallieren den Loopstation-Installer erneut ausführen und "
                "„Rubber Band (GPL) herunterladen“ ankreuzen.")
    return ("Zum Nachinstallieren scripts/install-linux.sh erneut aufrufen und der Frage zustimmen "
            "(oder --rubberband), oder „pip install pylibrb“ in der Umgebung der Loopstation.")


def engine_notice(choice: str) -> str:
    """The parents' status line: which engine runs and what is installed, with a hint if not."""
    available, detail = rubberband_status()
    if available:
        status = f"Rubber Band installiert ({detail})"
    elif detail == NOT_INSTALLED:
        status = "Rubber Band nicht installiert"
    else:
        status = f"Rubber Band installiert, aber nicht nutzbar ({detail})"
    if choice == "simple":
        return f"Der einfache Stretch ist gewählt. {status}."
    if available:
        return f"{status}, wird benutzt."
    if choice == "auto":
        return f"{status}, einfache Engine aktiv."
    return f"{status}, einfache Engine aktiv. {install_hint()}"


def _resample_tail(data: np.ndarray, target: int) -> np.ndarray:
    """Inputs too short for overlap-add: plain interpolation (pitch changes, but nothing shorter exists)."""
    positions = np.linspace(0, len(data) - 1, target)
    return np.interp(positions, np.arange(len(data)), data).astype(np.float32)


def _exact_length(data: np.ndarray, target: int) -> np.ndarray:
    if len(data) >= target:
        return np.ascontiguousarray(data[:target], dtype=np.float32)
    out = np.zeros(target, dtype=np.float32)
    out[: len(data)] = data
    return out


def stretch_target(frames: int, grid: int) -> int:
    """Nearest whole number of loops for ``frames`` recorded frames (at least one loop)."""
    if grid <= 0:
        raise ValueError("grid must be positive")
    return max(1, round(frames / grid)) * grid


def within_stretch(frames: int, grid: int, max_deviation: float = DEFAULT_MAX_DEVIATION) -> bool:
    """True if ``frames`` is at most ``max_deviation`` off its ``stretch_target``."""
    target = stretch_target(frames, grid)
    return abs(frames - target) / target <= max_deviation


def stretch_to_grid(
    data: np.ndarray,
    grid: int,
    *,
    max_deviation: float = DEFAULT_MAX_DEVIATION,
    engine: StretchEngine | None = None,
) -> np.ndarray | None:
    """``data`` stretched to the nearest multiple of ``grid``, or ``None`` when it is too far off.

    The deviation is ``abs(len(data) - target) / target``; it must not exceed
    ``max_deviation``. ``None`` means "do not stretch": use ``fit_to_grid``.
    Data that already has the target length is returned as is.
    """
    if len(data) == 0:
        return None
    if not within_stretch(len(data), grid, max_deviation):
        return None
    target = stretch_target(len(data), grid)
    if len(data) == target:
        return data
    result = (engine or WsolaEngine()).stretch(data, target)
    if len(result) != target:
        raise ValueError(f"engine returned {len(result)} frames, expected {target}")
    return result


class MarkerStretchError(ValueError):
    """Stretching between markers is not possible; ``reason`` says why.

    ``too_far`` (a segment is off its beat by more than the limit), ``same_beat``
    (two markers snap to one beat line), ``edge`` (a marker snaps to the loop's
    start or end) or ``no_markers``.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def marker_targets(markers: list[int], beat_frames: float, frames: int) -> list[int]:
    """Where each marker goes: the nearest beat line (a multiple of ``beat_frames``).

    Markers outside ``0 < marker < frames`` are not markers and are skipped. The
    targets must be strictly increasing and strictly inside the loop, otherwise
    ``MarkerStretchError``.
    """
    if beat_frames <= 0:
        raise ValueError("beat_frames must be positive")
    inside = sorted({m for m in markers if 0 < m < frames})
    if not inside:
        raise MarkerStretchError("no_markers")
    targets = [round(round(m / beat_frames) * beat_frames) for m in inside]
    if targets[0] <= 0 or targets[-1] >= frames:
        raise MarkerStretchError("edge")
    if any(b <= a for a, b in zip(targets, targets[1:], strict=False)):
        raise MarkerStretchError("same_beat")
    return targets


def stretch_between_markers(
    data: np.ndarray,
    markers: list[int],
    beat_frames: float,
    *,
    max_deviation: float = DEFAULT_MAX_DEVIATION,
    engine: StretchEngine | None = None,
) -> tuple[np.ndarray, list[int]]:
    """Move each marker to its beat line by stretching the stretches between them.

    ``data`` is cut at the markers; every piece is stretched to the distance
    between the beat lines its ends move to, so the first and last frame stay
    where they are and the result has exactly ``len(data)`` frames. Returns the
    result and the marker positions in it (the beat lines). Every piece must be
    off by at most ``max_deviation`` of its new length, else nothing is
    stretched (``MarkerStretchError("too_far")``): a marker far from a beat is
    more likely misplaced than meant.
    """
    total = len(data)
    targets = marker_targets(markers, beat_frames, total)
    inside = sorted({m for m in markers if 0 < m < total})
    source = [0, *inside, total]
    target = [0, *targets, total]
    pieces = []
    for (s0, s1), (t0, t1) in zip(
        zip(source, source[1:], strict=False), zip(target, target[1:], strict=False), strict=True
    ):
        want, have = t1 - t0, s1 - s0
        if have != want and abs(have - want) / want > max_deviation:
            raise MarkerStretchError("too_far")
        piece = np.asarray(data[s0:s1], dtype=np.float32)
        pieces.append(piece if have == want else (engine or WsolaEngine()).stretch(piece, want))
    result = np.concatenate(pieces).astype(np.float32, copy=False)
    if len(result) != total:
        raise ValueError(f"stretched to {len(result)} frames, expected {total}")
    return result, targets
