"""Export of single loops and of the sum of the running loops as WAV files.

Everything here is pure: no Qt, no audio device, no event store. The parents'
export dialog collects the pads from the controller and calls into this
module; the render itself is deterministic.

The sum uses the same level chain as the live output: all loops are added,
multiplied by the master volume and then kept under the parents' ceiling by
the same ``PeakLimiter``. A looping voice gets the same soft seam as live. The
render is exactly ``bars x grid`` frames long, so loops that are a multiple of
the grid close without a click. There is no time line: every loop starts at
the first frame and repeats unchanged, a loop that does not fit is cut at the
end (plus an optional short fade-out). A free pad keeps its own length (the
controller hands it over unfitted), so it repeats in that length and the render
cuts it off hard at the end like any other loop.

Without a loop grid there is no bar to count. Nothing is guessed then:
``ExportError`` explains it, unless the caller chose the stand-in "bars times
the longest loop", which is written into the file's comment.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import soundfile

from loopstation.audio.dynamics import PeakLimiter, db_to_gain
from loopstation.audio.sync import soften_seam

if TYPE_CHECKING:
    from loopstation.controller import Controller

# Bar counts offered by the dialog; any positive number works.
BAR_CHOICES = (4, 8, 16, 32)
MAX_BARS = 256
# Fade-out at the end: 15 ms, never more than a quarter of one bar.
FADE_OUT_SECONDS = 0.015
FADE_OUT_BAR_FRACTION = 0.25
# Beats per bar for the BPM display (4/4 is the default of the plan).
BEATS_PER_BAR = 4
# Same lowest ceiling as the live limiter (about -80 dBFS).
MIN_CEILING = 1e-4
# The limiter works block by block as in the audio callback.
LIMITER_BLOCK = 1024
# WAV format of every export.
EXPORT_SUBTYPE = "PCM_24"

NO_GRID_TEXT = (
    "In dieser Sitzung gibt es keinen Takt. Eine Summe über N Takte geht erst, wenn die erste "
    "Aufnahme einen Takt festlegt (Loops im Takt halten muss an sein). "
    "Als Notbehelf lässt sich \"N × längstes Sample\" ausdrücklich wählen."
)
NOTHING_TEXT = "Es gibt nichts zu exportieren: kein Pad mit Sample ist in der Auswahl."


class ExportError(ValueError):
    """The export cannot be made; the message is meant for the parents."""


@dataclass(frozen=True)
class ExportPad:
    """One pad's audio for the sum: ``data`` is mono float32 at the export rate."""

    pad: int
    data: np.ndarray


@dataclass(frozen=True)
class SumSpec:
    """What the sum is made of and how it is leveled."""

    sample_rate: int
    bars: int
    # Bar length in frames (the session grid); None = no grid.
    grid: int | None
    loops: Sequence[ExportPad]
    # One-shot pads, added once from the first frame (empty by default).
    one_shots: Sequence[ExportPad] = ()
    volume: float = 1.0
    ceiling_db: float = 0.0
    soft_seam: bool = True
    fade_out: bool = True
    # Stand-in without a grid: the longest loop counts as one bar.
    longest_as_bar: bool = False


@dataclass(frozen=True)
class SumInfo:
    """Facts about a planned sum (shown in the dialog, written into the file)."""

    bar_frames: int
    frames: int
    seconds: float
    bpm: float | None
    stand_in: bool


def ceiling_linear(db: float) -> float:
    return max(MIN_CEILING, min(1.0, db_to_gain(db)))


def bar_seconds(grid: int, sample_rate: int) -> float:
    return grid / sample_rate


def bpm_of(grid: int, sample_rate: int, beats: int = BEATS_PER_BAR) -> float:
    """Tempo for a bar of ``grid`` frames with ``beats`` beats."""
    return beats * 60.0 * sample_rate / grid


def plan_sum(spec: SumSpec) -> SumInfo:
    """Check ``spec`` and work out the exact length; ``ExportError`` if it cannot be made."""
    if not 1 <= spec.bars <= MAX_BARS:
        raise ExportError(f"Die Zahl der Takte muss zwischen 1 und {MAX_BARS} liegen.")
    if not spec.loops and not spec.one_shots:
        raise ExportError(NOTHING_TEXT)
    stand_in = spec.grid is None
    if spec.grid is not None:
        bar = spec.grid
    elif spec.longest_as_bar and spec.loops:
        bar = max(len(p.data) for p in spec.loops)
    else:
        raise ExportError(NO_GRID_TEXT)
    if bar <= 0:
        raise ExportError(NOTHING_TEXT)
    frames = spec.bars * bar
    return SumInfo(
        bar_frames=bar,
        frames=frames,
        seconds=frames / spec.sample_rate,
        bpm=None if stand_in else bpm_of(bar, spec.sample_rate),
        stand_in=stand_in,
    )


