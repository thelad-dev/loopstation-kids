"""Audio device and host API catalog (pure functions over an injected ``sd``).

Nothing here opens a stream. Every function takes the ``sounddevice`` module
(or a stand-in, like ``SoundDeviceAudio(sd=...)``), so tests need no sound
card. The platform is injected as a ``sys.platform`` string for the same reason.

Devices are saved by a stable reference (name, host API name, occurrence), not
by PortAudio index: indices shift when a device is plugged in or out. A saved
reference that no longer exists resolves to the system default plus a hint.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["input", "output"]

# Host API names as PortAudio reports them, best default first (plan 11.1, 12.1).
# DirectSound and MME stay in the list as fallbacks, not as recommendations.
PLATFORM_PREFERENCE: dict[str, tuple[str, ...]] = {
    "win32": ("Windows WASAPI", "Windows DirectSound", "MME"),
    "linux": ("ALSA", "JACK Audio Connection Kit"),
    "darwin": ("Core Audio",),
}


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    def channels(self, kind: Kind) -> int:
        return self.max_input_channels if kind == "input" else self.max_output_channels


@dataclass(frozen=True)
class DeviceRef:
    """Stable reference to a device, safe to store in settings or a set.

    ``occurrence`` tells equally named devices of one host API apart (0 is the
    first one in PortAudio order).
    """

    name: str
    hostapi: str
    occurrence: int = 0


@dataclass(frozen=True)
class HostApiGroup:
    name: str
    devices: tuple[AudioDevice, ...]
    default_index: int | None  # the host API's own default device for this kind


@dataclass(frozen=True)
class Resolution:
    """Outcome of finding a saved device again.

    ``index`` is ``None`` for the system default (pass ``device=None`` to
    PortAudio). ``note`` is empty unless the saved device was not found.
    """

    index: int | None
    device: AudioDevice | None
    note: str = ""


def _hostapi_names(sd: Any) -> list[str]:
    return [str(h["name"]) for h in sd.query_hostapis()]


def all_devices(sd: Any) -> list[AudioDevice]:
    names = _hostapi_names(sd)
    found = []
    for position, raw in enumerate(sd.query_devices()):
        api = int(raw["hostapi"])
        found.append(
            AudioDevice(
                index=int(raw.get("index", position)),
                name=str(raw["name"]),
                hostapi=names[api] if 0 <= api < len(names) else "",
                max_input_channels=int(raw["max_input_channels"]),
                max_output_channels=int(raw["max_output_channels"]),
                default_samplerate=float(raw.get("default_samplerate", 0.0)),
            )
        )
    return found


def list_devices(sd: Any, kind: Kind) -> list[HostApiGroup]:
    """Devices that can record (``input``) or play (``output``), grouped by host API.

    Host APIs without such a device are left out; the host API order of
    PortAudio is kept.
    """
    devices = all_devices(sd)
    groups = []
    for api in sd.query_hostapis():
        name = str(api["name"])
        members = tuple(d for d in devices if d.hostapi == name and d.channels(kind) > 0)
        if not members:
            continue
        default = int(api.get(f"default_{kind}_device", -1))
        groups.append(HostApiGroup(name, members, default if default >= 0 else None))
    return groups


def default_hostapi(available: Sequence[str], platform: str) -> str | None:
    """The host API this app starts with on ``platform`` (a ``sys.platform`` value).

    Falls back to the first available one, e.g. an unknown platform or a
    machine without the preferred API.
    """
    for name in PLATFORM_PREFERENCE.get(_platform_key(platform), ()):
        if name in available:
            return name
    return available[0] if available else None


def _platform_key(platform: str) -> str:
    for key in PLATFORM_PREFERENCE:
        if platform.startswith(key):
            return key
    return platform


def default_device(sd: Any, kind: Kind, platform: str) -> AudioDevice | None:
    """The platform default host API's default device, or ``None`` if there is none."""
    groups = list_devices(sd, kind)
    chosen = default_hostapi([g.name for g in groups], platform)
    for group in groups:
        if group.name == chosen and group.default_index is not None:
            return next((d for d in group.devices if d.index == group.default_index), None)
    return None


def ref_for(device: AudioDevice, devices: Sequence[AudioDevice]) -> DeviceRef:
    """Stable reference for ``device``; ``devices`` is the full list (``all_devices``)."""
    same = [d for d in devices if d.name == device.name and d.hostapi == device.hostapi]
    occurrence = next((i for i, d in enumerate(same) if d.index == device.index), 0)
    return DeviceRef(device.name, device.hostapi, occurrence)


def resolve_device(sd: Any, ref: DeviceRef | None, kind: Kind) -> Resolution:
    """Find a saved device again by name and host API, whatever its index is now.

    No reference means the system default, silently. A reference whose device
    is gone also resolves to the system default, with a hint in ``note``. With
    fewer equally named devices than before, the first of them is taken.
    """
    if ref is None:
        return Resolution(None, None)
    matches = [
        d
        for d in all_devices(sd)
        if d.name == ref.name and d.hostapi == ref.hostapi and d.channels(kind) > 0
    ]
    if not matches:
        what = "Aufnahmegerät" if kind == "input" else "Wiedergabegerät"
        note = f"{what} „{ref.name}“ ({ref.hostapi}) nicht gefunden, Systemstandard wird benutzt."
        return Resolution(None, None, note)
    chosen = matches[ref.occurrence] if ref.occurrence < len(matches) else matches[0]
    return Resolution(chosen.index, chosen)
