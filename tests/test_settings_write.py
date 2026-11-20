"""Writing settings.toml and taking settings over while the app runs (no hardware)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import fields, replace
from pathlib import Path

import pytest
from conftest import FakeAudio, make_settings

from loopstation import config
from loopstation.config import (
    RESTART_KEYS,
    SETTING_COMMENTS,
    ConfigError,
    Settings,
    load_settings,
    parse_settings,
    render_settings_text,
    restart_keys_changed,
    write_settings,
)
from loopstation.controller import LIVE_SETTINGS, Controller
from loopstation.store import EventStore

SHIPPED = Path(__file__).resolve().parent.parent / "settings.toml"


def test_roundtrip_settings_to_file_to_settings(tmp_path):
    settings = Settings(rows=4, cols=5, max_record_seconds=12.5, sample_rate=48000, sound_effects=False,
                        fullscreen=True, launchpad=False, loop_sync=False, latency_ms=85.5,
                        data_dir=Path("daten"))
    path = tmp_path / "settings.toml"
    write_settings(path, settings, SHIPPED.read_text(encoding="utf-8"))
    assert load_settings(path) == settings


def test_roundtrip_with_auto_latency_and_defaults(tmp_path):
    path = tmp_path / "settings.toml"
    write_settings(path, Settings())
    assert load_settings(path) == Settings()
    assert 'latency_ms = "auto"' in path.read_text(encoding="utf-8")


def test_comments_and_layout_survive_a_write(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text(SHIPPED.read_text(encoding="utf-8"), encoding="utf-8")
    write_settings(path, replace(Settings(), loop_sync=False, max_record_seconds=20.0))
    before = SHIPPED.read_text(encoding="utf-8").splitlines()
    after = path.read_text(encoding="utf-8").splitlines()
    comments = [line for line in before if line.startswith("#")]
    assert [line for line in after if line.startswith("#")] == comments
    changed = {a for a, b in zip(after, before, strict=True) if a != b}
    assert changed == {"loop_sync = false", "max_record_seconds = 20"}


def test_trailing_comment_on_a_value_line_is_kept(tmp_path):
    text = render_settings_text('rows = 3  # drei Zeilen\n', replace(Settings(), rows=5))
    assert text.splitlines()[0] == "rows = 5  # drei Zeilen"


def test_missing_keys_are_appended_with_their_comment(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("# eigene Datei\nrows = 3\n", encoding="utf-8")
    write_settings(path, Settings())
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# eigene Datei\nrows = 3\n")
    assert f"# {SETTING_COMMENTS['loop_sync']}\nloop_sync = true" in text
    assert load_settings(path) == Settings()


def test_new_file_starts_from_the_template(tmp_path):
    path = tmp_path / "sub" / "settings.toml"
    write_settings(path, Settings(rows=2), SHIPPED.read_text(encoding="utf-8"))
    assert "Fehlt diese Datei" in path.read_text(encoding="utf-8")
    assert load_settings(path).rows == 2


def test_every_setting_has_a_comment_and_restart_keys_exist():
    names = {f.name for f in fields(Settings)}
    assert names <= set(SETTING_COMMENTS)
    assert set(RESTART_KEYS) <= names


def test_shipped_file_says_which_values_need_a_restart():
    lines = SHIPPED.read_text(encoding="utf-8").splitlines()
    assert not any(line == "# Nach einer Änderung die Loopstation neu starten." for line in lines)
    for key in RESTART_KEYS:
        block = []
        index = next(i for i, line in enumerate(lines) if line.startswith(f"{key} ="))
        # rows and cols share one comment block; skip a directly preceding assignment line
        while index > 0 and (lines[index - 1].startswith("#") or "=" in lines[index - 1]):
            index -= 1
            block.append(lines[index])
        assert any("Neustart" in line for line in block), key


@pytest.mark.parametrize("raw", [{"rows": 99}, {"loop_sync": "ja"}, {"latency_ms": "viel"},
                                 {"max_record_seconds": 0}, {"data_dir": " "}])
def test_invalid_input_is_refused_with_the_loader_message(tmp_path, raw):
    path = tmp_path / "settings.toml"
    with pytest.raises(ConfigError) as from_page:
        parse_settings(raw, str(path))
    path.write_text("\n".join(f"{k} = {config.format_toml_value(k, v)}" for k, v in raw.items()),
                    encoding="utf-8")
    with pytest.raises(ConfigError) as from_file:
        load_settings(path)
    assert str(from_page.value) == str(from_file.value)


def test_write_is_atomic_temp_then_replace(tmp_path, monkeypatch):
    path = tmp_path / "settings.toml"
    path.write_text("rows = 3\n", encoding="utf-8")
    calls = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: calls.append((Path(a), Path(b))) or real(a, b))
    write_settings(path, Settings(rows=6))
    assert calls == [(path.with_name("settings.toml.tmp"), path)]
    assert not path.with_name("settings.toml.tmp").exists()


def test_failed_write_leaves_the_old_file_and_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "settings.toml"
    path.write_text("rows = 3\n", encoding="utf-8")

    def boom(_a, _b):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_settings(path, Settings(rows=6))
    assert path.read_text(encoding="utf-8") == "rows = 3\n"
    assert list(tmp_path.iterdir()) == [path]


def test_written_file_is_valid_toml_for_odd_paths(tmp_path):
    path = tmp_path / "settings.toml"
    odd = Settings(data_dir=Path('mit "Anführungszeichen"'))
    write_settings(path, odd)
    assert tomllib.loads(path.read_text(encoding="utf-8"))["data_dir"] == 'mit "Anführungszeichen"'


def test_resolve_config_path_is_absolute_even_without_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.resolve_config_path() == (tmp_path / "settings.toml").resolve()
    assert config.resolve_config_path(Path("x.toml")) == (tmp_path / "x.toml").resolve()
    assert not (tmp_path / "settings.toml").exists()


def test_restart_keys_changed():
    base = Settings()
    assert restart_keys_changed(base, replace(base, loop_sync=False)) == []
    assert restart_keys_changed(base, replace(base, rows=4, sample_rate=48000)) == ["rows", "sample_rate"]


# ---------------------------------------------------------------- live


@pytest.fixture
def controller(tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    ctrl = Controller(store, FakeAudio(clock), settings, clock=clock)
    yield ctrl
    store.close()


def test_live_values_are_taken_over_without_a_restart(controller):
    new = replace(controller.settings, loop_sync=False, sound_effects=False, max_record_seconds=30.0,
                  launchpad=False, fullscreen=True, latency_ms=120.0)
    assert controller.apply_settings(new) == []
    for key in LIVE_SETTINGS:
        assert getattr(controller.settings, key) == getattr(new, key)


def test_sound_effects_off_takes_effect_for_the_next_recording(controller, clock):
    controller.press(0)
    clock.advance(1)
    controller.press(0)
    assert len(controller.audio.effects) == 2
    controller.apply_settings(replace(controller.settings, sound_effects=False))
    controller.press(1)
    clock.advance(1)
    controller.press(1)
    assert len(controller.audio.effects) == 2


def test_max_record_seconds_applies_live(controller, clock):
    controller.apply_settings(replace(controller.settings, max_record_seconds=2.0))
    controller.press(0)
    assert controller.recording_limit() == 2.0
    clock.advance(2.5)
    controller.tick()
    assert controller.recording_pad is None


def test_loop_sync_off_drops_the_grid_live(controller, clock):
    controller.press(0)
    clock.advance(1)
    controller.press(0)
    assert controller.audio.grid is not None
    controller.apply_settings(replace(controller.settings, loop_sync=False))
    assert controller.audio.grid is None


def test_restart_values_are_not_applied_but_reported(controller):
    running = controller.settings
    new = replace(running, rows=5, cols=6, sample_rate=48000, data_dir=Path("anderswo"), loop_sync=False)
    assert controller.apply_settings(new) == ["rows", "cols", "sample_rate", "data_dir"]
    assert (controller.settings.rows, controller.settings.cols) == (running.rows, running.cols)
    assert controller.settings.sample_rate == running.sample_rate
    assert controller.settings.data_dir == running.data_dir
    assert controller.settings.loop_sync is False  # the live one still went through


def test_backend_without_configure_is_fine_and_with_it_gets_the_values(controller):
    seen = []
    controller.audio.configure = lambda seconds, latency: seen.append((seconds, latency))
    controller.apply_settings(replace(controller.settings, max_record_seconds=7.0, latency_ms=250.0))
    controller.apply_settings(replace(controller.settings, latency_ms=None))
    assert seen == [(7.0, 0.25), (7.0, None)]


def test_refusing_backend_leaves_the_settings_untouched(controller):
    before = controller.settings

    def refuse(_seconds, _latency):
        raise RuntimeError("no")

    controller.audio.configure = refuse
    with pytest.raises(RuntimeError):
        controller.apply_settings(replace(before, loop_sync=False, max_record_seconds=40.0))
    assert controller.settings is before


def test_sounddevice_audio_configure_changes_limit_and_latency_for_the_next_recording():
    from conftest import FakeSoundDevice

    from loopstation.audio.sounddevice_backend import SoundDeviceAudio

    audio = SoundDeviceAudio(8000, 10, latency_seconds=0.0, sd=FakeSoundDevice(), clock=lambda: 0.0)
    audio.configure(20.0, 0.25)
    assert audio._max_frames == 21 * 8000
    assert audio.start_recording()
    assert audio._latency_frames == 2000
    audio.stop_recording()
    audio.configure(20.0, None)
    assert audio._latency_seconds is None
