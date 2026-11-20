"""Erweitert: the parents' tempo (rule 8), the metronome and the waveform (offscreen, no hardware).

Controller on FakeAudio (clap mode where onsets matter), the quiet tick on the
real SoundDeviceAudio with a stand-in device to see it pass the ceiling, and the
widgets rendered offscreen.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from conftest import FakeAudio, FakeClock, FakeSoundDevice, make_settings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from loopstation.audio import metronome
from loopstation.audio.dynamics import block_peak, db_to_gain
from loopstation.audio.samples import load_wav
from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.config import ConfigError, Settings, parse_settings
from loopstation.controller import Controller, Mode
from loopstation.gui.advanced_page import AdvancedPage, loop_title
from loopstation.gui.grid_panel import GridPanel
from loopstation.gui.tempo_card import MetronomeCard, MetronomeStrip, TempoCard
from loopstation.gui.waveform import WAVE_COLOR, WaveformWidget, beat_lines, peak_columns
from loopstation.state import master_source
from loopstation.store import EventStore

SR = 8000


def build(tmp_path, clock: FakeClock, claps=None, **overrides) -> tuple[Controller, FakeAudio]:
    overrides.setdefault("auto_grid", True)
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = FakeAudio(clock)
    audio.clap_times = claps
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def events(controller: Controller, type_: str) -> list[dict]:
    lines = controller.store.log_path.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["type"] == type_]


def bar_frames(bpm: float, beats: int = 4) -> int:
    return round(beats * 60 * SR / bpm)


# --- the parents' tempo sets master_set with source parent_bpm (rule 8) ------------------------


def test_the_parents_tempo_replaces_the_grid_with_master_set_from_parent_bpm(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    assert master_source(controller.store.state.master) == "onset"
    sample = controller.pad(0).sample
    before = (tmp_path / "samples" / sample).read_bytes()

    assert controller.set_parent_grid(120, "3/4") is True

    master = controller.store.state.master
    assert master["frames"] == bar_frames(120, 3) and master["rate"] == SR
    assert master["source"] == "parent_bpm" and master["signature"] == "3/4"
    assert events(controller, "master_set")[-1]["data"]["source"] == "parent_bpm"
    info = controller.grid_info()
    assert round(info.bpm) == 120 and info.signature == "3/4" and info.source == "parent_bpm"
    assert audio.grid == master["frames"]
    assert (tmp_path / "samples" / sample).read_bytes() == before  # refitted, never rewritten


def test_onsets_set_no_grid_after_the_parents_tempo_on_an_empty_session(tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    assert controller.set_parent_grid(96, "4/4") is True
    assert controller.store.state.master is None and not events(controller, "master_set")
    assert controller.parent_grid() == (96.0, "4/4")

    record(controller, clock, 0, 3.0)  # two claps 0.5 s apart would make a 2 s onset bar

    master = controller.store.state.master
    assert master["frames"] == bar_frames(96) == 20000
    assert master["source"] == "parent_bpm" and master["signature"] == "4/4" and master["pad"] == 0
    stop = events(controller, "record_stop")[-1]["data"]
    assert stop["grid"] == "parent_bpm"
    assert stop["frames"] == 2 * master["frames"]  # 3 s on a 2.5 s bar fit to two bars, as any grid does
    assert stop["shift"] > 0  # the onset still aligns this recording
    assert audio.grid == master["frames"]


def test_the_parents_tempo_stays_after_the_session_is_emptied(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    controller.set_parent_grid(96, "4/4")
    record(controller, clock, 0, 3.0)
    controller.delete_all()
    assert controller.store.state.master is None
    record(controller, clock, 1, 3.0)
    assert controller.store.state.master["source"] == "parent_bpm"


def test_a_later_recording_cannot_move_the_parents_grid(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    controller.set_parent_grid(100, "4/4")
    grid = controller.store.state.master
    record(controller, clock, 1, 5.0)
    assert controller.store.state.master == grid


def test_the_parents_tempo_without_auto_grid_does_not_shift_the_recording(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0], auto_grid=False)
    controller.set_parent_grid(96, "4/4")
    record(controller, clock, 0, 3.0)
    assert "shift" not in events(controller, "record_stop")[-1]["data"]
    assert controller.store.state.master["frames"] == bar_frames(96)


@pytest.mark.parametrize("bpm, signature", [(39, "4/4"), (201, "4/4"), (96, "5/4")])
def test_a_tempo_outside_the_window_or_an_unknown_signature_is_refused(tmp_path, clock, bpm, signature):
    controller, _ = build(tmp_path, clock)
    assert controller.set_parent_grid(bpm, signature) is False
    assert controller.parent_grid() is None


def test_the_parents_tempo_needs_loop_sync_and_waits_for_a_running_recording(tmp_path, clock):
    controller, _ = build(tmp_path, clock, loop_sync=False)
    assert controller.set_parent_grid(96, "4/4") is False
    controller, _ = build(tmp_path / "b", clock)
    controller.press(0)  # recording
    assert controller.set_parent_grid(96, "4/4") is False


def test_running_loops_start_again_on_the_new_bars_without_touching_their_files(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    assert controller.pad(0).looping
    audio.calls.clear()

    controller.set_parent_grid(60, "4/4")  # one bar = 4 s

    assert ("stop", 0, False) in audio.calls and ("play", 0, True) in audio.calls
    data, loop = audio.voices[0]
    assert loop and len(data) == bar_frames(60) == 4 * SR  # padded to the new bar on the fly
    assert controller.pad(0).looping
    assert audio.grid == bar_frames(60)


def test_measured_grid_comes_back_with_the_button(tmp_path, clock):
    controller, _ = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    measured = dict(controller.store.state.master)
    controller.set_parent_grid(60, "4/4")
    assert controller.use_measured_grid() is True
    assert controller.store.state.master == measured
    assert controller.parent_grid() is None
    assert controller.use_measured_grid() is False  # nothing left to give back


def test_giving_the_grid_back_without_a_measured_one_only_ends_the_override(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    controller.set_parent_grid(60, "4/4")
    record(controller, clock, 0, 2.0)
    assert controller.store.state.master["source"] == "parent_bpm"
    assert controller.use_measured_grid() is True
    assert controller.parent_grid() is None
    assert controller.store.state.master["source"] == "parent_bpm"  # bars stay until the session ends


def test_the_parents_tempo_survives_a_restart_through_the_log(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.set_parent_grid(120, "6/8")
    controller.shutdown()
    again, _ = build(tmp_path, clock)
    tempo, signature = again.parent_grid()
    assert round(tempo) == 120 and signature == "6/8"


def test_old_logs_without_a_source_still_read_as_before(tmp_path, clock):
    controller, _ = build(tmp_path, clock, auto_grid=False)
    record(controller, clock, 0, 2.0)
    assert controller.parent_grid() is None
    assert controller.grid_info().source == "duration"
    assert controller.metronome_period() == pytest.approx(0.5)  # 2 s bar, 4/4 by default


# --- metronome: the period follows the grid ----------------------------------------------------


@pytest.mark.parametrize("bpm, signature, beats", [(120, "4/4", 4), (90, "3/4", 3), (100, "6/8", 2)])
def test_the_metronome_period_follows_the_grid(tmp_path, clock, bpm, signature, beats):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.set_parent_grid(bpm, signature)
    period = controller.metronome_period()
    assert period == pytest.approx(60 / bpm, rel=1e-3)
    assert period * beats == pytest.approx(controller.bar_seconds())
    controller.set_parent_grid(60, signature)
    assert controller.metronome_period() == pytest.approx(1.0, rel=1e-3)


def test_there_is_no_metronome_without_a_grid(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    assert controller.metronome_period() is None and controller.beat_position() is None
    controller.settings = replace(controller.settings, metronome_tone=True)
    controller.tick()
    assert audio.effects == []


def test_the_beat_position_follows_the_loop_start_of_the_audio_engine(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.set_parent_grid(120, "4/4")  # bar = 2 s, beat = 0.5 s
    audio.boundary_in = 1.5  # a quarter bar played
    assert controller.beat_position() == pytest.approx(1.0)
    audio.boundary_in = 0.5
    assert controller.beat_position() == pytest.approx(3.0)


def test_without_running_loops_the_beat_counts_on_on_the_clock(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    controller.set_parent_grid(120, "4/4")
    audio.boundary_in = 1.5
    assert controller.beat_position() == pytest.approx(1.0)
    audio.boundary_in = None  # loops stopped: it goes on from where it was
    clock.advance(0.5)
    assert controller.beat_position() == pytest.approx(2.0)
    clock.advance(1.5)
    assert controller.beat_position() == pytest.approx(1.0)  # wrapped into the next bar


# --- metronome tone: quiet, on the beat, off by default ----------------------------------------


def tone_controller(tmp_path, clock, **overrides):
    controller, audio = build(tmp_path, clock, metronome_tone=True, **overrides)
    record(controller, clock, 0, 2.0)
    controller.set_parent_grid(120, "4/4")  # 0.5 s beats
    audio.effects.clear()
    return controller, audio


def test_the_tone_is_off_by_default(tmp_path, clock):
    assert Settings().metronome_tone is False
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0, 2.0)
    audio.effects.clear()  # the recording beeps are not the metronome
    audio.boundary_in = 0.5
    controller.tick()
    assert audio.effects == []


def test_the_tick_is_handed_over_shortly_before_the_beat_and_lands_on_it(tmp_path, clock):
    controller, audio = tone_controller(tmp_path, clock)
    audio.boundary_in = 1.9  # 0.1 s into the bar: next beat in 0.4 s, too early
    controller.tick()
    assert audio.effects == []
    audio.boundary_in = 1.45  # 0.55 s: next beat (2) in 0.45 s, still too early
    controller.tick()
    assert audio.effects == []
    audio.boundary_in = 1.06  # 0.94 s: the next beat is 0.06 s away
    controller.tick()
    assert len(audio.effects) == 1
    effect = audio.effects[0]
    lead = round(0.06 * SR)
    assert not np.any(effect[: lead - 2])  # silence up to the beat ...
    assert np.max(np.abs(effect[lead + 20:])) > 0  # ... then the tick
    assert len(effect) == lead + round(metronome.TICK_SECONDS * SR)


def test_one_tick_per_beat_even_if_the_gui_ticks_often(tmp_path, clock):
    controller, audio = tone_controller(tmp_path, clock)
    for boundary in (1.06, 1.04, 1.02):  # three GUI ticks before the same beat
        audio.boundary_in = boundary
        clock.advance(0.02)
        controller.tick()
    assert len(audio.effects) == 1
    audio.boundary_in = 0.56  # half a second later: the next beat
    clock.advance(0.5 - 0.06)
    controller.tick()
    assert len(audio.effects) == 2


def test_the_first_beat_of_the_bar_sounds_different_and_all_ticks_are_quiet(tmp_path, clock):
    controller, audio = tone_controller(tmp_path, clock, metronome_level_db=-24.0)
    audio.boundary_in = 0.06  # the bar start is 0.06 s away: beat 1
    controller.tick()
    audio.boundary_in = 1.56  # beat 2
    clock.advance(0.5)
    controller.tick()
    accent, plain = audio.effects
    lead = lambda e: int(np.argmax(np.abs(e) > 0))  # noqa: E731
    first, second = accent[lead(accent):], plain[lead(plain):]
    n = min(len(first), len(second))
    assert not np.allclose(first[:n], second[:n])
    assert block_peak(accent) <= db_to_gain(-24.0) + 1e-6 and block_peak(plain) <= db_to_gain(-24.0) + 1e-6


def test_switching_the_tone_off_stops_it(tmp_path, clock):
    controller, audio = tone_controller(tmp_path, clock)
    audio.boundary_in = 1.06
    controller.tick()
    assert len(audio.effects) == 1
    controller.apply_settings(replace(controller.settings, metronome_tone=False))
    clock.advance(0.5)
    audio.boundary_in = 0.56
    controller.tick()
    assert len(audio.effects) == 1


def test_the_tone_runs_through_master_volume_and_ceiling():
    device = FakeSoundDevice(block=100)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=0.0, sd=device, clock=lambda: 0.0,
                             volume=1.0, ceiling_db=-30.0)
    audio.set_grid(None)
    loud = metronome.tick(SR, -6.0)  # the loudest the setting allows
    audio.play_effect(metronome.delayed(loud, 50))
    device.step(20)
    out = device.output_signal()
    ceiling = db_to_gain(-30.0)
    assert 0 < block_peak(out) <= ceiling + 1e-6  # limited, not muted
    audio.set_volume(0.0)
    device.step(20)
    audio.play_effect(metronome.tick(SR, -6.0))
    device.step(20)
    assert block_peak(device.output_signal()[-100 * 20:]) < 1e-3  # the master volume moves it, too


def test_metronome_settings_are_validated_and_quiet_by_default():
    assert Settings().metronome_level_db == -20.0
    assert parse_settings({"metronome_tone": True}).metronome_tone is True
    assert parse_settings({"metronome_level_db": -30}).metronome_level_db == -30.0
    for raw in ({"metronome_tone": "an"}, {"metronome_level_db": -3}, {"metronome_level_db": -41}):
        with pytest.raises(ConfigError, match="metronome"):
            parse_settings(raw, "settings.toml")


# --- waveform ----------------------------------------------------------------------------------


def test_peak_columns_are_scaled_to_the_loudest_part():
    data = np.concatenate([np.full(100, 0.1), np.full(100, -0.4), np.zeros(100)]).astype(np.float32)
    peaks = peak_columns(data, 3)
    assert peaks.tolist() == pytest.approx([0.25, 1.0, 0.0])
    assert peak_columns(np.zeros(50, dtype=np.float32), 5).tolist() == [0.0] * 5
    assert peak_columns(np.zeros(0, dtype=np.float32), 4).tolist() == [0.0] * 4
    assert len(peak_columns(np.ones(3, dtype=np.float32), 10)) == 10  # fewer frames than columns


def test_beat_lines_follow_the_bar_and_mark_its_start():
    lines = beat_lines(8000, 4000, 4)  # two bars of four beats
    assert [round(p, 3) for p, _, _ in lines] == [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]
    assert [start for _, start, _ in lines] == [True, False, False, False, True, False, False, False]
    assert [n for _, _, n in lines] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert beat_lines(8000, None, 4) == [] and beat_lines(0, 4000, 4) == []
    assert [n for _, _, n in beat_lines(3000, 3000, 3)] == [1, 2, 3]


def wave_pixels(widget: WaveformWidget) -> list[QColor]:
    image = widget.grab().toImage()
    return [image.pixelColor(x, y) for x in range(0, image.width(), 3) for y in range(0, image.height(), 3)]


def near(color: QColor, other: QColor) -> bool:
    return (abs(color.red() - other.red()) < 12 and abs(color.green() - other.green()) < 12
            and abs(color.blue() - other.blue()) < 12)


def test_the_waveform_renders_offscreen_with_its_beat_lines(qapp):
    widget = WaveformWidget()
    widget.resize(900, 180)
    t = np.arange(8000) / SR
    widget.set_loop((0.6 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 4000, 4)
    assert len(widget.lines()) == 8
    cyan = QColor(WAVE_COLOR)
    assert any(near(c, cyan) for c in wave_pixels(widget))
    widget.set_loop(None, None, 4)  # an empty pad shows no wave
    assert widget.lines() == []
    assert not any(near(c, cyan) for c in wave_pixels(widget))


def test_loop_titles_say_how_the_loop_sits_on_the_grid():
    assert loop_title(5, 20000, 20000, 20000, SR) == "Pad 6 · Aufnahme 2,50 s · 1 Takt · im Raster"
    assert loop_title(0, 12000, 16000, 8000, SR) == (
        "Pad 1 · Aufnahme 1,50 s · 2 Takte · wird ans Raster angepasst")
    assert loop_title(1, 12000, 12000, None, SR) == "Pad 2 · Aufnahme 1,50 s · freie Länge"
    assert loop_title(2, None, None, None, SR) == "Pad 3 · noch kein Loop"


# --- the pages -------------------------------------------------------------------------------


@pytest.fixture
def page(qapp, tmp_path, clock):
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    dialog = AdvancedPage(controller, export_dir=tmp_path / "out")
    yield dialog, controller, audio
    dialog.close()
    controller.store.close()


@pytest.fixture
def tempo(qapp, tmp_path, clock):
    """The tempo correction and the current-bar card of the "Takt & Loop" area."""
    controller, audio = build(tmp_path, clock, claps=[0.5, 1.0])
    record(controller, clock, 0, 3.0)
    card, grid_panel = TempoCard(controller), GridPanel(controller)
    yield card, grid_panel, controller, audio
    card.close()
    grid_panel.close()
    controller.store.close()


def test_the_page_shows_the_loop_of_the_session(page):
    dialog, controller, _ = page
    assert dialog.pad == 0
    assert dialog.wave_title.text().startswith("Pad 1 · Aufnahme 2,00 s")
    assert len(dialog.waveform.lines()) == 4
    dialog.choose_pad(5)
    assert dialog.waveform.lines() == [] and "noch kein Loop" in dialog.wave_title.text()
    assert not dialog.save_button.isEnabled()  # nothing to save on an empty pad


def test_the_page_saves_the_shown_loop_as_wav(page, tmp_path):
    dialog, controller, _ = page
    assert "pad01_" in dialog.target_label.text()
    path = dialog.export_loop()
    assert path is not None and path.parent == tmp_path / "out" and path.suffix == ".wav"
    assert path.exists() and dialog.last_path == path
    assert "Gespeichert" in dialog.loop_message.text()
    dialog.choose_pad(5)
    assert dialog.export_loop() is None
    assert "keine lesbare Aufnahme" in dialog.loop_message.text()


def test_the_cue_switch_of_the_page_acts_at_once(page):
    dialog, controller, _ = page
    assert controller.settings.export_cue_points is True
    dialog.cue_switch.setChecked(False)
    assert controller.settings.export_cue_points is False


def test_the_tempo_card_shows_the_grid_of_the_session(tempo):
    card, grid_panel, controller, _ = tempo
    assert grid_panel.texts()[0][1] == "120 BPM"
    assert card.bpm_spin.value() == 120 and card.signature == "4/4"
    assert not card.measured_button.isEnabled()  # nothing of the parents' set yet


def test_the_tempo_card_sets_the_parents_tempo_and_gives_the_measured_one_back(tempo):
    card, grid_panel, controller, audio = tempo
    card.bpm_spin.setValue(90)
    card.signature_chips["3/4"].click()
    assert card.apply_parent_grid() is True
    info = controller.grid_info()
    assert round(info.bpm) == 90 and info.signature == "3/4" and info.source == "parent_bpm"
    grid_panel.refresh()
    assert grid_panel.texts()[3][1] == "Eltern-BPM"
    assert card.measured_button.isEnabled()
    assert card.tempo_status.text().startswith("Vorgegeben: 90 BPM · 3/4")
    assert card.use_measured_grid() is True
    assert controller.grid_info().source == "onset" and card.bpm_spin.value() == 120


def test_the_tempo_card_says_so_when_the_tempo_cannot_be_set(qapp, tmp_path, clock):
    controller, _ = build(tmp_path, clock, loop_sync=False)
    card = TempoCard(controller)
    try:
        assert card.apply_parent_grid() is False
        assert "Loops im Takt halten" in card.tempo_status.text()
    finally:
        card.close()


def test_the_refusal_goes_away_once_setting_the_tempo_is_possible_again(qapp, tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    card = TempoCard(controller)
    try:
        controller.press(0)  # a recording runs
        assert card.apply_parent_grid() is False
        assert "Das geht gerade nicht" in card.tempo_status.text()
        card.refresh()
        assert "Das geht gerade nicht" in card.tempo_status.text()
        clock.advance(2.0)
        controller.press(0)
        card.refresh()
        assert card.tempo_status.text() == ""
    finally:
        card.close()


def test_the_first_recording_on_the_parents_bar_is_fitted_not_stretched(tmp_path, clock):
    controller, _ = build(tmp_path, clock, auto_grid=False)
    controller.set_parent_grid(96, "4/4")
    grid = bar_frames(96)
    record(controller, clock, 0, grid / SR * 0.95)  # 5 % short: would be stretched on a later take
    data = load_wav(tmp_path / "samples" / controller.pad(0).sample, SR)
    assert len(data) == grid
    assert np.abs(data[-grid // 20 :]).max() == 0.0  # padded with silence, content not stretched


def test_the_tempo_card_on_an_empty_session_waits_for_the_first_recording(qapp, tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    card, metronome_card = TempoCard(controller), MetronomeCard(controller)
    try:
        card.bpm_spin.setValue(72)
        assert card.apply_parent_grid() is True
        assert "gilt ab der nächsten ersten Aufnahme" in card.tempo_status.text()
        assert metronome_card.strip.beats is None
    finally:
        card.close()
        metronome_card.close()


def test_the_metronome_strip_marks_the_current_beat(tempo):
    _card, _grid, controller, audio = tempo
    metronome_card = MetronomeCard(controller)
    audio.boundary_in = 1.2  # 0.8 s into a 2 s bar: beat 2 of 4 (0-based 1)
    metronome_card.refresh()
    assert metronome_card.strip.beats == 4 and metronome_card.strip.active == 1
    assert "120 BPM" in metronome_card.period_label.text() and "0,50 s" in metronome_card.period_label.text()
    metronome_card.close()


def test_the_metronome_tone_switch_of_the_area_acts_at_once(tempo, tmp_path):
    from loopstation.gui.settings_page import SettingsDialog

    _card, _grid, controller, _audio = tempo
    dialog = SettingsDialog(
        tmp_path / "settings.toml", controller.settings, lambda new: [], controller=controller)
    try:
        dialog.editors["metronome_tone"]._box.setChecked(True)
        assert controller.settings.metronome_tone is True
        dialog.editors["metronome_tone"]._box.setChecked(False)
        assert controller.settings.metronome_tone is False
    finally:
        dialog.close()


def test_the_strip_renders_with_and_without_a_grid(qapp):
    strip = MetronomeStrip()
    strip.resize(400, 72)
    strip.set_state(4, 2)
    assert not strip.grab().toImage().isNull()
    strip.set_state(None, None)
    assert not strip.grab().toImage().isNull()


def test_the_parents_area_offers_erweitert_and_the_child_page_has_nothing_of_it(qapp, tmp_path, clock):
    from conftest import FakeAudio as Audio
    from PySide6.QtWidgets import QAbstractButton, QDialog

    from loopstation.gui.main_window import MainWindow

    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    controller = Controller(store, Audio(clock), settings, clock=clock)
    window = MainWindow(controller, None, [], config_path=tmp_path / "settings.toml")

    class Auto(QDialog):
        def __init__(self, result):
            super().__init__()
            self._result = result

        def exec(self):
            return self._result

    try:
        child = [b.text() for b in window.frame.findChildren(QAbstractButton)]
        assert not any(word in text for text in child for word in ("Erweitert", "Metronom", "BPM"))
        shown, opened = [], []
        window.gate_factory = lambda _parent: Auto(QDialog.DialogCode.Accepted)
        window.settings_factory = lambda *a: shown.append(a) or Auto(QDialog.DialogCode.Rejected)
        window.advanced_factory = lambda c, p: opened.append((c, p)) or QWidget()
        window.open_parent_area()
        pages = {page.key: page for page in shown[0][5]}
        assert pages["advanced"].label == "Erweitert" and pages["advanced"].icon == "layers"
        pages["advanced"].build()
        assert opened == [(controller, None)]
    finally:
        window.timer.stop()
        window.close()
        store.close()
