"""Novation Launchpad support: detection, pad/note mapping and LED colours.

Everything here runs in the GUI thread: ``LaunchpadController.poll`` is
called from a Qt timer and drains pending MIDI messages without blocking,
so no MIDI callback ever runs on a foreign thread.

Hardware access goes through the small ``MidiPorts`` interface, which tests
replace with a fake. Without mido/python-rtmidi the controller simply stays
disconnected and the on-screen pads keep working.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

PROGRAMMER = "programmer"
LEGACY = "legacy"

# Palette velocities for programmer-layout devices (MK2, Mini MK3, X, Pro MK3).
PROGRAMMER_COLORS = {"off": 0, "white": 3, "red": 5, "yellow": 13, "green": 21}
# Legacy devices only have red/green LEDs. "Empty" is shown as off.
LEGACY_COLORS = {"off": 0x00, "white": 0x00, "red": 0x0F, "yellow": 0x3E, "green": 0x3C}

GRID_SIZE = 8  # all supported devices have an 8x8 pad grid


@dataclass(frozen=True)
class LaunchpadModel:
    name: str
    layout: str
    # SysEx payload (without F0/F7) that switches the device to programmer mode.
    sysex: tuple[int, ...] | None = None


MINI_MK3 = LaunchpadModel("Launchpad Mini MK3", PROGRAMMER, (0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01))
LAUNCHPAD_X = LaunchpadModel("Launchpad X", PROGRAMMER, (0x00, 0x20, 0x29, 0x02, 0x0C, 0x0E, 0x01))
PRO_MK3 = LaunchpadModel("Launchpad Pro MK3", PROGRAMMER, (0x00, 0x20, 0x29, 0x02, 0x0E, 0x0E, 0x01))
MK2 = LaunchpadModel("Launchpad MK2", PROGRAMMER)
LEGACY_MODEL = LaunchpadModel("Launchpad", LEGACY)


def identify(port_name: str) -> LaunchpadModel | None:
    """Return the model a MIDI port name belongs to, or None.

    The original Launchpad Pro (MK1) uses a different protocol and is not
    supported; it is not matched so it cannot receive wrong messages.
    """
    name = port_name.lower()
    if "lpminimk3" in name or "launchpad mini mk3" in name:
        return MINI_MK3
    if "lpx" in name or "launchpad x" in name:
        return LAUNCHPAD_X
    if "lppromk3" in name or "launchpad pro mk3" in name:
        return PRO_MK3
    if "launchpad mk2" in name:
        return MK2
    if "launchpad pro" in name:
        return None
    if "launchpad" in name:  # Launchpad, Launchpad S, Launchpad Mini MK1/MK2
        return LEGACY_MODEL
    return None


def _port_score(port_name: str) -> int:
    """Prefer the device's MIDI port over its DAW port."""
    tokens = port_name.replace("(", " ").replace(")", " ").replace(":", " ").split()
    upper = {t.upper() for t in tokens}
    if upper & {"DAW", "DA", "MIDIIN2", "MIDIOUT2"}:
        return -1
    if upper & {"MIDI", "MI"}:
        return 1
    return 0


def pick_port(names: Iterable[str], model: LaunchpadModel | None = None) -> tuple[str, LaunchpadModel] | None:
    """Pick the best port among ``names`` (optionally restricted to ``model``)."""
    best: tuple[int, str, LaunchpadModel] | None = None
    for name in names:
        found = identify(name)
        if found is None or (model is not None and found != model):
            continue
        score = _port_score(name)
        if best is None or score > best[0]:
            best = (score, name, found)
    return (best[1], best[2]) if best else None


class PadMapping:
    """Maps pad indices of a rows x cols grid to device notes and back.

    Pad index = row * cols + col with row 0 at the top. Only the top-left
    8x8 part of a larger grid is mapped.
    """

    def __init__(self, layout: str, rows: int, cols: int) -> None:
        self.layout = layout
        self.cols = cols
        self.rows_visible = min(rows, GRID_SIZE)
        self.cols_visible = min(cols, GRID_SIZE)

    def note_for(self, pad: int) -> int | None:
        row, col = divmod(pad, self.cols)
        if row >= self.rows_visible or col >= self.cols_visible:
            return None
        if self.layout == PROGRAMMER:
            return (GRID_SIZE - row) * 10 + (col + 1)
        return row * 16 + col

    def pad_for(self, note: int) -> int | None:
        if self.layout == PROGRAMMER:
            row, col = GRID_SIZE - note // 10, note % 10 - 1
        else:
            row, col = divmod(note, 16)
        if not (0 <= row < self.rows_visible and 0 <= col < self.cols_visible):
            return None
        return row * self.cols + col

    def mapped_pads(self) -> list[int]:
        return [r * self.cols + c for r in range(self.rows_visible) for c in range(self.cols_visible)]


class MidiPorts(Protocol):
    """The four MIDI operations the controller needs (faked in tests)."""

    def input_names(self) -> list[str]: ...
    def output_names(self) -> list[str]: ...
    def open_input(self, name: str) -> Any: ...
    def open_output(self, name: str) -> Any: ...


