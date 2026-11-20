"""Which devices the two streams open, from the saved names (pure, nothing is opened).

Settings keep a device by name and the host API by name (``devices.DeviceRef``),
never by PortAudio index. An empty name is "Systemstandard": the default device of
the chosen host API. An empty host API is the platform default (plan 11.1): WASAPI
on Windows, ALSA on Linux. A saved device or host API that is gone resolves to the
default of the host API that is there, plus a short hint.
"""

from __future__ import annotations

from typing import Any

from loopstation.audio.devices import (
    DeviceRef,
    Kind,
    Resolution,
    default_hostapi,
    list_devices,
    resolve_device,
)

# Host API that needs the extra "convert the sample rate" flag in shared mode.
WASAPI = "Windows WASAPI"


def resolve_choice(sd: Any, name: str, hostapi: str, kind: Kind, platform: str) -> Resolution:
    """Index of the device to open for ``kind`` (``None`` = let PortAudio choose), with a hint if needed."""
    groups = list_devices(sd, kind)
    available = [g.name for g in groups]
    notes = []
    chosen = hostapi
    if hostapi and hostapi not in available:
        notes.append(f"Audio-System „{hostapi}“ nicht gefunden, Standard wird benutzt.")
        chosen = ""
    if not chosen:
        chosen = default_hostapi(available, platform) or ""
    group = next((g for g in groups if g.name == chosen), None)
    standard = None
    if group is not None and group.default_index is not None:
        standard = next((d for d in group.devices if d.index == group.default_index), None)
    if name and group is not None:
        found = resolve_device(sd, DeviceRef(name, group.name), kind)
        if found.device is not None:
            return Resolution(found.index, found.device, " ".join(notes))
        notes.append(found.note)
    elif name:
        what = "Aufnahmegerät" if kind == "input" else "Wiedergabegerät"
        notes.append(f"{what} „{name}“ nicht gefunden, Systemstandard wird benutzt.")
    index = standard.index if standard is not None else None
    return Resolution(index, standard, " ".join(notes))
