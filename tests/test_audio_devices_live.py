"""Choosing devices and the audio system while the app runs (no sound card, no PortAudio)."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import numpy as np
import pytest
from conftest import FakeSoundDevice, make_settings

from loopstation.audio import NO_MIC_TEXT, create_audio, enable_asio
from loopstation.audio.selection import resolve_choice
from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.config import RESTART_KEYS, Settings, parse_settings, restart_keys_changed

SR = 8000


def dev(
    name: str, hostapi: int, inputs: int = 0, outputs: int = 0, low_input: float = 0.01
) -> dict[str, Any]:
    return {
        "name": name, "hostapi": hostapi, "max_input_channels": inputs, "max_output_channels": outputs,
        "default_samplerate": 48000.0, "default_low_input_latency": low_input,
    }


def windows_sd(**kwargs: Any) -> FakeSoundDevice:
    return FakeSoundDevice(
        hostapis=[
            {"name": "MME", "default_input_device": 0, "default_output_device": 1},
            {"name": "Windows WASAPI", "default_input_device": 2, "default_output_device": 3},
        ],
        devices=[
            dev("Mikro", 0, inputs=1),                      # 0
            dev("Boxen", 0, outputs=2),                     # 1
            dev("Mikro", 1, inputs=1),                      # 2
            dev("Boxen", 1, outputs=2),                     # 3
            dev("Kids Mic", 1, inputs=1, low_input=0.02),   # 4
            dev("Kopfhörer", 1, outputs=2),                 # 5
        ],
        **kwargs,
    )


def make(device: FakeSoundDevice, platform: str = "win32", **names: str) -> SoundDeviceAudio:
    return SoundDeviceAudio(SR, 10, latency_seconds=0.0, sd=device, clock=lambda: 0.0,
                            platform=platform, **names)


# --------------------------------------------------------------- resolving


def test_empty_names_mean_the_default_device_of_the_platform_host_api() -> None:
    sd = windows_sd()
    assert resolve_choice(sd, "", "", "input", "win32").index == 2  # WASAPI, not MME
    assert resolve_choice(sd, "", "", "output", "win32").index == 3
    assert resolve_choice(sd, "", "MME", "output", "win32").index == 1


def test_a_named_device_is_found_inside_the_chosen_host_api() -> None:
    sd = windows_sd()
    assert resolve_choice(sd, "Kids Mic", "Windows WASAPI", "input", "win32").index == 4
    assert resolve_choice(sd, "Mikro", "MME", "input", "win32").index == 0
    assert resolve_choice(sd, "Mikro", "MME", "input", "win32").note == ""


def test_a_missing_device_or_host_api_falls_back_to_the_default_with_a_hint() -> None:
    sd = windows_sd()
    gone = resolve_choice(sd, "Weg", "Windows WASAPI", "output", "win32")
    assert gone.index == 3 and "Weg" in gone.note and "Systemstandard" in gone.note
    no_api = resolve_choice(sd, "", "ASIO", "output", "win32")
    assert no_api.index == 3 and "ASIO" in no_api.note


def test_without_any_device_the_system_default_is_left_to_portaudio() -> None:
    assert resolve_choice(FakeSoundDevice(), "", "", "input", "linux").index is None


# ------------------------------------------------------------ the backend


def test_the_streams_open_on_the_chosen_devices() -> None:
    sd = windows_sd()
    audio = make(sd, input_device="Kids Mic", output_device="Kopfhörer", hostapi="Windows WASAPI")
    assert sd.output.device == 5
    audio.start_recording()
    assert sd.input.device == 4
    assert audio.device_notice == ""


def test_wasapi_streams_convert_the_sample_rate_others_do_not() -> None:
    sd = windows_sd()
    make(sd, hostapi="Windows WASAPI")
    assert sd.output.extra_settings.auto_convert is True
    sd2 = windows_sd()
    make(sd2, hostapi="MME")
    assert sd2.output.extra_settings is None


def test_a_switch_closes_the_old_streams_and_opens_new_ones() -> None:
    sd = windows_sd()
    audio = make(sd, hostapi="Windows WASAPI")
    first = sd.output
    audio.start_recording()
    mic = sd.input
    note = audio.select_devices("Kids Mic", "Kopfhörer", "Windows WASAPI")
    assert note == ""
    assert first.closed and not first.active
    assert mic.closed  # a recording that was running is dropped
    assert sd.output is not first and sd.output.active and sd.output.device == 5
    assert audio.recording_seconds() == 0.0
    audio.start_recording()
    assert sd.input.device == 4


def test_voices_and_the_grid_keep_running_across_a_switch() -> None:
    sd = windows_sd(block=100)
    audio = make(sd, hostapi="Windows WASAPI")
    audio.set_grid(1000)
    tone = np.full(1000, 0.25, dtype=np.float32)
    audio.play(3, tone, loop=True)
    sd.step(3)
    audio.select_devices("", "Kopfhörer", "Windows WASAPI")
    assert audio.playing_pads() == {3}
    old_frames = len(sd.output_signal())
    sd.step(2)  # the new stream pulls on from the same frame counter
    after = sd.output_signal()[old_frames:]
    assert np.allclose(after, 0.25)  # still audible, same level
    assert audio.next_boundary_in() is not None


def test_a_missing_device_uses_the_default_and_says_so() -> None:
    sd = windows_sd()
    audio = make(sd, input_device="Weg", output_device="Auch weg", hostapi="Windows WASAPI")
    assert sd.output.device == 3
    assert "Weg" in audio.device_notice and "Auch weg" in audio.device_notice
    assert audio.available_input


def test_a_device_that_refuses_to_open_falls_back_to_the_default() -> None:
    sd = windows_sd(broken_devices=(5,))
    audio = make(sd, hostapi="Windows WASAPI")
    note = audio.select_devices("", "Kopfhörer", "Windows WASAPI")
    assert sd.output.device is None and sd.output.active
    assert "Wiedergabegerät" in note


def test_a_microphone_that_refuses_is_reported_and_the_default_is_tried() -> None:
    sd = windows_sd(broken_devices=(4,))
    audio = make(sd, hostapi="Windows WASAPI")
    note = audio.select_devices("Kids Mic", "", "Windows WASAPI")
    assert "Aufnahmegerät" in note
    assert audio.available_input
    audio.start_recording()
    assert sd.input.device is None


def test_a_switch_without_a_microphone_leaves_recording_unavailable() -> None:
    sd = windows_sd(has_input=False)
    audio = make(sd)
    assert not audio.available_input
    assert audio.start_recording() is False


def test_the_auto_latency_is_derived_again_for_the_new_devices() -> None:
    sd = windows_sd(input_latency=0.005, output_latency=0.0075)
    audio = SoundDeviceAudio(SR, 10, latency_seconds=None, sd=sd, clock=lambda: 0.0,
                             platform="win32", hostapi="Windows WASAPI")
    assert audio.reported_latency_ms() == pytest.approx(7.5 + 10.0)
    audio.select_devices("Kids Mic", "", "Windows WASAPI")
    assert audio.reported_latency_ms() == pytest.approx(7.5 + 20.0)
    sd.output_latency = 0.02  # the next output stream reports a larger delay
    audio.select_devices("Kids Mic", "Kopfhörer", "Windows WASAPI")
    assert audio.reported_latency_ms() == pytest.approx(20.0 + 20.0)
    audio.start_recording()  # "auto" uses the streams that are open now
    assert audio._latency_frames == round((0.005 + 0.02) * SR)


def test_the_catalog_for_the_settings_page_comes_from_the_backend() -> None:
    audio = make(windows_sd())
    groups = audio.device_groups("input")
    assert [g.name for g in groups] == ["MME", "Windows WASAPI"]
    assert [d.name for d in groups[1].devices] == ["Mikro", "Kids Mic"]


# ---------------------------------------------------------------- settings


def test_the_new_keys_have_empty_defaults_and_are_read_from_the_file() -> None:
    s = Settings()
    assert (s.input_device, s.output_device, s.audio_hostapi, s.asio) == ("", "", "", False)
    parsed = parse_settings({"input_device": " Kids Mic ", "audio_hostapi": "ALSA", "asio": True})
    assert parsed.input_device == "Kids Mic" and parsed.audio_hostapi == "ALSA" and parsed.asio


def test_asio_only_acts_after_a_restart() -> None:
    assert "asio" in RESTART_KEYS
    assert restart_keys_changed(Settings(), Settings(asio=True)) == ["asio"]
    assert restart_keys_changed(Settings(), Settings(input_device="X")) == []


# -------------------------------------------------------------------- ASIO


def test_asio_sets_the_variable_before_sounddevice_is_imported() -> None:
    env: dict[str, str] = {}
    seen: list[str | None] = []

    def importer() -> FakeSoundDevice:
        seen.append(env.get("SD_ENABLE_ASIO"))
        return windows_sd()

    audio, status = create_audio(Settings(asio=True, sample_rate=SR), importer, "win32", env)
    assert seen == ["1"]
    assert isinstance(audio, SoundDeviceAudio) and status is None


def test_without_the_switch_or_off_windows_the_variable_stays_unset() -> None:
    for platform, asio in (("win32", False), ("linux", True)):
        env: dict[str, str] = {}
        seen: list[str | None] = []

        def importer(env=env, seen=seen) -> FakeSoundDevice:
            seen.append(env.get("SD_ENABLE_ASIO"))
            return windows_sd()

        create_audio(Settings(asio=asio, sample_rate=SR), importer, platform, env)
        assert seen == [None] and "SD_ENABLE_ASIO" not in env


def test_enable_asio_writes_the_real_environment_only_when_asked() -> None:
    before = os.environ.get("SD_ENABLE_ASIO")
    enable_asio(False, "win32")
    assert os.environ.get("SD_ENABLE_ASIO") == before


def test_create_audio_passes_the_devices_from_the_settings() -> None:
    sd = windows_sd()
    settings = Settings(sample_rate=SR, output_device="Kopfhörer", input_device="Kids Mic",
                        audio_hostapi="Windows WASAPI")
    audio, status = create_audio(settings, lambda: sd, "win32", {})
    assert sd.output.device == 5 and status is None
    audio.start_recording()
    assert sd.input.device == 4


def test_create_audio_without_a_microphone_still_starts() -> None:
    audio, status = create_audio(Settings(sample_rate=SR), lambda: windows_sd(has_input=False), "win32", {})
    assert status == NO_MIC_TEXT and isinstance(audio, SoundDeviceAudio)


# -------------------------------------------------------------- controller


def make_controller(tmp_path, sd: FakeSoundDevice, **names: str):
    from loopstation.controller import Controller
    from loopstation.store import EventStore

    settings = make_settings(tmp_path, **names)
    audio = SoundDeviceAudio(settings.sample_rate, 10, sd=sd, clock=lambda: 0.0, platform="win32",
                             hostapi=settings.audio_hostapi)
    store = EventStore(tmp_path / "log", settings.pad_count)
    controller = Controller(store, audio, settings, clock=lambda: 0.0)
    return controller, audio


def test_applying_other_devices_reopens_the_streams_live(tmp_path) -> None:
    sd = windows_sd()
    controller, audio = make_controller(tmp_path, sd, audio_hostapi="Windows WASAPI")
    controller.apply_settings(replace(controller.settings, output_device="Kopfhörer"))
    assert sd.output.device == 5
    assert controller.settings.output_device == "Kopfhörer"
    assert controller.notice() and "Audio" in controller.notice()
    assert controller.device_notice == ""
    controller.shutdown()


def test_saving_other_settings_does_not_touch_the_streams(tmp_path) -> None:
    sd = windows_sd()
    controller, _audio = make_controller(tmp_path, sd, audio_hostapi="Windows WASAPI")
    before = len(sd.opened_outputs)
    controller.apply_settings(replace(controller.settings, loop_sync=False))
    assert len(sd.opened_outputs) == before
    controller.shutdown()


def test_a_missing_device_shows_up_as_a_status_hint(tmp_path) -> None:
    controller, _audio = make_controller(tmp_path, windows_sd(), audio_hostapi="Windows WASAPI")
    controller.apply_settings(replace(controller.settings, input_device="Weg"))
    assert "Weg" in controller.device_notice
    controller.shutdown()


def test_failing_to_reopen_keeps_the_old_names_and_tells_the_parents(tmp_path) -> None:
    sd = windows_sd()
    controller, audio = make_controller(tmp_path, sd, audio_hostapi="Windows WASAPI")

    def refuse(*_a: Any) -> str:
        raise RuntimeError("no device at all")

    audio.select_devices = refuse  # type: ignore[method-assign]
    controller.apply_settings(replace(controller.settings, output_device="Kopfhörer"))
    assert controller.settings.output_device == ""
    assert "neu starten" in (controller.notice() or "")
    controller.shutdown()


# -------------------------------------------------------------------- page


@pytest.fixture
def page(qapp, tmp_path):
    from PySide6.QtWidgets import QWidget

    from loopstation.gui.settings_page import SettingsDialog

    class Window(QWidget):
        """Stands in for the main window: the page looks for ``audio_devices`` on its parent."""

        audio_devices: Any = None

    sd = windows_sd()
    audio = SoundDeviceAudio(SR, 10, sd=sd, clock=lambda: 0.0, platform="win32",
                             hostapi="Windows WASAPI")
    window = Window()
    window.audio_devices = audio
    running = make_settings(tmp_path, audio_hostapi="Windows WASAPI")
    applied: list[Settings] = []

    def apply(new: Settings) -> list[str]:
        applied.append(new)
        audio.select_devices(new.input_device, new.output_device, new.audio_hostapi)
        return restart_keys_changed(running, new)

    dialog = SettingsDialog(tmp_path / "settings.toml", running, apply, template=None, parent=window)
    yield dialog, applied, audio, sd
    dialog.close()
    window.close()


def _labels(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def test_the_page_lists_the_devices_of_the_chosen_audio_system(page) -> None:
    dialog, *_ = page
    hostapi = dialog.editors["audio_hostapi"].list  # a list of radio buttons, one per audio system
    assert hostapi.labels() == ["MME", "Windows WASAPI"]
    assert hostapi.value() == "Windows WASAPI"
    assert hostapi.by_name["Windows WASAPI"].isChecked()
    assert _labels(dialog.editors["input_device"].box) == ["Systemstandard", "Mikro", "Kids Mic"]
    assert _labels(dialog.editors["output_device"].box) == ["Systemstandard", "Boxen", "Kopfhörer"]
    hostapi.select("MME")
    assert _labels(dialog.editors["input_device"].box) == ["Systemstandard", "Mikro"]


def test_choosing_devices_saves_by_name_and_restarts_the_streams(page, tmp_path) -> None:
    from loopstation.config import load_settings

    dialog, applied, _audio, sd = page
    mic = dialog.editors["input_device"].box
    mic.setCurrentIndex(mic.findData("Kids Mic"))
    out = dialog.editors["output_device"].box
    out.setCurrentIndex(out.findData("Kopfhörer"))
    assert dialog.save()
    saved = load_settings(tmp_path / "settings.toml")
    assert (saved.input_device, saved.output_device) == ("Kids Mic", "Kopfhörer")
    assert applied[-1].output_device == "Kopfhörer"
    assert sd.output.device == 5
    assert "neu gestartet" in dialog.message.text()


def test_a_saved_device_that_is_gone_stays_listed_and_marked(qapp, tmp_path, page) -> None:
    dialog, *_ = page
    box = dialog.editors["output_device"].box
    dialog.editors["output_device"].set_choices([("Boxen", "Boxen")], "Altes Gerät")
    assert _labels(box)[-1] == "Altes Gerät (nicht gefunden)"
    assert dialog.editors["output_device"].value() == "Altes Gerät"


def test_the_page_shows_the_auto_latency_of_the_devices(page) -> None:
    dialog, *_ = page
    assert "ms" in dialog.latency_hint.text()


def test_a_bluetooth_device_gets_a_warning(page) -> None:
    dialog, *_ = page
    dialog.editors["output_device"].set_choices([("BT-Kopfhörer", "BT-Kopfhörer")], "BT-Kopfhörer")
    dialog._update_device_hints()
    assert "Bluetooth" in dialog.device_hint.text()


def test_asio_says_honestly_that_it_acts_after_a_restart(page, tmp_path) -> None:
    from loopstation.config import load_settings

    dialog, applied, *_ = page
    dialog.editors["asio"]._box.setChecked(True)
    assert dialog.save()
    assert load_settings(tmp_path / "settings.toml").asio is True
    assert "wirkt nach Neustart" in dialog.message.text() and "ASIO" in dialog.message.text()
    assert applied[-1].asio is True


def test_without_an_audio_engine_the_page_keeps_the_saved_names(qapp, tmp_path) -> None:
    from loopstation.gui.settings_page import SettingsDialog

    running = make_settings(tmp_path, input_device="Kids Mic", audio_hostapi="Windows WASAPI")
    dialog = SettingsDialog(tmp_path / "settings.toml", running, lambda new: [], template=None)
    assert dialog.editors["input_device"].value() == "Kids Mic"
    assert dialog.collect().audio_hostapi == "Windows WASAPI"
    dialog.close()
