"""End to end across the packages: one session as a child and the parents would run it.

The controller runs on the real engine (``SoundDeviceAudio``) with the stand-in
sound card, so the grid, the onset shift, the stretch, the seam and the limiter
are the real code. Everything goes through the public methods the screen and the
Launchpad use; sets go through ``SetSession``. No hardware, no display.

Plan "loopstation-kids-verbesserungsplan.md": first recording fixes the bar (onset
shift for that take only), more pads fit into it, undo and redo keep the bar,
the loop seam is soft, the ceiling holds, sets keep the undo steps, export is
exact, markers travel with their sample and end up as cue points.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import numpy as np
import pytest
import soundfile
from conftest import FakeAudio, FakeClock, FakeSoundDevice, clap_signal, make_settings

from loopstation import export as ex
from loopstation import sets
from loopstation.audio.dynamics import block_peak, db_to_gain
from loopstation.audio.samples import load_wav
from loopstation.audio.sounddevice_backend import SoundDeviceAudio
from loopstation.audio.sync import soften_seam
from loopstation.controller import FREE_HOLD_SECONDS, Controller, Mode
from loopstation.session import SetSession, commit_open
from loopstation.state import master_source
from loopstation.store import EventStore

SR = 8000
BLOCK = 100
BAR = 16000  # two claps 0.5 s apart: one beat is 0.5 s, one bar is four beats = 2 s
CEILING_DB = -6.0
CEILING = db_to_gain(CEILING_DB)
CUE_TOLERANCE = 2 / 2**23  # 24-bit WAV


def sawtooth(frames: int, period: int, amp: float) -> np.ndarray:
    """A ramp that jumps every ``period`` frames: a loop of it has a step at its seam."""
    return (amp * (2 * (np.arange(frames) % period) / period - 1)).astype(np.float32)


class Rig:
    """The running app: engine on a stand-in card, controller, sets session, and a clock."""

    def __init__(self, tmp_path) -> None:
        self.tmp = tmp_path
        self.clock = FakeClock()
        self.device = FakeSoundDevice(block=BLOCK)
        self.settings = make_settings(
            tmp_path / "live", auto_grid=True, sound_effects=False, volume=1.0, max_level_db=0.0)
        # As ``loopstation.audio`` builds it: the seam setting goes to the engine.
        self.audio = SoundDeviceAudio(
            SR, 10, latency_seconds=0.0, sd=self.device, clock=lambda: 0.0,
            soft_seam=self.settings.soft_seam)
        self.sets_folder = tmp_path / "sets"
        self.open_controller()

    def open_controller(self) -> None:
        self.store = EventStore(self.settings.log_dir, self.settings.pad_count, clock=self.clock)
        self.controller = Controller(self.store, self.audio, self.settings, clock=self.clock)
        self.controller.startup()
        self.session = SetSession(self.controller, None, clock=self.clock, sets_folder=self.sets_folder)

    # -- the child's hands

    def say(self, signal: np.ndarray | None) -> None:
        """What the microphone hears from now on: ``signal`` starts with the next recording frame."""
        if signal is None:
            self.device.voice = None
            return
        base = self.device.frame - BLOCK  # the stand-in card delivers a block that was heard just before

        def voice(frames: np.ndarray) -> np.ndarray:
            idx = frames - base
            out = np.zeros(len(frames), dtype=np.float32)
            ok = (idx >= 0) & (idx < len(signal))
            out[ok] = signal[idx[ok]]
            return out

        self.device.voice = voice

    def take(self, pad: int, seconds: float, signal: np.ndarray | None) -> None:
        """Press the pad, speak for ``seconds`` (after a wait for the loop start), press again."""
        c = self.controller
        c.press(pad)
        for _ in range(int(BAR / BLOCK) + 2):  # a recording on a running loop waits for its start
            if not c.recording_waits():
                break
            self.device.step()
        assert c.recording_pad == pad and not c.recording_waits()
        self.say(signal)
        self.device.step(round(seconds * SR / BLOCK))
        c.press(pad)
        assert c.recording_pad is None
        self.say(None)
        self.clock.advance(1.0)  # sample names carry the time: every take gets its own

    def play(self, frames: int) -> None:
        self.device.step(frames // BLOCK)

    def events(self, type_: str | None = None) -> list[dict]:
        lines = self.controller.store.log_path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        return [r for r in rows if type_ is None or r["type"] == type_]

    def wav(self, pad: int) -> np.ndarray:
        return load_wav(self.settings.samples_dir / self.controller.pad(pad).sample, SR)

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def rig(tmp_path) -> Rig:
    r = Rig(tmp_path)
    yield r
    r.close()


def first_take(rig: Rig) -> None:
    """Pad 0: claps at 0.5 s and 1.0 s in a 3 s take: sets the bar, starts at the first clap."""
    rig.take(0, 3.0, clap_signal(3 * SR, SR, [0.5, 1.0]))


def undo_depth(rig: Rig) -> int:
    return len(rig.store.state.undo_stack)


def test_the_whole_session_end_to_end(rig, tmp_path):
    c, device = rig.controller, rig.device

    # --- 1. the first recording makes the bar; only it is shifted to its first onset
    first_take(rig)
    master = rig.store.state.master
    assert master["frames"] == BAR and master_source(master) == "onset"
    assert master["signature"] == "4/4" and master["pad"] == 0
    assert rig.audio._grid == BAR  # the engine got the bar
    info = c.grid_info()
    assert info is not None and info.bpm == pytest.approx(120.0) and info.seconds == pytest.approx(2.0)
    stop0 = rig.events("record_stop")[0]["data"]
    assert stop0["grid"] == "onset" and stop0["shift"] > 0.4 * SR  # silence in front was cut away
    pad0 = rig.wav(0)
    assert len(pad0) == BAR
    assert int(np.argmax(np.abs(pad0) > 0.1)) < 0.02 * SR  # the loop begins at the first clap

    # --- 2. a second pad, a little short of the bar and with a hard jump at its end: no shift,
    # it is fitted into the bar (stretch) and keeps its own start
    rig.clock.advance(1.0)
    saw = sawtooth(3 * SR, 3001, 0.3)
    rig.take(1, 1.95, saw)  # 15600 frames, 2.5 % short of one bar
    stop1 = rig.events("record_stop")[1]["data"]
    assert "shift" not in stop1 and stop1.get("grid") != "onset"
    pad1 = rig.wav(1)
    assert len(pad1) == BAR
    assert rig.store.state.master == master  # the bar did not move

    # --- 3. both loop; the engine plays exactly their sum, the seam of pad 1 has no click
    c.set_mode(Mode.LOOP)
    anchor = device.frame
    c.press(0)  # nothing loops yet: starts at once and anchors the bar lines
    device.step(30)
    c.press(1)  # the next loop waits for the next bar line
    assert c.waiting_pads() == {1}
    c.set_mode(Mode.PLAY)
    device.run_to(anchor + 4 * BAR)
    assert c.waiting_pads() == set() and c.pad(0).looping and c.pad(1).looping
    loop0, loop1 = c._loop_data(c.pad(0).sample, 0), c._loop_data(c.pad(1).sample, 1)
    soft0, soft1 = soften_seam(loop0, SR), soften_seam(loop1, SR)  # what a looping voice plays
    out = device.output_signal()
    assert np.array_equal(out[anchor:anchor + BAR], soft0)  # pad 0 alone, from the anchor
    both = out[anchor + BAR:anchor + 2 * BAR]
    assert np.allclose(both, soft0 + soft1, atol=1e-6)  # pad 1 joined on the bar line
    for bar in (2, 3):  # the same period every bar
        assert np.array_equal(out[anchor + bar * BAR:anchor + (bar + 1) * BAR], both)
    # Soft seam: the take itself jumps where its end meets its start, the engine plays no step there.
    assert abs(float(loop1[-1]) - float(loop1[0])) > 0.25
    for bar in (1, 2, 3):
        edge = anchor + bar * BAR
        assert abs(float(out[edge]) - float(out[edge - 1])) < 0.05
    c.stop_all()

    # --- 4. loud sum of several pads: the ceiling is never passed
    rig.clock.advance(1.0)
    for pad, hz in ((2, 330.0), (3, 550.0), (4, 770.0)):
        loud = (0.9 * np.sin(2 * np.pi * hz * np.arange(3 * SR) / SR)).astype(np.float32)
        rig.take(pad, 2.0, loud)
    c.set_max_level_db(CEILING_DB)
    c.set_volume(1.0)
    assert c.max_level_db == CEILING_DB
    # What the parents set is kept in the settings file; a new controller (set swap) reads it from there.
    rig.settings = replace(rig.settings, max_level_db=CEILING_DB, volume=1.0)
    c.set_mode(Mode.LOOP)
    for pad in range(5):
        if not c.pad(pad).looping:
            c.press(pad)
    c.set_mode(Mode.PLAY)
    mark = device.frame
    device.step(3 * BAR // BLOCK)
    loud_out = device.output_signal()[mark:]
    assert block_peak(loud_out) <= CEILING + 1e-6
    assert block_peak(loud_out) > 0.9 * CEILING  # limited, not muted
    c.stop_all()

    # --- 5. undo and redo of a pad, the bar stays
    c.set_mode(Mode.RECORD)
    rig.take(1, 1.9, sawtooth(3 * SR, 1777, 0.4))
    c.set_mode(Mode.PLAY)
    second, first = c.pad(1).sample, c.pad(1).history[0]
    assert c.pad(1).history == [first, second] and len(rig.wav(1)) == BAR
    depth = undo_depth(rig)
    c.undo(1)
    assert c.pad(1).sample == first and c.can_redo(1)
    assert rig.store.state.master == master
    c.redo(1)
    assert c.pad(1).sample == second and rig.store.state.master == master
    # global undo and redo too
    c.undo()
    assert c.pad(1).sample == first
    c.redo()
    assert c.pad(1).sample == second and undo_depth(rig) == depth
    assert c.grid_frames() == BAR

    # --- 6. markers belong to the sample: Undo brings them back with it
    assert c.add_marker(1, 4320) and c.add_marker(1, 12480)
    assert c.markers(1) == [4320, 12480]
    c.undo(1)
    assert c.pad(1).sample == first and c.markers(1) == []
    c.redo(1)
    assert c.markers(1) == [4320, 12480]
    assert c.remove_marker(1, 12480) and c.markers(1) == [4320]
    assert rig.events("marker_set")[-1]["data"]["frames"] == [4320]

    # --- 7. a set keeps undo steps, bar, source and signature; redo starts empty
    c.undo(1)  # something on the redo stack to be dropped
    assert c.can_redo()
    steps = [dict(e) for e in rig.store.state.undo_stack]
    pads_before = {i: (p.sample, p.history) for i, p in rig.store.state.pads.items()}
    markers_before = dict(rig.store.state.markers)
    target = rig.sets_folder / "kinder.loopset"
    manifest = rig.session.save(target)
    assert manifest.grid == master  # source, signature and pad travel with the bar
    assert manifest.pad_count == 12 and manifest.sample_rate == SR
    rig.store.close()
    shutil.rmtree(rig.settings.data_dir)
    rig.settings.data_dir.mkdir()
    commit_open(rig.settings.data_dir, rig.session.prepare_open(target))
    rig.open_controller()
    c = rig.controller
    state = rig.store.state
    assert [e["seq"] for e in state.undo_stack] == [e["seq"] for e in steps]
    assert {i: (p.sample, p.history) for i, p in state.pads.items()} == pads_before
    assert state.redo_stack == [] and not c.can_redo()
    assert state.master == master and master_source(state.master) == "onset"
    assert state.master["signature"] == "4/4" and state.master["pad"] == 0
    assert state.markers == markers_before
    assert c.grid_frames() == BAR
    for name in sets.referenced_samples(state):
        assert (rig.settings.samples_dir / name).is_file()
    assert not rig.session.unsaved()
    c.undo()  # undo works in the opened set
    assert c.can_redo()
    c.redo()

    # --- 8. changing sets changes the bar and back again; an empty session takes it from the next set
    # a second app on its own folder with a 1 s bar
    other_clock = FakeClock()
    other_settings = make_settings(tmp_path / "other", sound_effects=False)
    other_store = EventStore(other_settings.log_dir, 12, clock=other_clock)
    other_audio = FakeAudio(other_clock)
    other_controller = Controller(other_store, other_audio, other_settings, clock=other_clock)
    other_controller.startup()
    other_controller.press(0)
    other_clock.advance(1.0)
    other_controller.press(0)
    assert other_controller.grid_frames() == SR
    other_set = tmp_path / "sets" / "other.loopset"
    SetSession(other_controller, None, clock=other_clock, sets_folder=tmp_path / "sets").save(other_set)
    other_store.close()

    for source, frames in ((other_set, SR), (target, BAR)):
        rig.store.close()
        commit_open(rig.settings.data_dir, rig.session.prepare_open(source))
        rig.open_controller()
        c = rig.controller
        assert c.grid_frames() == frames and rig.store.state.master["frames"] == frames
        assert c.store.state.has_content()

    # --- 9. export: the sum over N bars is N bars long and under the ceiling; single loops carry cue points
    c.set_volume(1.0)
    bars = 6
    sum_path = tmp_path / "out" / "sum.wav"
    info_sum = ex.export_sum(sum_path, ex.build_spec(c, bars=bars, all_pads=True))
    assert info_sum.frames == bars * BAR
    with soundfile.SoundFile(str(sum_path)) as handle:
        assert (handle.samplerate, handle.channels, len(handle)) == (SR, 1, bars * BAR)
    data, _ = soundfile.read(str(sum_path), dtype="float32")
    assert float(np.abs(data).max()) <= CEILING + CUE_TOLERANCE
    assert float(np.abs(data).max()) > 0.0
    # one bar repeating N times (the limiter keeps a little memory, so not sample for sample)
    assert np.corrcoef(data[BAR:2 * BAR], data[2 * BAR:3 * BAR])[0, 1] > 0.98

    marker_pad = 1
    assert c.add_marker(marker_pad, 12480) and c.add_marker(marker_pad, 4320)  # a marker in the opened set
    marks = c.markers(marker_pad)
    assert marks == [4320, 12480]
    loop_path = tmp_path / "out" / "pad.wav"
    loop = c.loop_audio(c.pad(marker_pad).sample, marker_pad)
    assert ex.export_loop(loop_path, loop, SR, "Loopstation", markers=marks) == "cue"
    assert ex.read_cue_points(loop_path.read_bytes()) == [
        (f, ex.marker_name(i)) for i, f in enumerate(marks)]
    back, rate = soundfile.read(str(loop_path), dtype="float32")
    assert rate == SR and len(back) == len(loop) and np.allclose(back, loop, atol=CUE_TOLERANCE)
    plain = tmp_path / "out" / "plain.wav"
    other_pad = 0
    assert ex.export_loop(plain, c.loop_audio(c.pad(other_pad).sample, other_pad), SR) is None
    assert soundfile.info(str(plain)).frames == BAR

    # --- 10. free pad: a long hold, then the recording keeps its own length and the bar stays
    c.stop_all()
    free_pad = 7
    c.press_down(free_pad)
    for _ in range(round((FREE_HOLD_SECONDS + 0.1) / 0.03)):
        rig.clock.advance(0.03)
        c.tick()
    assert c.press_up(free_pad) is False and c.is_free(free_pad)
    rig.take(free_pad, 1.3, (0.3 * np.sin(np.arange(3 * SR) * 0.2)).astype(np.float32))
    assert len(rig.wav(free_pad)) == pytest.approx(1.3 * SR, abs=BLOCK)  # not fitted to the bar
    assert c.grid_frames() == BAR and rig.store.state.master["frames"] == BAR
    c.undo(free_pad)
    assert c.pad(free_pad).sample is None
    c.redo(free_pad)
    assert c.pad(free_pad).sample is not None and c.is_free(free_pad)


def test_the_bar_survives_undoing_everything_and_bringing_it_back(rig):
    c = rig.controller
    first_take(rig)
    rig.take(1, 2.0, sawtooth(3 * SR, 1777, 0.3))
    master = dict(rig.store.state.master)
    c.undo()
    c.undo()
    assert not rig.store.state.has_content() and not c.can_undo()
    c.redo()
    c.redo()
    assert rig.store.state.master == master and c.grid_frames() == BAR and rig.audio._grid == BAR
    assert c.pad(0).sample is not None and c.pad(1).sample is not None
    # "Alle löschen" and back
    c.delete_all()
    assert not rig.store.state.has_content()
    c.undo()
    assert rig.store.state.master == master and c.pad(1).sample is not None
    # a take without claps in an empty session sets no bar: the session stays free
    c.delete_all()
    rig.take(2, 1.0, sawtooth(3 * SR, 1777, 0.3))
    assert c.grid_frames() is None and rig.store.state.master is None
    # claps 0.4 s apart set a new bar of 1.6 s
    c.delete_all()
    rig.take(3, 2.5, clap_signal(3 * SR, SR, [0.3, 0.7]))
    assert c.grid_frames() == 12800 and master_source(rig.store.state.master) == "onset"
    assert rig.audio._grid == 12800
    c.undo()  # take 3 gone
    c.undo()  # the second delete taken back: the free take is there again, still without a bar
    assert c.pad(2).sample is not None and c.grid_frames() is None
    c.undo()
    c.undo()  # the first delete taken back: the old session with its own bar
    assert c.grid_frames() == BAR and rig.store.state.master == master