class MidoPorts:
    """``MidiPorts`` on top of mido with the python-rtmidi backend."""

    def __init__(self) -> None:
        import mido  # deferred: the app must run without MIDI libraries

        mido.set_backend("mido.backends.rtmidi", load=True)
        self._mido = mido

    def input_names(self) -> list[str]:
        return list(self._mido.get_input_names())

    def output_names(self) -> list[str]:
        return list(self._mido.get_output_names())

    def open_input(self, name: str) -> Any:
        return self._mido.open_input(name)

    def open_output(self, name: str) -> Any:
        return self._mido.open_output(name)


def _message(kind: str, **fields: Any) -> Any:
    import mido

    return mido.Message(kind, **fields)


class LaunchpadController:
    """Connects to a Launchpad, reports pad presses and mirrors pad colours."""

    def __init__(
        self,
        ports_factory: Callable[[], MidiPorts] | None,
        rows: int,
        cols: int,
        clock: Callable[[], float] = time.monotonic,
        rescan_interval: float = 2.0,
        message_factory: Callable[..., Any] = _message,
    ) -> None:
        # Called lazily on the first scan; None disables Launchpad support.
        self._ports_factory = ports_factory
        self._ports: MidiPorts | None = None
        self.rows, self.cols = rows, cols
        self._clock = clock
        self._rescan_interval = rescan_interval
        self._make = message_factory
        self._next_scan = 0.0
        self._inport: Any = None
        self._outport: Any = None
        self._out_name: str | None = None
        self.model: LaunchpadModel | None = None
        self._mapping: PadMapping | None = None
        self._wanted: dict[int, str] = {}
        self._sent: dict[int, int] = {}

    @property
    def connected(self) -> bool:
        return self._outport is not None

    @property
    def status_text(self) -> str | None:
        return "Launchpad verbunden" if self.connected else None

    # ---------------------------------------------------------- connection

    def _get_ports(self) -> MidiPorts | None:
        if self._ports is None and self._ports_factory is not None:
            try:
                self._ports = self._ports_factory()
            except Exception as exc:
                log.info("MIDI not available, Launchpad support off: %s", exc)
                self._ports_factory = None
        return self._ports

    def _scan(self) -> None:
        """Look for a Launchpad and connect to it (called every few seconds)."""
        ports = self._get_ports()
        if ports is None:
            return
        try:
            found_in = pick_port(ports.input_names())
            if found_in is None:
                return
            in_name, model = found_in
            found_out = pick_port(ports.output_names(), model)
            if found_out is None:
                return
            out_name = found_out[0]
            self._inport = ports.open_input(in_name)
            self._outport = ports.open_output(out_name)
        except Exception as exc:
            log.warning("connecting to Launchpad failed: %s", exc)
            self._disconnect()
            return
        self._out_name = out_name
        self.model = model
        self._mapping = PadMapping(model.layout, self.rows, self.cols)
        self._sent = {}
        log.info("Launchpad connected: %s (%s)", model.name, out_name)
        if model.sysex:
            self._send(self._make("sysex", data=list(model.sysex)))
        self._flush_colors()

    def _still_present(self) -> bool:
        ports = self._get_ports()
        try:
            return ports is not None and self._out_name in ports.output_names()
        except Exception:
            return False

    def _disconnect(self) -> None:
        for port in (self._inport, self._outport):
            if port is not None:
                with contextlib.suppress(Exception):
                    port.close()
        self._inport = self._outport = None
        self._out_name = None
        self.model = None
        self._mapping = None
        self._sent = {}

    def _send(self, message: Any) -> bool:
        if self._outport is None:
            return False
        try:
            self._outport.send(message)
        except Exception as exc:
            log.warning("Launchpad send failed, treating it as unplugged: %s", exc)
            self._disconnect()
            return False
        return True

    # ----------------------------------------------------------------- API

    def poll(self) -> list[int]:
        """Return pads pressed since the last call; rescan when disconnected."""
        now = self._clock()
        if not self.connected:
            if now >= self._next_scan:
                self._next_scan = now + self._rescan_interval
                self._scan()
            return []
        if now >= self._next_scan:
            self._next_scan = now + self._rescan_interval
            if not self._still_present():
                log.info("Launchpad unplugged")
                self._disconnect()
                return []
        pressed: list[int] = []
        try:
            for message in self._inport.iter_pending():
                if message.type == "note_on" and message.velocity > 0 and self._mapping:
                    pad = self._mapping.pad_for(message.note)
                    if pad is not None:
                        pressed.append(pad)
        except Exception as exc:
            log.warning("Launchpad read failed, treating it as unplugged: %s", exc)
            self._disconnect()
        return pressed

    def set_colors(self, colors: dict[int, str]) -> None:
        """Remember the wanted colours and send only what changed."""
        self._wanted = dict(colors)
        self._flush_colors()

    def _flush_colors(self) -> None:
        if not self.connected or self._mapping is None or self.model is None:
            return
        palette = PROGRAMMER_COLORS if self.model.layout == PROGRAMMER else LEGACY_COLORS
        for pad in self._mapping.mapped_pads():
            velocity = palette[self._wanted.get(pad, "white")]
            if self._sent.get(pad) == velocity:
                continue
            note = self._mapping.note_for(pad)
            if not self._send(self._make("note_on", note=note, velocity=velocity)):
                return
            self._sent[pad] = velocity

    def close(self) -> None:
        """Switch all mapped LEDs off and release the ports."""
        if self.connected and self._mapping is not None:
            for pad in self._mapping.mapped_pads():
                if not self._send(self._make("note_on", note=self._mapping.note_for(pad), velocity=0)):
                    break
        self._disconnect()
