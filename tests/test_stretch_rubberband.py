"""Rubber Band engine behind the stretch interface (W3-RUBBERBAND).

Tests that need the real library are skipped with a reason where ``pylibrb`` is not
installed; the fallback tests run everywhere and mock the library away.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from conftest import make_settings

from loopstation.audio import stretch as stretch_module
from loopstation.audio.stretch import (
    RubberBandEngine,
    WsolaEngine,
    engine_notice,
    resolve_engine,
    rubberband_status,
    stretch_to_grid,
)
from loopstation.config import STRETCH_ENGINES, ConfigError, Settings, parse_settings
from loopstation.controller import LIVE_SETTINGS

RATE = 44100
GRID = RATE // 2

needs_rubberband = pytest.mark.skipif(
    not rubberband_status()[0], reason=f"Rubber Band not usable here: {rubberband_status()[1]}"
)


@pytest.fixture
def no_rubberband(monkeypatch):
    """The library cannot be imported (as on a platform without a wheel)."""
    monkeypatch.setitem(sys.modules, "pylibrb", None)
    stretch_module.rubberband_status.cache_clear()
    yield
    stretch_module.rubberband_status.cache_clear()


def clicks(frames: int, count: int) -> np.ndarray:
    """``count`` impulses spread evenly over ``frames`` (a click track)."""
    data = np.zeros(frames, dtype=np.float32)
    for k in range(count):
        data[int(k * frames / count)] = 0.5
    return data


def click_positions(data: np.ndarray, count: int, period: int) -> list[int]:
    positions = []
    for k in range(count):
        start = max(0, k * period - period // 2)
        window = np.abs(data[start : k * period + period // 2])
        positions.append(start + int(np.argmax(window)))
    return positions


# ------------------------------------------------------------- the real library


@needs_rubberband
@pytest.mark.parametrize("deviation", [0.03, 0.08, -0.03, -0.08])
def test_rubberband_stretch_keeps_length_period_and_level(deviation):
    count = 4
    target = count * GRID
    data = clicks(round(target * (1 + deviation)), count)
    result = RubberBandEngine(RATE).stretch(data, target)
    assert len(result) == target and result.dtype == np.float32
    positions = click_positions(result, count, GRID)
    # The clicks keep their period (a phase vocoder smears an impulse by a couple of ms).
    assert all(abs(b - a - GRID) <= RATE * 0.005 for a, b in zip(positions, positions[1:], strict=False))
    # Never louder than the input: the engine does not approach the master ceiling by itself.
    assert float(np.abs(result).max()) <= float(np.abs(data).max()) + 1e-6


@needs_rubberband
def test_rubberband_keeps_the_pitch_of_a_tone():
    t = np.arange(round(GRID * 1.05)) / RATE
    data = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    result = RubberBandEngine(RATE).stretch(data, GRID)
    spectrum = np.abs(np.fft.rfft(result * np.hanning(len(result))))
    assert abs(float(np.argmax(spectrum)) * RATE / len(result) - 440) < 5


@needs_rubberband
def test_rubberband_engine_goes_through_stretch_to_grid():
    data = clicks(round(GRID * 0.95), 1)
    result = stretch_to_grid(data, GRID, engine=RubberBandEngine(RATE))
    assert result is not None and len(result) == GRID


@needs_rubberband
def test_rubberband_is_found_and_described():
    assert rubberband_status()[0] is True
    assert "pylibrb" in engine_notice("auto")
    assert isinstance(resolve_engine("auto", RATE), RubberBandEngine)
    assert isinstance(resolve_engine("rubberband", RATE), RubberBandEngine)


# ----------------------------------------------------- fallback, no library needed


def test_simple_always_resolves_to_the_builtin_engine():
    assert isinstance(resolve_engine("simple", RATE), WsolaEngine)


def test_missing_library_falls_back_for_auto_and_rubberband(no_rubberband):
    assert rubberband_status()[0] is False
    for choice in ("auto", "rubberband"):
        engine = resolve_engine(choice, RATE)
        assert isinstance(engine, WsolaEngine)
        data = clicks(round(GRID * 0.95), 1)
        assert len(stretch_to_grid(data, GRID, engine=engine)) == GRID


def test_missing_library_is_explained_to_the_parents(no_rubberband):
    assert "fehlt" in engine_notice("auto") and "einfache Stretch" in engine_notice("auto")
    assert "nicht nutzbar" in engine_notice("rubberband")
    assert "pylibrb" in engine_notice("auto")
    assert engine_notice("simple") == "Der einfache, eingebaute Stretch wird benutzt."


def test_a_failing_library_falls_back_for_that_stretch(monkeypatch):
    engine = RubberBandEngine(RATE)

    def boom(data, target):
        raise RuntimeError("library crashed")

    monkeypatch.setattr(engine, "_run", boom)
    data = clicks(round(GRID * 0.95), 1)
    assert len(engine.stretch(data, GRID)) == GRID


def test_engine_edge_cases_do_not_need_the_library():
    engine = RubberBandEngine(RATE)
    data = np.ones(100, dtype=np.float32)
    assert engine.stretch(data, 100) is data
    assert np.array_equal(engine.stretch(np.zeros(0, dtype=np.float32), 50), np.zeros(50, dtype=np.float32))
    with pytest.raises(ValueError):
        engine.stretch(data, 0)


# ------------------------------------------------------------------ the setting


def test_setting_defaults_and_validation():
    assert Settings().stretch_engine == "auto"
    assert STRETCH_ENGINES == ("auto", "rubberband", "simple")
    assert "stretch_engine" in LIVE_SETTINGS
    for value in STRETCH_ENGINES:
        assert parse_settings({"stretch_engine": value}).stretch_engine == value
    with pytest.raises(ConfigError, match="stretch_engine"):
        parse_settings({"stretch_engine": "magic"}, "settings.toml")


def test_controller_uses_the_chosen_engine(tmp_path, clock, monkeypatch):
    from conftest import FakeAudio

    from loopstation.controller import Controller
    from loopstation.store import EventStore

    chosen = []

    def fake_resolve(choice, rate):
        chosen.append((choice, rate))
        return WsolaEngine()

    monkeypatch.setattr("loopstation.controller.resolve_engine", fake_resolve)
    settings = make_settings(tmp_path, stretch_engine="simple")
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, FakeAudio(clock), settings, clock=clock)
    engine = controller._stretch_engine()
    assert controller._stretch_engine() is engine  # kept, not rebuilt per stretch
    assert chosen == [("simple", controller.audio.sample_rate)]
    controller.apply_settings(Settings(**{**controller.settings.__dict__, "stretch_engine": "auto"}))
    controller._stretch_engine()
    assert chosen[-1][0] == "auto"  # the live setting takes effect at once


def test_parents_page_shows_the_engine_choice_and_why(qapp, tmp_path, no_rubberband):
    from loopstation.gui.settings_page import SettingsDialog

    dialog = SettingsDialog(tmp_path / "settings.toml", make_settings(tmp_path), lambda s: [])
    editor = dialog.editors["stretch_engine"]
    assert [editor._combo.itemText(i) for i in range(editor._combo.count())] == list(STRETCH_ENGINES)
    assert "fehlt" in dialog._engine_hint.text()
    editor._combo.setCurrentText("simple")
    assert dialog._engine_hint.text() == engine_notice("simple")
