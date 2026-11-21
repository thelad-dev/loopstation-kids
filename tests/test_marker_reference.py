"""Markers the parents set are final: no complaint about estimated beats, snapping, strict onsets."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_markers import GRID, SR, click_frame, on_grid

from loopstation.audio.onset import detect_onsets, nearest_transient
from loopstation.audio.stretch import MarkerStretchError, stretch_between_markers
from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import LIVE_SETTINGS
from loopstation.gui.advanced_page import AdvancedDialog

RATE = 48000
HITS = [0.5, 1.37, 2.31, 3.12]  # a child's hits: none of them on a quarter of the 4 s loop
AMPS = [0.6, 0.5, 0.55, 0.45]


def hits_signal(seed, *, noise=0.01, rustle=0.0, rustles=0, hum=0.0, tail=0.0, length=4.0,
                hits=HITS, amps=AMPS):
    """Short noise bursts at known times plus room noise, rustling, hum and a reverb tail."""
    rng = np.random.default_rng(seed)
    n = int(length * RATE)
    x = rng.normal(0, noise, n)
    for at, amp in zip(hits, amps, strict=True):
        i = int(at * RATE)
        m = min(int(0.05 * RATE), n - i)
        x[i : i + m] += rng.normal(0, amp, m) * np.exp(-np.arange(m) / (0.01 * RATE))
    for at in rng.uniform(0.2, length - 0.3, rustles):
        i, m = int(at * RATE), int(0.04 * RATE)
        x[i : i + m] += rng.normal(0, rustle, m) * np.hanning(m)
    if hum:
        x += hum * np.sin(2 * np.pi * 220 * np.arange(n) / RATE)
    if tail:
        ir = np.exp(-np.arange(int(0.6 * RATE)) / (0.2 * RATE)) * rng.normal(0, 1, int(0.6 * RATE))
        x += tail * np.fft.irfft(np.fft.rfft(x, 2 * n) * np.fft.rfft(ir * 0.1, 2 * n))[:n]
    return x.astype(np.float32)


def invented(onsets, hits=HITS, tolerance=0.05):
    return [o / RATE for o in onsets if min(abs(o / RATE - h) for h in hits) > tolerance]


# ----------------------------------------------------------------- the false alarm

def test_markers_on_the_hits_were_refused_against_estimated_beat_lines():
    x = hits_signal(1)
    marks = [int(h * RATE) for h in HITS[1:]]
    with pytest.raises(MarkerStretchError) as caught:  # what every stretch did until now
        stretch_between_markers(x, marks, RATE * 1.0)
    assert caught.value.reason == "too_far"
    result, targets = stretch_between_markers(x, marks, RATE * 1.0, max_deviation=None)
    assert len(result) == len(x) and targets == [RATE, 2 * RATE, 3 * RATE]


def test_a_stretch_on_an_estimated_grid_never_refuses_a_marker_on_a_hit(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.37, 1.31))  # the hits sit far from the quarters
    assert controller.grid_info().source != "parent_bpm"
    for hit in (0.37, 1.31):
        assert controller.add_marker(1, int(hit * SR))
    old = controller.pad(1).sample
    assert controller.stretch_to_markers(1) is None  # no "zu weit neben seinem Schlag"
    new = controller.pad(1).sample
    assert new != old and len(controller.sample_audio(new)) == GRID
    controller.undo(1)
    assert controller.pad(1).sample == old  # and Zurück takes it back
    controller.shutdown()


def test_the_parents_own_tempo_keeps_the_limit(tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock)
    assert controller.set_parent_grid(120, "4/4")
    controller.add_marker(1, 6000)
    assert "zu weit" in controller.stretch_to_markers(1)
    controller.shutdown()


# ------------------------------------------------------------ no invented beats

@pytest.mark.parametrize("level", [0.0, 0.002, 0.01, 0.03, 0.08])
def test_silence_and_noise_give_no_onsets(level):
    for seed in range(5):
        noise = np.random.default_rng(seed).normal(0, level, 4 * RATE).astype(np.float32)
        assert detect_onsets(noise, RATE) == []


def test_real_hits_are_found_on_time_and_nothing_else():
    for seed in range(8):
        onsets = detect_onsets(hits_signal(seed, tail=1.0), RATE)
        assert invented(onsets) == []
        for hit in HITS:
            assert min(abs(o / RATE - hit) for o in onsets) < 0.03


def test_rustling_does_not_become_beats_but_did_before():
    old = dict(rel_threshold=0.25, min_peak=0.01, min_gap_seconds=0.05, rise_ratio=3.0,
               rise_lookback_seconds=0.03, noise_factor=0.0, max_attack_seconds=10.0)
    before = now = 0
    for seed in range(8):
        x = hits_signal(seed, rustle=0.12, rustles=6)
        before += len(invented(detect_onsets(x, RATE, **old)))
        now += len(invented(detect_onsets(x, RATE)))
    assert before >= 20 and now <= 2


def test_a_hum_and_a_slow_swell_are_not_hits():
    t = np.arange(4 * RATE) / RATE
    swell = (0.3 * np.sin(2 * np.pi * 220 * t) * np.sin(np.pi * t / 4) ** 2).astype(np.float32)
    assert detect_onsets(swell, RATE) == []
    assert detect_onsets(swell + hits_signal(3, hits=[], amps=[]), RATE) == []


def test_the_steps_of_a_ramp_are_not_hits():
    ramp = 0.3 * (2 * (np.arange(RATE) % 1777) / 1777 - 1)  # a tone that jumps every 1777 frames
    assert detect_onsets(ramp.astype(np.float32), RATE) == []


# ------------------------------------------------------------------- snapping

@pytest.mark.parametrize("offset", [-0.04, -0.01, 0.0, 0.03, 0.05])
def test_snapping_finds_the_right_transient(offset):
    x = hits_signal(2, rustle=0.1, rustles=3)
    for hit in HITS:
        snapped = nearest_transient(x, RATE, int((hit + offset) * RATE))
        assert snapped is not None and abs(snapped / RATE - hit) < 0.004


def test_snapping_leaves_a_click_far_from_any_hit_alone():
    x = hits_signal(2)
    assert nearest_transient(x, RATE, int(2.0 * RATE)) is None
    assert nearest_transient(np.zeros(RATE, np.float32), RATE, 1000) is None
    assert nearest_transient(np.random.default_rng(0).normal(0, 0.05, RATE), RATE, 1000) is None
    assert nearest_transient(np.zeros(0, np.float32), RATE, 0) is None


def test_a_quiet_blip_does_not_steal_the_marker_from_the_hit():
    x = hits_signal(4, hits=[1.0, 1.04], amps=[0.7, 0.08], length=2.0)
    snapped = nearest_transient(x, RATE, int(1.035 * RATE))
    assert snapped is not None and abs(snapped / RATE - 1.0) < 0.004


# ----------------------------------------------------------- settings and page

def test_the_snap_setting_is_a_live_bool_that_is_on_by_default():
    assert Settings().snap_markers is True and "snap_markers" in LIVE_SETTINGS
    assert parse_settings({"snap_markers": False}).snap_markers is False
    with pytest.raises(ConfigError):
        parse_settings({"snap_markers": "ja"})


@pytest.fixture
def snap_page(qapp, tmp_path, clock):
    controller, _ = on_grid(tmp_path, clock, claps_pad1=(0.37, 1.31))
    dialog = AdvancedDialog(controller)
    dialog.choose_pad(1)
    dialog.resize(1200, 900)
    yield dialog, controller
    dialog.close()
    controller.store.close()


def test_the_marker_button_snaps_to_the_hit_and_logs_the_snapped_frame(snap_page):
    dialog, controller = snap_page
    assert dialog.snap_switch.isChecked()
    click_frame(dialog, int(0.37 * SR) + 120)  # 15 ms late
    assert dialog.place_marker()
    (frame,) = controller.markers(1)
    assert abs(frame - int(0.37 * SR)) <= 24 and frame != int(0.37 * SR) + 120
    click_frame(dialog, int(0.9 * SR))  # between the hits: stays
    assert dialog.place_marker() and int(0.9 * SR) in controller.markers(1)


def test_the_switch_turns_snapping_off_at_once(snap_page):
    dialog, controller = snap_page
    dialog.snap_switch.setChecked(False)
    assert controller.settings.snap_markers is False
    click_frame(dialog, int(0.37 * SR) + 120)
    assert dialog.place_marker() and controller.markers(1) == [int(0.37 * SR) + 120]
    dialog.snap_switch.setChecked(True)
    assert controller.settings.snap_markers is True


def test_the_snap_switch_is_on_the_page_like_the_other_switches(snap_page):
    dialog, _ = snap_page
    assert dialog.snap_switch.parent() is not None
    dialog.snap_switch.setChecked(False)
    QTest.mouseClick(dialog.snap_switch, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert dialog.snap_switch.isChecked() is True
