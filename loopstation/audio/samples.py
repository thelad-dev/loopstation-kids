"""WAV files for recorded samples: naming, writing and reading."""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import soundfile

_NAME_RE = re.compile(r"^pad_(\d+)_(\d+)\.wav$")


def sample_filename(pad: int, stamp: int) -> str:
    """File name for a recording on ``pad`` started at ``stamp`` (epoch ms)."""
    return f"pad_{pad}_{stamp}.wav"


def parse_stamp(filename: str) -> int | None:
    """Epoch milliseconds encoded in a sample file name, or None."""
    match = _NAME_RE.match(filename)
    return int(match.group(2)) if match else None


def save_wav(path: Path, data: np.ndarray, sample_rate: int) -> None:
    """Write mono float data as 16-bit PCM WAV, atomically and durably."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    soundfile.write(str(tmp), np.asarray(data, dtype=np.float32), sample_rate,
                    subtype="PCM_16", format="WAV")
    with open(tmp, "r+b") as handle:  # fsync needs a writable fd on Windows
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_wav(path: Path, target_rate: int) -> np.ndarray:
    """Read a WAV file as mono float32 at ``target_rate``.

    Multi-channel files are mixed down; a different sample rate is converted
    with simple linear interpolation (good enough for short kid recordings).
    """
    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1).astype(np.float32)
    if rate != target_rate and len(mono) > 1:
        count = max(1, round(len(mono) * target_rate / rate))
        positions = np.linspace(0, len(mono) - 1, count)
        mono = np.interp(positions, np.arange(len(mono)), mono).astype(np.float32)
    return mono
