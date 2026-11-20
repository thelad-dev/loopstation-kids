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
