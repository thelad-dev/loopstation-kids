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
    """Pitch-preserving WSOLA stretch (fallback engine, simple quality).

    Detected attacks (claps, drum hits) land on their stretched position (position x ratio):
    every window that reaches one is placed by it instead of by the similarity search. That holds
    for attacks at least a window apart (2048 frames, about 46 ms at 44.1 kHz); with several in
    reach of one window, only the one nearest its middle is placed exactly, the others can be off
    by up to their distance x the stretch. Attacks too soft or slow to be detected (a swell, a
    hit far under a loud held tone) only get the plain search and can be a few milliseconds off.
    """

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
        energy = np.concatenate([[0.0], np.cumsum(np.square(padded, dtype=np.float64))])
        frames = -(-target // hop) + 1
        anchors = _anchors(_attacks(data, max(16, frame // 32)), frames, hop, ratio, frame, search,
                           len(padded) - frame - search)
        out = np.zeros(frames * hop + frame, dtype=np.float32)
        previous_end = 0  # where the natural continuation of the last chosen segment starts
        for k in range(frames):
            ideal = int(round(k * hop / ratio))
            if anchors[k] is not None:
                start = anchors[k]
            elif k == 0:
                start = ideal
            else:
                start = _best_match(padded, energy, previous_end, ideal, frame, search,
                                    _guide(anchors, k, hop, ideal, search))
            chunk = padded[start + search : start + search + frame]
            out[k * hop : k * hop + frame] += chunk * (first_window if k == 0 else window)
            previous_end = start + hop
        return out


# An attack is a short window at least three times as loud as the average of the stretch before it.
ATTACK_RISE = 3.0
ATTACK_FLOOR = 1e-4  # windows more than 40 dB below the loudest one never count
ATTACK_LOOKBACK = 16  # windows of average before a window (about 23 ms at 44.1 kHz)
ATTACK_GAP = 32  # windows after an attack in which no new one counts: one stretch window (46 ms)
# Windows before an anchored one that share the phase step towards it, as far as the search reaches
# (see ``_guide``).
ANCHOR_LEAD = 8
# Pulls a tie (silence: every candidate scores 0) to the ideal position; far too small to move a real match.
TIE_BREAK = 1e-4


def _attacks(data: np.ndarray, block: int) -> np.ndarray:
    """Frame positions of the attacks (sudden rises in energy) in ``data``, in order.

    Windows of ``block`` frames overlap by three quarters, so an attack is seen whole however it
    falls on the grid; each is compared with the average level before it, so a clap over a held
    tone still counts while the ups and downs of a low tone do not.
    """
    step = max(1, block // 4)
    if len(data) < block:
        return np.zeros(0, dtype=np.int64)
    total = np.concatenate([[0.0], np.cumsum(np.square(data, dtype=np.float64))])
    starts = np.arange(0, len(data) - block + 1, step)
    level = total[starts + block] - total[starts]
    floor = float(level.max()) * ATTACK_FLOOR
    if floor <= 0:
        return np.zeros(0, dtype=np.int64)
    lookback = ATTACK_LOOKBACK * block
    begin = np.maximum(starts - lookback, 0)
    span = np.maximum(starts - begin, 1)
    before = (total[starts] - total[begin]) / span * block
    rising = starts[(level > floor) & (level > ATTACK_RISE * before)]
    positions: list[int] = []
    for start in rising:
        if positions and start - positions[-1] < ATTACK_GAP * block:
            continue  # the same attack seen again (or one too close to be placed on its own)
        around = np.abs(data[start : start + 2 * block])
        positions.append(int(start) + int(np.argmax(around >= 0.5 * around.max())))
    return np.array(positions, dtype=np.int64)


def _anchors(
    attacks: np.ndarray, frames: int, hop: int, ratio: float, frame: int, search: int, last_start: int
) -> list[int | None]:
    """For every output window, the start that puts an attack it can reach on its stretched position.

    ``None`` where no attack is in reach (the similarity search decides). Every window around one
    attack gets its start this way, so they follow on seamlessly and the attack is neither smeared
    nor moved. With two attacks in reach, the one nearer the window's middle wins.
    """
    anchors: list[int | None] = [None] * frames
    for k in range(frames):
        ideal = int(round(k * hop / ratio))
        reach = np.searchsorted(attacks, [ideal - search, ideal + frame + search])
        near = attacks[reach[0] : reach[1]]
        if len(near):
            attack = int(near[np.argmin(np.abs(near - (ideal + hop)))])
            start = int(round(ideal + (attack - ideal) * (1 - ratio)))
            anchors[k] = min(max(start, ideal - search), ideal + search, last_start)
    return anchors


def _guide(anchors: list[int | None], k: int, hop: int, ideal: int, search: int) -> tuple[int, float] | None:
    """Where window ``k`` would start to lead seamlessly into the next anchored window, and its share.

    The anchored window rarely fits the natural continuation; on held tones the whole mismatch
    would land in one splice and the tone would dip there. The ``ANCHOR_LEAD`` windows before it
    and the splice into it take an equal share each: window j before the anchor goes 1/(j+1) of
    the remaining way.
    """
    for ahead in range(1, ANCHOR_LEAD + 1):
        if k + ahead < len(anchors) and anchors[k + ahead] is not None:
            lead_in = anchors[k + ahead] - ahead * hop
            return (lead_in, 1.0 / (ahead + 1)) if abs(lead_in - ideal) <= search else None
    return None


def _similarity(
    padded: np.ndarray,
    energy: np.ndarray,
    template_start: int,
    lo: int,
    segment: np.ndarray,
    frame: int,
    search: int,
) -> np.ndarray:
    """Normalised cross-correlation of the template at ``template_start`` with each candidate."""
    template = padded[template_start + search : template_start + search + frame]
    scores = np.correlate(segment, template, mode="valid").astype(np.float64)
    count = len(scores)
    template_energy = energy[template_start + search + frame] - energy[template_start + search]
    first = lo + search
    candidate_energy = energy[first + frame : first + frame + count] - energy[first : first + count]
    norm = np.sqrt(np.maximum(template_energy * candidate_energy, 0.0))
    quiet = norm <= 1e-9 * frame
    return np.where(quiet, 0.0, scores / np.where(quiet, 1.0, norm))


def _best_match(
    padded: np.ndarray,
    energy: np.ndarray,
    previous_end: int,
    ideal: int,
    frame: int,
    search: int,
    guide: tuple[int, float] | None = None,
) -> int:
    """The start near ``ideal`` that continues the previous window best (normalised cross-correlation).

    Normalising keeps loud candidates from winning on level alone; ``TIE_BREAK`` sends a tie
    (silence) to the ideal position instead of the edge of the search, so nothing drifts.

    With a ``guide`` (start, share) the candidate must also fit the window that leads into an
    anchored one (``_guide``). The misfit to each is measured as an angle (arccos of the
    correlation), and the candidate is chosen that keeps the larger of misfit/share and
    misfit to the guide/(1 - share) smallest: it goes ``share`` of the way, never all of it.
    """
    lo = max(0, ideal - search)
    hi = min(len(padded) - frame, ideal + search)
    if hi <= lo:
        return min(lo, len(padded) - frame)
    segment = padded[lo + search : hi + search + frame]
    scores = _similarity(padded, energy, previous_end, lo, segment, frame, search)
    if guide is not None and 0 <= guide[0] + search <= len(padded) - frame:
        ahead = _similarity(padded, energy, guide[0], lo, segment, frame, search)
        share = guide[1]
        misfit = np.maximum(np.arccos(np.clip(scores, -1.0, 1.0)) / share,
                            np.arccos(np.clip(ahead, -1.0, 1.0)) / (1 - share))
        scores = -misfit
    scores -= TIE_BREAK * np.abs(np.arange(lo, lo + len(scores)) - ideal) / max(search, 1)
    return lo + int(np.argmax(scores))


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
    targets: list[int] | None = None,
) -> tuple[np.ndarray, list[int]]:
    """Move each marker to its beat line by stretching the stretches between them.

    ``data`` is cut at the markers; every piece is stretched to the distance
    between the beat lines its ends move to, so the first and last frame stay
    where they are and the result has exactly ``len(data)`` frames. Returns the
    result and the marker positions in it (the beat lines). Every piece must be
    off by at most ``max_deviation`` of its new length, else nothing is
    stretched (``MarkerStretchError("too_far")``): a marker far from a beat is
    more likely misplaced than meant.

    ``targets`` (one per marker inside the loop, strictly increasing) replaces
    the nearest beat lines: used when the markers were set on a stretched copy
    and are mapped back onto the original, so they keep the copy's beat lines.
    """
    total = len(data)
    inside = sorted({m for m in markers if 0 < m < total})
    if targets is None:
        targets = marker_targets(markers, beat_frames, total)
    elif len(targets) != len(inside) or any(
        b <= a for a, b in zip([0, *targets], [*targets, total], strict=True)
    ):
        raise ValueError("targets must be one strictly increasing position per marker inside the loop")
    source = [0, *inside, total]
    target = [0, *targets, total]
    spans = list(zip(
        zip(source, source[1:], strict=False), zip(target, target[1:], strict=False), strict=True
    ))
    for (s0, s1), (t0, t1) in spans:  # all checked before anything is stretched
        want, have = t1 - t0, s1 - s0
        if have != want and abs(have - want) / want > max_deviation:
            raise MarkerStretchError("too_far")
    pieces = []
    for (s0, s1), (t0, t1) in spans:
        want, have = t1 - t0, s1 - s0
        piece = np.asarray(data[s0:s1], dtype=np.float32)
        pieces.append(piece if have == want else (engine or WsolaEngine()).stretch(piece, want))
    result = np.concatenate(pieces).astype(np.float32, copy=False)
    if len(result) != total:
        raise ValueError(f"stretched to {len(result)} frames, expected {total}")
    return result, targets


def map_back(frames: list[int], anchors: list[list[int]], total: int) -> list[int]:
    """Positions in a stretched loop mapped back onto the loop it was stretched from.

    ``anchors`` are ``[frame_in_original, frame_in_result]`` pairs (both strictly
    increasing, inside ``0 .. total``); the start and end of the loop are fixed
    points. Between the anchors the stretch is taken as linear. That is only
    approximately true: an engine may move an event inside a piece (WSOLA up to
    about its search window), so a position mapped back can be off by that much.
    """
    original = [0, *(int(a[0]) for a in anchors), total]
    stretched = [0, *(int(a[1]) for a in anchors), total]
    return [int(round(v)) for v in np.interp(frames, stretched, original)]
