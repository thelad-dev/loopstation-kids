"""Launchpad detection, note mapping and LED updates with a fake MIDI port."""

from __future__ import annotations

import pytest
from conftest import FakeClock, FakeMessage, FakeMidiPorts, fake_message

from loopstation.midi.launchpad import (
    LAUNCHPAD_X,
    LEGACY,
    LEGACY_MODEL,
    MINI_MK3,
    MK2,
    PRO_MK3,
    PROGRAMMER,
    LaunchpadController,
    PadMapping,
    identify,
    pick_port,
)

MINI_LINUX = [
    "Launchpad Mini MK3:Launchpad Mini MK3 LPMiniMK3 DA 20:0",
    "Launchpad Mini MK3:Launchpad Mini MK3 LPMiniMK3 MI 20:1",
]


@pytest.mark.parametrize(
    ("names", "model", "port"),
    [
        (MINI_LINUX, MINI_MK3, MINI_LINUX[1]),
        (["LPMiniMK3 DAW Out", "LPMiniMK3 MIDI Out"], MINI_MK3, "LPMiniMK3 MIDI Out"),
        (["MIDIIN2 (LPMiniMK3 MIDI)", "LPMiniMK3 MIDI"], MINI_MK3, "LPMiniMK3 MIDI"),
        (["Launchpad X:Launchpad X LPX DAW 24:0", "Launchpad X:Launchpad X LPX MIDI 24:1"],
         LAUNCHPAD_X, "Launchpad X:Launchpad X LPX MIDI 24:1"),
        (["LPProMK3 MIDI", "LPProMK3 DAW"], PRO_MK3, "LPProMK3 MIDI"),
        (["Launchpad MK2:Launchpad MK2 MIDI 1 28:0"], MK2, "Launchpad MK2:Launchpad MK2 MIDI 1 28:0"),
        (["Launchpad S:Launchpad S MIDI 1 32:0"], LEGACY_MODEL, "Launchpad S:Launchpad S MIDI 1 32:0"),
        (["Launchpad Mini:Launchpad Mini MIDI 1 32:0"], LEGACY_MODEL,
         "Launchpad Mini:Launchpad Mini MIDI 1 32:0"),
    ],
)
def test_detection_from_port_names(names, model, port):
    assert pick_port(["Midi Through:Midi Through Port-0 14:0", *names]) == (port, model)


def test_no_launchpad():
    assert pick_port(["Midi Through:Midi Through Port-0 14:0", "USB Keyboard"]) is None
    assert identify("Launchpad Pro:Launchpad Pro MIDI 1") is None  # MK1 Pro is not supported


def test_programmer_mapping_4x3():
    mapping = PadMapping(PROGRAMMER, rows=3, cols=4)
    assert mapping.note_for(0) == 81  # top left
    assert mapping.note_for(3) == 84
    assert mapping.note_for(4) == 71
    assert mapping.note_for(11) == 64
    for pad in range(12):
        assert mapping.pad_for(mapping.note_for(pad)) == pad
    assert mapping.pad_for(85) is None  # column 5 is outside a 4-wide grid
    assert mapping.pad_for(51) is None  # row 4 is outside a 3-high grid
    assert mapping.pad_for(89) is None  # side button


def test_programmer_mapping_8x8():
    mapping = PadMapping(PROGRAMMER, rows=8, cols=8)
    assert mapping.note_for(0) == 81 and mapping.note_for(63) == 18
    assert sorted(mapping.note_for(p) for p in range(64)) == sorted(
        r * 10 + c for r in range(1, 9) for c in range(1, 9))
    for pad in range(64):
        assert mapping.pad_for(mapping.note_for(pad)) == pad


def test_legacy_mapping_4x3_and_8x8():
    small = PadMapping(LEGACY, rows=3, cols=4)
    assert [small.note_for(p) for p in (0, 3, 4, 11)] == [0, 3, 16, 35]
    assert small.pad_for(8) is None  # side button column
    big = PadMapping(LEGACY, rows=8, cols=8)
    for pad in range(64):
        assert big.pad_for(big.note_for(pad)) == pad
    assert big.note_for(63) == 7 * 16 + 7


def test_grid_larger_than_8x8_maps_only_the_top_left_part():
    mapping = PadMapping(PROGRAMMER, rows=10, cols=10)
    assert mapping.note_for(8) is None  # column 9
    assert mapping.note_for(80) is None  # row 9
    assert len(mapping.mapped_pads()) == 64