def _repeat(data: np.ndarray, frames: int) -> np.ndarray:
    """``data`` repeated from its first frame and cut to exactly ``frames``."""
    if len(data) == 0:
        return np.zeros(frames, dtype=np.float32)
    repeats = -(-frames // len(data))
    return np.tile(np.asarray(data, dtype=np.float32), repeats)[:frames]


def fade_out_frames(bar_frames: int, sample_rate: int) -> int:
    return min(round(FADE_OUT_SECONDS * sample_rate), int(FADE_OUT_BAR_FRACTION * bar_frames))


def apply_fade_out(mix: np.ndarray, frames: int) -> None:
    """Fade the last ``frames`` of ``mix`` to exactly zero (in place); ``mix`` is never louder after."""
    frames = min(frames, len(mix))
    if frames < 1:
        return
    ramp = 0.5 * (1.0 + np.cos(np.pi * np.arange(1, frames + 1) / frames))
    mix[len(mix) - frames:] *= ramp.astype(np.float32)


def render_sum(spec: SumSpec) -> np.ndarray:
    """The sum as mono float32, exactly ``bars x grid`` frames, kept under the ceiling."""
    info = plan_sum(spec)
    mix = np.zeros(info.frames, dtype=np.float32)
    for pad in spec.loops:
        voice = soften_seam(pad.data, spec.sample_rate) if spec.soft_seam else pad.data
        mix += _repeat(voice, info.frames)
    for pad in spec.one_shots:
        shot = np.asarray(pad.data, dtype=np.float32)[: info.frames]
        mix[: len(shot)] += shot
    mix *= np.float32(spec.volume)
    ceiling = ceiling_linear(spec.ceiling_db)
    limiter = PeakLimiter(spec.sample_rate)
    for start in range(0, info.frames, LIMITER_BLOCK):
        limiter.process(mix[start:start + LIMITER_BLOCK], ceiling)
    if spec.fade_out:
        apply_fade_out(mix, fade_out_frames(info.bar_frames, spec.sample_rate))
    return mix


def sum_comment(spec: SumSpec, info: SumInfo) -> str:
    """Text for the WAV comment field: what the file is, and a stand-in is named as one."""
    if info.stand_in:
        return (
            f"Loopstation Summe, NOTBEHELF: {spec.bars} x längstes Sample "
            f"({info.bar_frames} Frames), kein Takt in der Sitzung"
        )
    return (
        f"Loopstation Summe, {spec.bars} Takte x {info.bar_frames} Frames, "
        f"{info.bpm:.1f} BPM ({BEATS_PER_BAR}/4)"
    )


def write_wav(path: Path, data: np.ndarray, sample_rate: int, comment: str = "") -> None:
    """Write mono ``data`` as a 24-bit WAV, atomically (temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with soundfile.SoundFile(
            str(tmp), "w", samplerate=sample_rate, channels=1, subtype=EXPORT_SUBTYPE, format="WAV"
        ) as out:
            if comment:
                out.comment = comment
            out.write(np.asarray(data, dtype=np.float32))
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def export_sum(path: Path, spec: SumSpec) -> SumInfo:
    """Render the sum and write it to ``path``; returns the facts about it."""
    info = plan_sum(spec)
    data = render_sum(spec)
    try:
        write_wav(path, data, spec.sample_rate, sum_comment(spec, info))
    except OSError as exc:
        raise ExportError(f"Die Datei lässt sich nicht schreiben: {exc}") from exc
    return info


def export_loop(path: Path, data: np.ndarray, sample_rate: int, comment: str = "") -> None:
    """Write one loop unchanged (no volume, no limiter) as a 24-bit WAV."""
    if len(data) == 0:
        raise ExportError(NOTHING_TEXT)
    try:
        write_wav(path, data, sample_rate, comment)
    except OSError as exc:
        raise ExportError(f"Die Datei lässt sich nicht schreiben: {exc}") from exc


def repeats_per_bar(loop_frames: int, bar_frames: int) -> float:
    """How many bars one pass of a loop spans (for the preview rows)."""
    return loop_frames / bar_frames if bar_frames > 0 else math.nan


# --------------------------------------------------- from the controller


def selected_pads(controller: Controller, all_pads: bool) -> tuple[list[int], list[int]]:
    """``(loop pads, one-shot pads)``: the pads that loop now, or every pad with a sample as a loop.

    A one-shot pad has a sample but is not looping; with ``all_pads`` there
    are none, because every pad with a sample counts as a loop.
    """
    with_sample = [i for i in range(controller.pad_count) if controller.pad(i).sample is not None]
    if all_pads:
        return with_sample, []
    loops = [i for i in with_sample if controller.pad(i).looping]
    return loops, [i for i in with_sample if i not in loops]


def build_spec(
    controller: Controller,
    bars: int,
    all_pads: bool = False,
    include_one_shots: bool = False,
    fade_out: bool = True,
    longest_as_bar: bool = False,
) -> SumSpec:
    """The sum of ``controller``'s session with its volume, ceiling and seam setting."""
    loop_ids, shot_ids = selected_pads(controller, all_pads)

    def audio(pad: int, as_loop: bool) -> ExportPad:
        sample = controller.pad(pad).sample
        data = None if sample is None else (
            controller.loop_audio(sample, pad) if as_loop else controller.sample_audio(sample))
        if data is None:
            raise ExportError(f"Die Aufnahme von Pad {pad + 1} fehlt oder ist nicht lesbar.")
        return ExportPad(pad, data)

    return SumSpec(
        sample_rate=controller.sample_rate,
        bars=bars,
        grid=controller.grid_frames(),
        loops=[audio(pad, True) for pad in loop_ids],
        one_shots=[audio(pad, False) for pad in shot_ids] if include_one_shots else [],
        volume=controller.volume,
        ceiling_db=controller.max_level_db,
        soft_seam=controller.settings.soft_seam,
        fade_out=fade_out,
        longest_as_bar=longest_as_bar,
    )
