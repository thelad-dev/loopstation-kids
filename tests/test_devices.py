"""Device and host API catalog against a stand-in sounddevice (no sound card)."""

from __future__ import annotations

from typing import Any

from conftest import FakeSoundDevice

from loopstation.audio.devices import (
    DeviceRef,
    all_devices,
    default_device,
    default_hostapi,
    list_devices,
    ref_for,
    resolve_device,
)


def dev(name: str, hostapi: int, inputs: int = 0, outputs: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": 48000.0,
    }


def windows_sd() -> FakeSoundDevice:
    return FakeSoundDevice(
        hostapis=[
            {"name": "MME", "default_input_device": 0, "default_output_device": 1},
            {"name": "Windows WASAPI", "default_input_device": 2, "default_output_device": 3},
            {"name": "ASIO", "default_input_device": -1, "default_output_device": -1},
        ],
        devices=[
            dev("Mikro USB", 0, inputs=1),
            dev("Lautsprecher", 0, outputs=2),
            dev("Mikro USB", 1, inputs=1),
            dev("Lautsprecher", 1, outputs=2),
            dev("Headset", 1, inputs=1, outputs=2),
        ],
    )


def test_groups_devices_by_hostapi_in_portaudio_order() -> None:
    groups = list_devices(windows_sd(), "output")
    assert [g.name for g in groups] == ["MME", "Windows WASAPI"]  # ASIO has no device
    assert [d.name for d in groups[1].devices] == ["Lautsprecher", "Headset"]
    assert groups[1].default_index == 3


def test_input_and_output_lists_only_hold_matching_devices() -> None:
    sd = windows_sd()
    inputs = {d.name for g in list_devices(sd, "input") for d in g.devices}
    outputs = {d.name for g in list_devices(sd, "output") for d in g.devices}
    assert inputs == {"Mikro USB", "Headset"}
    assert outputs == {"Lautsprecher", "Headset"}


def test_platform_default_hostapi() -> None:
    names = ["MME", "Windows DirectSound", "Windows WASAPI", "ASIO"]
    assert default_hostapi(names, "win32") == "Windows WASAPI"
    assert default_hostapi(["MME", "Windows DirectSound"], "win32") == "Windows DirectSound"
    assert default_hostapi(["MME"], "win32") == "MME"
    assert default_hostapi(["JACK Audio Connection Kit", "ALSA"], "linux") == "ALSA"
    assert default_hostapi(["Core Audio"], "darwin") == "Core Audio"
    assert default_hostapi(["Foo", "Bar"], "freebsd14") == "Foo"
    assert default_hostapi([], "linux") is None


def test_default_device_follows_the_platform_hostapi() -> None:
    sd = windows_sd()
    assert default_device(sd, "input", "win32").index == 2  # WASAPI, not MME
    assert default_device(sd, "output", "win32").index == 3
    assert default_device(FakeSoundDevice(), "output", "linux") is None


def test_saved_device_is_found_again_after_the_index_moved() -> None:
    sd = windows_sd()
    ref = ref_for(all_devices(sd)[4], all_devices(sd))  # Headset on WASAPI
    assert ref == DeviceRef("Headset", "Windows WASAPI", 0)
    # A new device is plugged in first: every index shifts by one.
    sd.devices.insert(0, dev("Neu", 0, inputs=1, outputs=1))
    found = resolve_device(sd, ref, "input")
    assert found.index == 5 and found.device.name == "Headset" and found.note == ""


def test_name_on_another_hostapi_is_not_a_match() -> None:
    result = resolve_device(windows_sd(), DeviceRef("Headset", "MME"), "input")
    assert result.index is None


def test_missing_device_falls_back_to_system_default_with_a_hint() -> None:
    result = resolve_device(windows_sd(), DeviceRef("Weg", "Windows WASAPI"), "output")
    assert result.index is None and result.device is None
    assert "Weg" in result.note and "Systemstandard" in result.note


def test_a_device_without_the_needed_direction_counts_as_missing() -> None:
    # "Lautsprecher" exists, but cannot record.
    result = resolve_device(windows_sd(), DeviceRef("Lautsprecher", "MME"), "input")
    assert result.index is None and result.note


def test_no_reference_means_system_default_without_a_hint() -> None:
    result = resolve_device(windows_sd(), None, "input")
    assert result.index is None and result.note == ""


def test_equally_named_devices_get_distinct_references() -> None:
    sd = FakeSoundDevice(
        hostapis=[{"name": "ALSA", "default_input_device": 0, "default_output_device": -1}],
        devices=[dev("USB Audio", 0, inputs=1), dev("USB Audio", 0, inputs=1)],
    )
    devices = all_devices(sd)
    first, second = (ref_for(d, devices) for d in devices)
    assert (first.occurrence, second.occurrence) == (0, 1)
    assert resolve_device(sd, second, "input").index == 1
    # One of the two is unplugged: the survivor is taken, not a fallback.
    sd.devices.pop()
    assert resolve_device(sd, second, "input").index == 0