def connect(names, rows=3, cols=4):
    ports = FakeMidiPorts(names)
    clock = FakeClock(0.0)
    launchpad = LaunchpadController(lambda: ports, rows, cols, clock=clock, message_factory=fake_message)
    assert launchpad.poll() == []  # first poll scans and connects
    return launchpad, ports, clock


def test_connect_sends_sysex_and_colors():
    launchpad, ports, _ = connect(MINI_LINUX)
    assert launchpad.connected and launchpad.status_text == "Launchpad verbunden"
    out = ports.opened["out:" + MINI_LINUX[1]]
    assert out.sent[0] == FakeMessage("sysex", data=(0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01))
    notes = {m.note: m.velocity for m in out.sent[1:]}
    assert len(notes) == 12 and set(notes.values()) == {3}  # all white


def test_colors_only_send_changes():
    launchpad, ports, _ = connect(MINI_LINUX)
    out = ports.opened["out:" + MINI_LINUX[1]]
    colors = {i: "white" for i in range(12)}
    out.sent.clear()
    launchpad.set_colors(colors)
    assert out.sent == []
    colors.update({0: "yellow", 5: "green", 11: "red"})
    launchpad.set_colors(colors)
    assert [(m.note, m.velocity) for m in out.sent] == [(81, 13), (72, 21), (64, 5)]
    out.sent.clear()
    launchpad.set_colors(colors)
    assert out.sent == []


def test_legacy_colors():
    names = ["Launchpad S:Launchpad S MIDI 1 32:0"]
    launchpad, ports, _ = connect(names)
    out = ports.opened["out:" + names[0]]
    assert all(m.type == "note_on" for m in out.sent)  # no SysEx for legacy devices
    out.sent.clear()
    launchpad.set_colors({0: "yellow", 1: "green", 2: "red", 3: "white"})
    assert [(m.note, m.velocity) for m in out.sent] == [(0, 0x3E), (1, 0x3C), (2, 0x0F)]


def test_presses_are_reported_as_pads():
    launchpad, ports, _ = connect(MINI_LINUX)
    inport = ports.opened["in:" + MINI_LINUX[1]]
    inport.pending += [
        FakeMessage("note_on", note=81, velocity=100),
        FakeMessage("note_on", note=81, velocity=0),  # release
        FakeMessage("note_off", note=72, velocity=0),
        FakeMessage("polytouch", note=72, velocity=50),
        FakeMessage("note_on", note=64, velocity=1),
        FakeMessage("note_on", note=88, velocity=90),  # outside the 4x3 grid
    ]
    assert launchpad.poll() == [0, 11]


def test_send_error_means_disconnected_and_hot_plug_reconnects():
    launchpad, ports, clock = connect(MINI_LINUX)
    out = ports.opened["out:" + MINI_LINUX[1]]
    out.fail_send = True
    launchpad.set_colors({0: "green"})
    assert not launchpad.connected and launchpad.status_text is None
    assert launchpad.poll() == []  # no crash, waits for the next scan
    clock.advance(2.1)
    launchpad.poll()
    assert launchpad.connected


def test_unplugging_is_noticed():
    launchpad, ports, clock = connect(MINI_LINUX)
    ports.inputs, ports.outputs = [], []
    clock.advance(2.1)
    assert launchpad.poll() == []
    assert not launchpad.connected


def test_without_midi_backend_the_launchpad_stays_off():
    def broken():
        raise ImportError("no rtmidi")

    launchpad = LaunchpadController(broken, 3, 4, clock=FakeClock(0.0))
    assert launchpad.poll() == []
    assert not launchpad.connected
    launchpad.set_colors({0: "yellow"})
    launchpad.close()


def test_close_switches_leds_off():
    launchpad, ports, _ = connect(MINI_LINUX)
    out = ports.opened["out:" + MINI_LINUX[1]]
    out.sent.clear()
    launchpad.close()
    assert len(out.sent) == 12 and {m.velocity for m in out.sent} == {0}
    assert out.closed and not launchpad.connected


def test_real_mido_messages_are_valid():
    """The default message factory builds real mido messages (no fake)."""
    ports = FakeMidiPorts(MINI_LINUX)
    launchpad = LaunchpadController(lambda: ports, 3, 4, clock=FakeClock(0.0))
    launchpad.poll()
    out = ports.opened["out:" + MINI_LINUX[1]]
    assert out.sent[0].bytes() == [0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01, 0xF7]
    assert out.sent[1].bytes() == [0x90, 81, 3]
