"""Controller with FakeAudio and FakeClock: the behaviour behind the buttons."""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile
from conftest import FakeAudio, FakeClock, make_settings

from loopstation.audio.null_backend import NullAudio
from loopstation.controller import Controller, Mode
from loopstation.store import EventStore


def build(tmp_path, clock: FakeClock, audio: FakeAudio | None = None, **overrides):
    settings = make_settings(tmp_path, **overrides)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    audio = audio or FakeAudio(clock)
    controller = Controller(store, audio, settings, clock=clock)
    controller.startup()
    return controller, audio


def record(controller: Controller, clock: FakeClock, pad: int, seconds: float = 1.0) -> None:
    controller.press(pad)
    clock.advance(seconds)
    controller.press(pad)


def event_types(controller: Controller) -> list[str]:
    path = controller.store.log_path
    return [json.loads(line)["type"] for line in path.read_text(encoding="utf-8").splitlines()]


def test_record_by_second_press_writes_wav(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    stamp = int(clock() * 1000)
    controller.press(0)
    assert controller.recording_pad == 0
    assert controller.pad_colors()[0] == "red"
    clock.advance(1.5)
    controller.press(0)
    assert controller.recording_pad is None

    name = f"pad_0_{stamp}.wav"
    assert controller.pad(0).sample == name
    path = tmp_path / "samples" / name
    data, rate = soundfile.read(str(path))
    assert rate == 8000 and abs(len(data) / rate - 1.5) < 0.01
    # The first sound of a session also fixes the loop length.
    assert event_types(controller)[-3:] == ["record_start", "record_stop", "master_set"]
    assert len(audio.effects) == 2  # start and stop beep
    assert controller.pad_colors()[0] == "yellow"


def test_auto_stop_at_max_length(tmp_path, clock):
    controller, _audio = build(tmp_path, clock, max_record_seconds=3)
    controller.press(5)
    clock.advance(2.9)
    controller.tick()
    assert controller.recording_pad == 5
    assert controller.recording_remaining() == pytest.approx(0.1)
    clock.advance(0.2)
    controller.tick()
    assert controller.recording_pad is None
    assert controller.pad(5).sample is not None


def test_samples_survive_a_new_controller(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 2)
    name = controller.pad(2).sample
    controller.shutdown()

    again, audio = build(tmp_path, clock)
    assert again.pad(2).sample == name
    again.press(2)  # play
    assert audio.calls[-1] == ("play", 2, False)
    played = audio.voices[2][0]
    assert isinstance(played, np.ndarray) and len(played) == 8000


def test_colors_play_and_loop(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    colors = controller.pad_colors()
    assert len(colors) == 12 and set(colors.values()) == {"white"}

    record(controller, clock, 0)
    controller.press(0)  # PLAY mode: plays once
    assert controller.pad_colors()[0] == "green"
    audio.finish(0)
    assert controller.pad_colors()[0] == "yellow"

    controller.press(0)
    controller.press(0)  # pressing a playing pad stops it
    assert 0 not in audio.voices

    controller.set_mode(Mode.LOOP)
    controller.press(0)
    assert controller.pad(0).looping and audio.voices[0][1] is True
    assert controller.pad_colors()[0] == "green"
    controller.press(0)
    assert not controller.pad(0).looping and 0 not in audio.voices
    assert event_types(controller)[-2:] == ["loop_on", "loop_off"]


def test_stop_playing_loop_in_play_mode(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 1)
    controller.set_mode(Mode.LOOP)
    controller.press(1)
    controller.set_mode(Mode.PLAY)
    controller.press(1)
    assert not controller.pad(1).looping and 1 not in audio.voices


def test_record_mode_overwrites_and_keeps_history(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 3)
    first = controller.pad(3).sample
    controller.set_mode(Mode.RECORD)
    clock.advance(1)
    record(controller, clock, 3)
    assert controller.pad(3).sample != first
    assert controller.pad(3).history == [first, controller.pad(3).sample]
    assert controller.mode == Mode.RECORD


def test_delete_mode_ends_after_one_pad(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0)
    record(controller, clock, 1)
    controller.set_mode(Mode.DELETE)
    controller.press(0)
    assert controller.pad(0).sample is None
    assert controller.mode == Mode.PLAY
    controller.press(1)  # PLAY mode again: plays instead of deleting
    assert controller.pad(1).sample is not None


def test_same_button_or_escape_leaves_delete_mode(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    controller.set_mode(Mode.DELETE)
    controller.set_mode(Mode.DELETE)
    assert controller.mode == Mode.PLAY
    controller.set_mode(Mode.DELETE)
    controller.escape()
    assert controller.mode == Mode.PLAY


def test_undo_and_restore(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 4)
    first = controller.pad(4).sample
    controller.set_mode(Mode.RECORD)
    clock.advance(1)
    record(controller, clock, 4)
    second = controller.pad(4).sample
    controller.set_mode(Mode.PLAY)

    controller.undo()
    assert controller.pad(4).sample == first
    controller.restore(4, second)
    assert controller.pad(4).sample == second
    controller.undo()
    assert controller.pad(4).sample == first
    controller.undo()
    assert controller.pad(4).sample is None
    controller.undo()  # nothing left: no event, a short hint
    assert controller.notice() is not None
    assert [entry.sample for entry in controller.history(4)] == [first, second]
    assert controller.history(4)[0].recorded_at is not None


def test_undo_skips_playback_events(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0)
    controller.press(0)  # play
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.press(0)
    controller.undo()  # undoes the recording, not the loop toggles
    assert controller.pad(0).sample is None


def test_undo_stops_the_affected_pad(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.undo()
    assert 0 not in audio.voices
    assert not controller.pad(0).looping


def test_delete_all_and_undo(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0)
    record(controller, clock, 7)
    controller.set_mode(Mode.LOOP)
    controller.press(7)
    controller.delete_all()
    assert all(controller.pad(i).sample is None for i in range(12))
    assert audio.voices == {}
    controller.undo()
    assert controller.pad(0).sample is not None and controller.pad(7).sample is not None


def test_too_short_recording_is_discarded(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    controller.press(0)
    clock.advance(0.1)
    controller.press(0)
    assert controller.pad(0).sample is None
    assert not (tmp_path / "samples").exists() or not list((tmp_path / "samples").iterdir())
    assert controller.notice() == "Zu kurz - nochmal!"
    assert event_types(controller)[-1] == "record_stop"


def test_no_microphone_no_recording(tmp_path, clock):
    controller, audio = build(tmp_path, clock, audio=FakeAudio(clock, available_input=False))
    controller.press(0)
    assert controller.recording_pad is None
    assert controller.notice() == "Kein Mikrofon gefunden"
    assert "record_start" not in event_types(controller)


def test_pressing_another_pad_stops_the_recording_first(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0)
    controller.press(1)  # starts recording on the empty pad 1
    clock.advance(1)
    controller.press(0)  # stops pad 1, then plays pad 0
    assert controller.pad(1).sample is not None
    assert controller.recording_pad is None
    assert controller.pad_colors()[0] == "green"


def test_history_mode_notifies_and_returns_to_play(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    opened: list[int] = []
    controller.add_history_listener(opened.append)
    record(controller, clock, 6)
    controller.set_mode(Mode.HISTORY)
    controller.press(6)
    assert opened == [6]
    assert controller.mode == Mode.PLAY


def test_stop_all_switches_loops_off(tmp_path, clock):
    controller, audio = build(tmp_path, clock)
    record(controller, clock, 0)
    record(controller, clock, 1)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.press(1)
    controller.stop_all()
    assert audio.voices == {}
    assert not controller.pad(0).looping and not controller.pad(1).looping


def test_nothing_loops_after_restart(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    record(controller, clock, 0)
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    controller.store.close()  # crash: no clean shutdown

    again, audio = build(tmp_path, clock)
    assert not again.pad(0).looping
    assert audio.voices == {}


def test_listener_is_called_on_changes(tmp_path, clock):
    controller, _ = build(tmp_path, clock)
    calls: list[int] = []
    controller.add_listener(lambda: calls.append(1))
    controller.set_mode(Mode.LOOP)
    controller.press(0)
    assert len(calls) >= 2


def test_null_audio_lights_pads_for_the_sample_length(tmp_path, clock):
    settings = make_settings(tmp_path)
    store = EventStore(settings.log_dir, settings.pad_count, clock=clock)
    # put a recording in place with a working fake, then continue without audio
    fake = FakeAudio(clock)
    controller = Controller(store, fake, settings, clock=clock)
    record(controller, clock, 0, seconds=2.0)
    null = NullAudio(sample_rate=8000, clock=clock)
    controller = Controller(store, null, settings, clock=clock)
    controller.press(0)
    assert controller.pad_colors()[0] == "green"
    clock.advance(2.1)
    assert controller.pad_colors()[0] == "yellow"
    store.close()
