"""Export of single loops and of the sum over N bars (pure renderer, no hardware)."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile
from conftest import FakeClock
from test_controller import build, record

from loopstation import export as ex
from loopstation.audio.dynamics import db_to_gain
from loopstation.audio.sync import soften_seam
from loopstation.controller import Mode

RATE = 8000
GRID = 2000  # a bar of 0.25 s


def tone(frames: int, level: float = 0.5, freq: float = 440.0) -> np.ndarray:
    t = np.arange(frames, dtype=np.float32) / RATE
    return (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def ramp(frames: int) -> np.ndarray:
    """Every frame different, so a wrong start or a wrong repeat shows."""
    return np.linspace(0.01, 0.2, frames, dtype=np.float32)


def spec(loops, bars=4, **kw) -> ex.SumSpec:
    kw.setdefault("grid", GRID)
    kw.setdefault("soft_seam", False)
    kw.setdefault("fade_out", False)
    pads = [ex.ExportPad(i, d) for i, d in enumerate(loops)]
    return ex.SumSpec(sample_rate=RATE, bars=bars, loops=pads, **kw)


# ---------------------------------------------------------------- length


@pytest.mark.parametrize("bars", [1, 4, 8, 16, 32])
def test_length_is_exactly_bars_times_grid(bars):
    out = ex.render_sum(spec([tone(GRID), tone(2 * GRID)], bars=bars))
    assert len(out) == bars * GRID
    assert out.dtype == np.float32


def test_odd_grid_stays_in_whole_frames():
    grid = 1999  # not divisible by anything useful
    out = ex.render_sum(spec([tone(grid)], bars=7, grid=grid))
    assert len(out) == 7 * grid


def test_plan_reports_length_and_tempo():
    info = ex.plan_sum(spec([tone(GRID)], bars=8))
    assert info.frames == 8 * GRID and info.seconds == pytest.approx(2.0)
    assert info.bpm == pytest.approx(4 * 60 * RATE / GRID) and not info.stand_in


@pytest.mark.parametrize("bars", [0, -1, ex.MAX_BARS + 1])
def test_bar_count_is_checked(bars):
    with pytest.raises(ex.ExportError, match="Takte"):
        ex.plan_sum(spec([tone(GRID)], bars=bars))


# ------------------------------------------------------- repeating like live


def test_a_one_bar_loop_repeats_every_bar_from_its_start():
    data = ramp(GRID)
    out = ex.render_sum(spec([data], bars=3))
    for bar in range(3):
        assert np.array_equal(out[bar * GRID:(bar + 1) * GRID], data)


def test_a_multi_bar_loop_starts_at_the_first_frame_and_is_cut_at_the_end():
    data = ramp(2 * GRID)  # two bars long
    out = ex.render_sum(spec([data], bars=3))
    assert np.array_equal(out[:2 * GRID], data)
    assert np.array_equal(out[2 * GRID:], data[:GRID])  # third bar: the loop starts again, then ends mid-loop


def test_loops_are_added():
    a, b = ramp(GRID), tone(GRID, 0.1)
    out = ex.render_sum(spec([a, b], bars=2))
    assert np.allclose(out[:GRID], a + b, atol=1e-6)


def test_seam_is_softened_like_live_when_switched_on():
    data = tone(2 * GRID)
    out = ex.render_sum(spec([data], bars=4, soft_seam=True))
    voice = soften_seam(data, RATE)
    assert np.array_equal(out[:2 * GRID], voice)
    assert np.array_equal(out[2 * GRID:], voice)
    assert out[2 * GRID] == 0.0 and out[2 * GRID - 1] == 0.0  # no step where the end meets the start


def test_one_shots_are_added_once_at_the_start_only_when_given():
    loop, shot = tone(GRID, 0.2), ex.ExportPad(5, ramp(GRID // 2))
    without = ex.render_sum(spec([loop], bars=2))
    with_shot = ex.render_sum(spec([loop], bars=2, one_shots=[shot]))
    assert np.allclose(with_shot[:GRID // 2], without[:GRID // 2] + shot.data, atol=1e-6)
    assert np.array_equal(with_shot[GRID // 2:], without[GRID // 2:])


def test_one_shots_alone_make_a_sum_on_the_grid():
    out = ex.render_sum(spec([], bars=2, one_shots=[ex.ExportPad(0, ramp(100))]))
    assert len(out) == 2 * GRID and np.array_equal(out[:100], ramp(100)) and not out[100:].any()


# ----------------------------------------------------------- level chain


def test_volume_scales_the_sum_before_the_limiter():
    data = tone(GRID, 0.4)
    quiet = ex.render_sum(spec([data], volume=0.5))
    assert np.allclose(quiet, 0.5 * data[np.arange(len(quiet)) % GRID], atol=1e-6)


@pytest.mark.parametrize("ceiling_db", [-6.0, -12.0, -1.0, 0.0])
def test_peak_never_passes_the_ceiling_even_for_a_loud_sum(ceiling_db):
    loud = [tone(GRID, 0.9, f) for f in (220.0, 330.0, 440.0, 550.0)]
    out = ex.render_sum(spec(loud, bars=8, volume=1.0, ceiling_db=ceiling_db))
    assert float(np.abs(out).max()) <= db_to_gain(ceiling_db) + 1e-6
    assert float(np.abs(out).max()) > 0.5 * db_to_gain(ceiling_db)  # limited, not silenced


def test_limiter_is_the_live_one_so_a_quiet_sum_passes_unchanged():
    data = tone(GRID, 0.1)
    out = ex.render_sum(spec([data], bars=2, ceiling_db=-6.0))
    assert np.array_equal(out[:GRID], data)


def test_lowest_ceiling_does_not_divide_by_zero():
    out = ex.render_sum(spec([tone(GRID)], ceiling_db=-30.0))
    assert np.isfinite(out).all() and float(np.abs(out).max()) <= db_to_gain(-30.0) + 1e-6


# -------------------------------------------------------------- fade out


def test_fade_out_ends_on_zero_and_leaves_the_rest_alone():
    loop = tone(GRID, 0.3)
    plain = ex.render_sum(spec([loop], bars=4))
    faded = ex.render_sum(spec([loop], bars=4, fade_out=True))
    n = ex.fade_out_frames(GRID, RATE)
    assert n == round(ex.FADE_OUT_SECONDS * RATE)  # 15 ms
    assert faded[-1] == 0.0
    assert np.array_equal(faded[:-n], plain[:-n])
    assert (np.abs(faded[-n:]) <= np.abs(plain[-n:]) + 1e-9).all()
    assert len(faded) == len(plain)


def test_fade_out_is_at_most_a_quarter_of_a_bar():
    assert ex.fade_out_frames(100, RATE) == 25
    assert ex.fade_out_frames(10 * RATE, RATE) == round(ex.FADE_OUT_SECONDS * RATE)


# ------------------------------------------------------------- no grid


def test_without_a_grid_nothing_is_guessed():
    with pytest.raises(ex.ExportError) as caught:
        ex.render_sum(spec([tone(GRID)], grid=None))
    assert "keinen Takt" in str(caught.value) and "Notbehelf" in str(caught.value)


def test_stand_in_uses_the_longest_loop_and_says_so_in_the_file(tmp_path):
    loops = [tone(GRID), tone(3 * GRID)]
    stand_in = spec(loops, bars=2, grid=None, longest_as_bar=True)
    info = ex.plan_sum(stand_in)
    assert info.stand_in and info.bar_frames == 3 * GRID and info.bpm is None
    path = tmp_path / "out" / "sum.wav"
    ex.export_sum(path, stand_in)
    with soundfile.SoundFile(str(path)) as handle:
        assert len(handle) == 2 * 3 * GRID
        assert "NOTBEHELF" in handle.comment


def test_a_real_grid_is_not_marked_as_a_stand_in(tmp_path):
    path = tmp_path / "sum.wav"
    ex.export_sum(path, spec([tone(GRID)], bars=4))
    with soundfile.SoundFile(str(path)) as handle:
        assert "NOTBEHELF" not in handle.comment and "4 Takte" in handle.comment


def test_stand_in_needs_a_loop():
    with pytest.raises(ex.ExportError):
        ex.plan_sum(spec([], grid=None, longest_as_bar=True, one_shots=[ex.ExportPad(0, tone(10))]))


def test_nothing_selected_is_an_error():
    with pytest.raises(ex.ExportError, match="nichts zu exportieren"):
        ex.plan_sum(spec([]))


# ----------------------------------------------------------------- files


def test_sum_is_written_as_24_bit_mono_wav_at_the_session_rate(tmp_path):
    path = tmp_path / "x" / "sum.wav"
    info = ex.export_sum(path, spec([tone(GRID, 0.3)], bars=8))
    assert info.frames == 8 * GRID
    with soundfile.SoundFile(str(path)) as handle:
        assert (handle.samplerate, handle.channels, handle.subtype, handle.format) == (
            RATE, 1, "PCM_24", "WAV")
        assert len(handle) == 8 * GRID
    assert not list(path.parent.glob("*.tmp"))  # written atomically


def test_written_sum_matches_the_render(tmp_path):
    s = spec([tone(GRID, 0.3)], bars=4, soft_seam=True)
    ex.export_sum(tmp_path / "sum.wav", s)
    data, _rate = soundfile.read(str(tmp_path / "sum.wav"), dtype="float32")
    assert np.allclose(data, ex.render_sum(s), atol=2 / 2**23)


def test_a_failed_write_leaves_no_partial_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    with pytest.raises(ex.ExportError, match="schreiben"):
        ex.export_sum(blocker / "sum.wav", spec([tone(GRID)]))
    assert list(tmp_path.iterdir()) == [blocker]


def test_single_loop_is_exported_unchanged(tmp_path):
    data = tone(GRID, 0.8)  # louder than any ceiling: a single loop gets no limiter
    path = tmp_path / "pad01.wav"
    ex.export_loop(path, data, RATE, "Loopstation Pad 1")
    back, rate = soundfile.read(str(path), dtype="float32")
    assert rate == RATE and len(back) == len(data)
    assert np.allclose(back, data, atol=2 / 2**23)


def test_exporting_an_empty_loop_is_refused(tmp_path):
    with pytest.raises(ex.ExportError):
        ex.export_loop(tmp_path / "e.wav", np.zeros(0, dtype=np.float32), RATE)


def test_no_mp3_and_no_external_program_anywhere_in_the_export():
    import inspect

    source = inspect.getsource(ex).lower()
    assert "ffmpeg" not in source and "subprocess" not in source and ".mp3" not in source


# ----------------------------------------------------- from the controller


def session(tmp_path, clock: FakeClock, **overrides):
    """Pad 0: one bar (1 s), pad 1: two bars; pad 0 and pad 2 loop, pad 1 is a one-shot, pad 3 is empty."""
    controller, audio = build(tmp_path, clock, **overrides)
    record(controller, clock, 0, 1.0)
    record(controller, clock, 1, 2.0)
    record(controller, clock, 2, 1.0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.press(2)
    controller.set_mode(Mode.PLAY)
    return controller, audio


def test_selection_follows_what_loops_now(tmp_path, clock):
    controller, _ = session(tmp_path, clock)
    assert ex.selected_pads(controller, all_pads=False) == ([0, 2], [1])
    assert ex.selected_pads(controller, all_pads=True) == ([0, 1, 2], [])


def test_spec_takes_grid_volume_ceiling_and_seam_from_the_session(tmp_path, clock):
    controller, _ = session(tmp_path, clock, volume=0.25, max_level_db=-12.0, soft_seam=False)
    built = ex.build_spec(controller, bars=4)
    assert built.grid == 8000 and built.sample_rate == 8000
    assert built.volume == controller.volume and built.ceiling_db == -12.0 and built.soft_seam is False
    assert [p.pad for p in built.loops] == [0, 2] and built.one_shots == []
    assert ex.build_spec(controller, 4, all_pads=True).loops[1].data.shape[0] == 2 * 8000
    assert [p.pad for p in ex.build_spec(controller, 4, include_one_shots=True).one_shots] == [1]


def test_sum_of_a_real_session_has_the_exact_length_and_respects_the_ceiling(tmp_path, clock):
    controller, _ = session(tmp_path, clock, max_level_db=-12.0)
    controller.set_volume(1.0)
    out = ex.render_sum(ex.build_spec(controller, bars=8, all_pads=True))
    assert len(out) == 8 * controller.grid_frames()
    assert float(np.abs(out).max()) <= db_to_gain(-12.0) + 1e-6


def test_session_without_loop_sync_has_no_grid_and_asks_instead_of_guessing(tmp_path, clock):
    controller, _ = session(tmp_path, clock, loop_sync=False)
    assert controller.grid_frames() is None
    with pytest.raises(ex.ExportError, match="keinen Takt"):
        ex.render_sum(ex.build_spec(controller, bars=4))
    out = ex.render_sum(ex.build_spec(controller, bars=2, longest_as_bar=True))
    assert len(out) == 2 * 8000


def test_a_missing_sample_file_is_reported_with_the_pad(tmp_path, clock):
    controller, _ = session(tmp_path, clock)
    name = controller.pad(0).sample
    controller._cache.pop(name)
    (tmp_path / "samples" / name).unlink()
    with pytest.raises(ex.ExportError, match="Pad 1"):
        ex.build_spec(controller, bars=4)
