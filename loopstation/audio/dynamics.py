"""Level handling that does not depend on any audio device.

Everything here works on float32 NumPy blocks. The output side (``PeakLimiter``
and ``ramp_gain``) writes into preallocated work buffers, so the audio
callback allocates nothing per block once the buffers have grown to the
largest block size seen so far.

Level chain of the output: sum of all voices, times the master volume (moved
in small steps, never in jumps), then the peak limiter with the ceiling that
the parents set. The microphone side has a trim in dB, a soft clipper and the
auto-gain rule.
"""

from __future__ import annotations

import math

import numpy as np

# Input samples at or above this magnitude count as clipped (a converter at
# full scale delivers exactly +-1.0; the margin covers rounding).
CLIP_LEVEL = 0.999


def db_to_gain(db: float) -> float:
    return 10.0 ** (db / 20.0)


def gain_to_db(gain: float) -> float:
    return 20.0 * math.log10(gain) if gain > 0 else float("-inf")


def block_peak(block: np.ndarray) -> float:
    """Largest magnitude of ``block`` without making a temporary copy."""
    if len(block) == 0:
        return 0.0
    return max(float(block.max()), -float(block.min()))


def ramp_gain(current: float, target: float, frames: int, max_step: float) -> float:
    """Gain at the end of a block of ``frames``: ``current`` moves towards ``target``.

    ``max_step`` is the largest change per sample, so a slider jump becomes a
    ramp that lasts the same time whatever the block size is.
    """
    limit = max_step * frames
    return current + max(-limit, min(limit, target - current))


class PeakLimiter:
    """Keeps the peaks of a block under a ceiling without a hard clip.

    A gain curve is applied to the block. For every sample the gain is at most
    ``ceiling / |x|``, so no peak passes. The curve sees ahead inside the
    block and starts to fall before a peak (``attack`` seconds for the full
    range) and climbs back slowly afterwards (``release`` seconds for the full
    range), which avoids both edges and pumping. There is no delay line:
    nothing is shifted in time. Only when a peak sits at the very start of a
    block, the gain can step once, because the previous block is gone.

    ``process`` works in place. A last ``clip`` to the ceiling only catches
    float rounding.
    """

    def __init__(
        self,
        sample_rate: int,
        attack: float = 0.0015,
        release: float = 0.25,
        capacity: int = 8192,
    ) -> None:
        self.sample_rate = sample_rate
        self.attack_slope = 1.0 / max(1.0, attack * sample_rate)
        self.release_slope = 1.0 / max(1.0, release * sample_rate)
        self.gain = 1.0  # gain at the end of the last block
        self._grow(capacity)

    def _grow(self, size: int) -> None:
        index = np.arange(size, dtype=np.float32)
        self._attack_ramp = index * np.float32(self.attack_slope)
        self._release_ramp = (index + 1.0) * np.float32(self.release_slope)
        self._need = np.empty(size, dtype=np.float32)
        self._curve = np.empty(size, dtype=np.float32)

    def reset(self) -> None:
        self.gain = 1.0

    def process(self, block: np.ndarray, ceiling: float) -> None:
        """Limit ``block`` (1-D float32, modified in place) to ``ceiling`` (linear, > 0)."""
        frames = len(block)
        if frames == 0:
            return
        if frames > len(self._need):
            self._grow(max(frames, 2 * len(self._need)))
        need = self._need[:frames]
        curve = self._curve[:frames]

        np.abs(block, out=need)
        if self.gain >= 1.0 and float(need.max()) <= ceiling:
            return  # nothing to do, the common case

        # Gain every sample needs so that it stays under the ceiling.
        np.maximum(need, ceiling, out=need)
        np.divide(ceiling, need, out=need)
        # Look ahead inside the block: min over j >= i of need[j] + slope * (j - i).
        np.add(need, self._attack_ramp[:frames], out=curve)
        np.minimum.accumulate(curve[::-1], out=curve[::-1])
        np.subtract(curve, self._attack_ramp[:frames], out=curve)
        np.minimum(curve, need, out=curve)  # rounding: never above the exact need
        # Climb back to unity slowly.
        np.add(self._release_ramp[:frames], self.gain, out=need)
        np.minimum(curve, need, out=curve)
        np.minimum(curve, 1.0, out=curve)

        block *= curve
        self.gain = float(curve[-1])
        np.clip(block, -ceiling, ceiling, out=block)


def soft_clip(block: np.ndarray, knee: float = 0.7, abs_buf: np.ndarray | None = None) -> np.ndarray:
    """Round off peaks above ``knee`` (in place); the result never exceeds +-1.

    Below the knee the signal passes unchanged; above it a tanh curve joins
    with the same slope and approaches +-1 smoothly. It is monotonic.
    ``abs_buf`` (same length as ``block``) avoids allocating in the audio callback.
    """
    magnitude = abs_buf[: len(block)] if abs_buf is not None else np.abs(block)
    if abs_buf is not None:
        np.abs(block, out=magnitude)
    over = magnitude > knee
    if over.any():
        span = 1.0 - knee
        shaped = knee + span * np.tanh((magnitude[over] - knee) / span)
        block[over] = np.copysign(shaped, block[over])
    return block


# Pad boost: linear gain may exceed 1 (0 dB). Soft-limit at the pad keeps the sum safe.
PAD_GAIN_MAX_DB = 18.0
PAD_GAIN_MAX = db_to_gain(PAD_GAIN_MAX_DB)
PAD_NORMALIZE_TARGET_DB = -3.0
PAD_NORMALIZE_TARGET = db_to_gain(PAD_NORMALIZE_TARGET_DB)


# --------------------------------------------------------------- auto gain

AUTO_GAIN_TARGET_DB = -18.0  # wanted average level (RMS) of the take
AUTO_GAIN_RANGE_DB = 12.0  # auto gain moves the trim by at most this much
AUTO_GAIN_UP_DB_PER_SECOND = 1.5  # slow on the way up ...
AUTO_GAIN_DOWN_DB_PER_SECOND = 6.0  # ... a bit quicker on the way down
AUTO_GAIN_SILENCE_DB = -55.0  # below this the block is noise and changes nothing
AUTO_GAIN_PEAK_LIMIT_DB = -3.0  # never lift a peak above this


def auto_gain_step(
    current_db: float,
    rms_db: float,
    peak: float,
    clipped: bool,
    seconds: float,
) -> float:
    """New auto-gain offset in dB after one input block of ``seconds``.

    ``rms_db`` and ``peak`` describe the block *before* the offset (but after
    the trim). A clipping block never raises the gain: it lowers
    it. Quiet blocks change nothing, the target is approached slowly and the
    offset stays within +-``AUTO_GAIN_RANGE_DB``.
    """
    if clipped:
        change = -AUTO_GAIN_DOWN_DB_PER_SECOND * seconds
    elif rms_db < AUTO_GAIN_SILENCE_DB:
        return current_db
    else:
        error = AUTO_GAIN_TARGET_DB - (rms_db + current_db)
        if error >= 0:
            change = min(error, AUTO_GAIN_UP_DB_PER_SECOND * seconds)
            # Do not lift the peak of this block into the soft clipper.
            if peak > 0:
                room = AUTO_GAIN_PEAK_LIMIT_DB - gain_to_db(peak) - current_db
                change = min(change, max(0.0, room))
        else:
            change = max(error, -AUTO_GAIN_DOWN_DB_PER_SECOND * seconds)
    return max(-AUTO_GAIN_RANGE_DB, min(AUTO_GAIN_RANGE_DB, current_db + change))
