import numpy as np
import pytest

from loopstation.audio.stretch import (
    DEFAULT_MAX_DEVIATION,
    WsolaEngine,
    stretch_target,
    stretch_to_grid,
)

RATE = 48000
GRID = RATE // 2


def sine(frames: int, frequency: float = 440.0) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / RATE
    return (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def dominant_frequency(data: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(data * np.hanning(len(data))))
    return float(np.argmax(spectrum)) * RATE / len(data)


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def stretch(self, data: np.ndarray, target: int) -> np.ndarray:
        self.calls.append((len(data), target))
        return np.full(target, 0.25, dtype=np.float32)


@pytest.mark.parametrize("loops", [1, 2, 3])
@pytest.mark.parametrize("deviation", [0.03, 0.08, -0.03, -0.08])
def test_within_limit_is_stretched_to_the_exact_multiple(loops, deviation):
    target = loops * GRID
    data = sine(round(target * (1 + deviation)))
    result = stretch_to_grid(data, GRID)
    assert result is not None
    assert len(result) == target
    assert result.dtype == np.float32


@pytest.mark.parametrize("loops", [1, 2, 3])
@pytest.mark.parametrize("deviation", [0.12, -0.12])
def test_beyond_limit_returns_none(loops, deviation):
    data = sine(round(loops * GRID * (1 + deviation)))
    assert stretch_to_grid(data, GRID) is None


def test_limit_is_a_parameter():
    data = sine(round(GRID * 1.12))
    assert stretch_to_grid(data, GRID) is None
    assert len(stretch_to_grid(data, GRID, max_deviation=0.15)) == GRID
    near = sine(round(GRID * 1.08))
    assert stretch_to_grid(near, GRID, max_deviation=0.05) is None
    assert DEFAULT_MAX_DEVIATION == 0.10


def test_single_clap_in_a_standing_grid_is_not_stretched():
    clap = np.zeros(RATE // 5, dtype=np.float32)
    clap[:200] = 0.8
    assert stretch_to_grid(clap, GRID) is None


def test_exact_length_is_returned_unchanged():
    data = sine(2 * GRID)
    assert stretch_to_grid(data, GRID) is data


def test_empty_data_is_not_stretched():
    assert stretch_to_grid(np.zeros(0, dtype=np.float32), GRID) is None


def test_stretch_target_rounds_to_the_nearest_loop_and_never_below_one():
    assert stretch_target(10, GRID) == GRID
    assert stretch_target(int(1.4 * GRID), GRID) == GRID
    assert stretch_target(int(1.6 * GRID), GRID) == 2 * GRID
    with pytest.raises(ValueError):
        stretch_target(10, 0)


@pytest.mark.parametrize("deviation", [0.03, 0.08, -0.03, -0.08])
def test_pitch_is_roughly_preserved(deviation):
    data = sine(round(2 * GRID * (1 + deviation)), 440.0)
    result = stretch_to_grid(data, GRID)
    assert result is not None
    before = dominant_frequency(data)
    after = dominant_frequency(result)
    assert abs(after - before) / before < 0.02


def test_stretched_signal_stays_audible_and_bounded():
    result = stretch_to_grid(sine(round(GRID * 1.06)), GRID)
    assert result is not None
    middle = result[GRID // 4 : -GRID // 4]
    assert 0.3 < float(np.abs(middle).max()) < 0.7


def test_fake_engine_is_used_instead_of_the_fallback():
    engine = FakeEngine()
    data = sine(round(GRID * 0.95))
    result = stretch_to_grid(data, GRID, engine=engine)
    assert engine.calls == [(len(data), GRID)]
    assert np.all(result == 0.25)


def test_fake_engine_is_not_called_beyond_the_limit_or_for_exact_length():
    engine = FakeEngine()
    assert stretch_to_grid(sine(round(GRID * 1.3)), GRID, engine=engine) is None
    stretch_to_grid(sine(GRID), GRID, engine=engine)
    assert engine.calls == []


def test_engine_with_wrong_length_is_rejected():
    class Broken:
        def stretch(self, data, target):
            return data

    with pytest.raises(ValueError):
        stretch_to_grid(sine(round(GRID * 0.95)), GRID, engine=Broken())


@pytest.mark.parametrize("frames", [1, 7, 100, 3000])
def test_wsola_handles_tiny_inputs(frames):
    result = WsolaEngine().stretch(sine(frames), frames + 5)
    assert len(result) == frames + 5


def test_wsola_rejects_bad_arguments():
    with pytest.raises(ValueError):
        WsolaEngine(frame_size=7)
    with pytest.raises(ValueError):
        WsolaEngine().stretch(sine(100), 0)


@pytest.mark.parametrize("deviation", [0.05, -0.05])
def test_transient_on_the_first_sample_keeps_its_attack(deviation):
    data = np.zeros(round(GRID * (1 + deviation)), dtype=np.float32)
    data[:64] = 0.9
    result = stretch_to_grid(data, GRID)
    assert result is not None
    assert result[0] == pytest.approx(0.9, abs=1e-4)
    assert float(np.max(np.abs(result[:64]))) == pytest.approx(0.9, abs=1e-4)


def burst(rate: int, kind: str) -> np.ndarray:
    """A sharp clap (30 ms) or a soft shaker hit (8 ms rise, 60 ms)."""
    rng = np.random.default_rng(1)
    if kind == "clap":
        n = int(0.03 * rate)
        k = np.arange(n)
        env = np.exp(-k / (n / 5))
        return (0.8 * env * (0.6 * np.sin(2 * np.pi * 1000 * k / rate) + 0.4 * rng.uniform(-1, 1, n))).astype(
            np.float32)
    n = int(0.06 * rate)
    k = np.arange(n)
    rise = int(0.008 * rate)
    env = np.minimum(1.0, k / rise) * np.exp(-np.maximum(0, k - rise) / (0.015 * rate))
    return (0.3 * env * rng.uniform(-1, 1, n)).astype(np.float32)


def hit_train(rate: int, kind: str, hiss: bool) -> tuple[np.ndarray, int]:
    """Eight hits about 0.48 s apart, in silence or over quiet hiss; returns the data and the gap."""
    gap = round(0.476 * rate)
    first = round(0.045 * rate)
    data = np.zeros(first + 8 * gap, dtype=np.float32)
    hit = burst(rate, kind)
    for i in range(8):
        start = first + i * gap
        data[start : start + len(hit)] += hit
    if hiss:
        data += (np.random.default_rng(5).standard_normal(len(data)) * 0.001).astype(np.float32)
    return data, gap


def attacks(data: np.ndarray, gap: int) -> list[int]:
    """The first frame of every hit: above a tenth of the peak after a quiet stretch."""
    hits = np.nonzero(np.abs(data) > 0.1 * float(np.abs(data).max()))[0]
    found: list[int] = []
    for h in hits:
        if not found or h - found[-1] > gap // 4:
            found.append(int(h))
    return found


@pytest.mark.parametrize("rate", [44100, 8000])
@pytest.mark.parametrize("ratio", [0.91, 0.95, 1.02, 1.05, 1.1])
@pytest.mark.parametrize("kind", ["clap", "shaker"])
@pytest.mark.parametrize("hiss", [False, True])
def test_wsola_keeps_every_attack_at_its_stretched_place(rate, ratio, kind, hiss):
    data, gap = hit_train(rate, kind, hiss)
    result = WsolaEngine().stretch(data, round(len(data) * ratio))
    before = attacks(data, gap)
    after = attacks(result, gap)
    assert len(before) == 8
    assert len(after) == 8
    tolerance = 0.002 * rate  # 2 ms
    pairs = zip(after, before, strict=True)
    misplaced = [(a, round(b * ratio)) for a, b in pairs if abs(a - b * ratio) > tolerance]
    assert misplaced == []


def harmonic_tone(rate: int, seconds: float, vibrato: float = 0.0) -> np.ndarray:
    t = np.arange(round(seconds * rate)) / rate
    phase = 2 * np.pi * np.cumsum(220.0 * (1 + vibrato * np.sin(2 * np.pi * 5 * t))) / rate
    return sum(a * np.sin(h * phase) for h, a in ((1, 0.3), (2, 0.2), (3, 0.1))).astype(np.float32)


@pytest.mark.parametrize("ratio", [0.91, 0.95, 1.05, 1.1])
def test_wsola_keeps_a_harmonic_tone_clean(ratio):
    rate = 44100
    data = harmonic_tone(rate, 2.0)
    result = WsolaEngine().stretch(data, round(len(data) * ratio))
    middle = result[2048:-2048]
    spectrum = np.abs(np.fft.rfft(middle * np.hanning(len(middle)))) ** 2
    frequency = np.arange(len(spectrum)) * rate / len(middle)
    peak = float(frequency[np.argmax(spectrum)])
    assert abs(peak - 220.0) < 1.0
    harmonic = np.zeros(len(spectrum), dtype=bool)
    for h in (1, 2, 3):
        harmonic |= np.abs(frequency - 220.0 * h) < 3.0
    rest_db = 10 * np.log10(spectrum[~harmonic].sum() / spectrum[harmonic].sum())
    assert rest_db < -38.0  # the search before this fix measured about -40 dB


@pytest.mark.parametrize("ratio", [0.91, 0.95, 1.05, 1.1])
def test_wsola_keeps_a_sung_tone_steady(ratio):
    rate = 44100
    data = harmonic_tone(rate, 2.0, vibrato=0.02)
    result = WsolaEngine().stretch(data, round(len(data) * ratio))
    blocks = result[4410:-4410]
    blocks = blocks[: len(blocks) // 441 * 441].reshape(-1, 441)
    level = np.sqrt(np.mean(blocks**2, axis=1))
    assert 20 * np.log10(level.max() / level.min()) < 2.0  # no dropouts from bad splices


def claps_over_tone(
    rate: int, offsets: list[int], vibrato: float = 0.0
) -> tuple[np.ndarray, list[int], np.ndarray]:
    """A held tone (about -10 dB under the claps) with a clap every half second, each starting
    ``offsets[i]`` frames into a 64-frame grid (the claps must be found wherever they fall)."""
    data = (harmonic_tone(rate, 4.0, vibrato) / 3).astype(np.float32)
    clap = burst(rate, "clap") * 1.2
    places = [(round((0.5 + i * 0.5) * rate) // 64) * 64 + offsets[i % len(offsets)] for i in range(7)]
    for place in places:
        data[place : place + len(clap)] += clap
    return data, places, clap


@pytest.mark.parametrize("ratio", [0.91, 0.95, 1.05, 1.1])
def test_wsola_keeps_claps_over_a_held_tone_in_place(ratio):
    rate = 44100
    data, places, clap = claps_over_tone(rate, [0, 24, 40, 56])
    result = WsolaEngine().stretch(data, round(len(data) * ratio))
    misplaced = []
    for place in places:
        want = round(place * ratio)
        around = result[want - 1000 : want + 1000]
        found = want - 1000 + int(np.argmax(np.correlate(around, clap[:300], mode="valid")))
        if abs(found - want) > 0.002 * rate:  # 2 ms
            misplaced.append((found, want))
    assert misplaced == []


@pytest.mark.parametrize("ratio", [0.91, 0.95, 1.05, 1.1])
@pytest.mark.parametrize("vibrato", [0.0, 0.02])
def test_wsola_keeps_the_tone_steady_before_each_clap(ratio, vibrato):
    rate = 44100
    data, places, _ = claps_over_tone(rate, [2], vibrato)
    result = WsolaEngine().stretch(data, round(len(data) * ratio))
    worst = 0.0
    for place in places:
        at = round(place * ratio)
        before = result[at - round(0.15 * rate) : at - round(0.012 * rate)]  # tone only, up to the clap
        blocks = before[: len(before) // 220 * 220].reshape(-1, 220)
        level = np.sqrt(np.mean(blocks**2, axis=1))
        worst = max(worst, 20 * np.log10(level.max() / level.min()))
    assert worst < 4.0  # the tone alone varies about 1.1-1.5 dB; a bad splice before the clap dips 6-8 dB
