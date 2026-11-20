"""Sets in the running session: save, unsaved changes, safe swap on open, device hints (no hardware)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import FakeAudio, FakeClock, FakeSoundDevice, make_settings
from test_devices import dev

from loopstation import session as sess
from loopstation import sets
from loopstation.controller import Controller, Mode
from loopstation.session import (
    SessionBusyError,
    SetSession,
    SetUnsuitableError,
    commit_open,
    content_fingerprint,
    device_notes,
    list_sets,
    prepare_open,
    recover_swap,
)
from loopstation.sets import SetCorruptError, SetTooNewError
from loopstation.state import AppState
from loopstation.store import EventStore


class Running:
    """A controller on disk (FakeAudio, FakeClock) plus the sets session around it."""

    def __init__(self, data_dir: Path, clock: FakeClock, settings_file: Path | None = None) -> None:
        self.clock = clock
        self.settings = make_settings(data_dir)
        self.audio = FakeAudio(clock)
        self.open_store()
        self.settings_file = settings_file
        self.sets_folder = data_dir.parent / "sets"
        self.session = SetSession(self.controller, settings_file, clock=clock, sets_folder=self.sets_folder)

    def open_store(self) -> None:
        self.store = EventStore(self.settings.log_dir, self.settings.pad_count, clock=self.clock)
        self.controller = Controller(self.store, self.audio, self.settings, clock=self.clock)
        self.controller.startup()

    def record(self, pad: int, seconds: float = 1.0) -> None:
        self.controller.press(pad)
        self.clock.advance(seconds)
        self.controller.press(pad)

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def running(tmp_path, clock) -> Running:
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text("# test\nvolume = 0.5\n", encoding="utf-8")
    run = Running(tmp_path / "live", clock, settings_file)
    yield run
    run.close()


def content(state: AppState) -> dict:
    """The parts of a state a set must keep (undo stack included), without seq numbers of snapshots."""
    raw = state.to_dict()
    return {"pads": raw["pads"], "undo_stack": raw["undo_stack"], "master": raw["master"]}


def two_takes(run: Running) -> None:
    run.record(0, 1.0)
    run.record(1, 1.0)
    run.controller.set_mode(Mode.RECORD)
    run.record(0, 1.0)  # replaces pad 0: undo stack and history have something to keep
    run.controller.set_mode(Mode.PLAY)


# ------------------------------------------------------------------ end to end


@pytest.mark.parametrize("suffix", [".loopset", ""])
def test_save_wipe_open_gives_the_same_session(running, tmp_path, suffix):
    two_takes(running)
    before = content(running.store.state)
    assert len(before["undo_stack"]) >= 2
    target = running.sets_folder / f"mias{suffix}"
    manifest = running.session.save(target)
    assert manifest.pad_count == 12
    running.close()

    # "Daten löschen": the whole working folder is gone.
    shutil.rmtree(running.settings.data_dir)
    running.settings.data_dir.mkdir()

    prepared = prepare_open(running.settings.data_dir, target, pad_count=12, sample_rate=8000)
    commit_open(running.settings.data_dir, prepared)
    running.open_store()

    after = running.store.state
    assert content(after) == before
    assert getattr(after, "redo_stack", []) == []  # redo starts empty
    for name in sets.referenced_samples(after):
        assert (running.settings.samples_dir / name).is_file()
    # The opened session is saved: nothing to ask about.
    assert running.session.unsaved() is False
    # Nothing of the swap is left behind.
    left = sorted(p.name for p in running.settings.data_dir.iterdir())
    assert left == ["data", "samples", "set-saved.json"]


def test_a_running_recording_blocks_saving(running):
    running.controller.press(3)
    assert running.session.recording()
    target = running.sets_folder / "x.loopset"
    with pytest.raises(SessionBusyError):
        running.session.save(target)
    assert not target.exists()
    assert not running.sets_folder.exists() or not list(running.sets_folder.iterdir())
    # Opening is refused for the same reason.
    with pytest.raises(SessionBusyError):
        running.session.prepare_open(target)
    # After the recording the same save works and the set holds a complete take only.
    running.clock.advance(1.0)
    running.controller.press(3)
    running.session.save(target)
    assert sets.read_manifest(target).samples


def test_saving_leaves_the_running_session_alone(running):
    two_takes(running)
    state_before = running.store.state.to_dict()
    running.session.save(running.sets_folder / "a.loopset")
    assert running.store.state.to_dict() == state_before
    running.record(2, 0.5)  # the child just carries on
    assert running.controller.pad(2).sample is not None


def test_session_data_stays_when_the_set_is_refused(running):
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    # A set that claims a newer format.
    new = running.sets_folder / "neu.loopset"
    with zipfile.ZipFile(target) as src, zipfile.ZipFile(new, "w") as out:
        for item in src.namelist():
            raw = src.read(item)
            if item == sets.MANIFEST_NAME:
                raw = raw.replace(b"format_version = 1", b"format_version = 99")
            out.writestr(item, raw)
    log_before = (running.settings.log_dir / "events.jsonl").read_bytes()
    with pytest.raises(SetTooNewError, match="neuere Loopstation"):
        running.session.prepare_open(new)
    broken = running.sets_folder / "kaputt.loopset"
    broken.write_bytes(b"not a zip")
    with pytest.raises(SetCorruptError):
        running.session.prepare_open(broken)
    assert (running.settings.log_dir / "events.jsonl").read_bytes() == log_before
    assert not (running.settings.data_dir / sess.STAGING_NAME).exists()


def test_set_for_another_pad_grid_or_sample_rate_is_refused(running):
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    with pytest.raises(SetUnsuitableError, match="hat 16"):
        prepare_open(running.settings.data_dir, target, pad_count=16, sample_rate=8000)
    with pytest.raises(SetUnsuitableError, match="44100 Hz"):
        prepare_open(running.settings.data_dir, target, pad_count=12, sample_rate=44100)
    assert not (running.settings.data_dir / sess.STAGING_NAME).exists()


# ------------------------------------------------------------ unsaved changes


def test_unsaved_changes_follow_content_not_loops_or_snapshots(running):
    assert running.session.unsaved() is False  # an empty session has nothing to lose
    two_takes(running)
    assert running.session.unsaved() is True
    running.session.save(running.sets_folder / "a.loopset")
    assert running.session.unsaved() is False
    running.controller.press(2)  # starts a recording: not content yet
    running.controller.press(2)
    running.clock.advance(0.0)
    # Switching loops and mere snapshots are not changes of the content.
    saved = content_fingerprint(running.store.state)
    running.controller.stop_all()
    assert content_fingerprint(running.store.state) == saved


def test_new_take_after_saving_is_unsaved_again(running):
    two_takes(running)
    running.session.save(running.sets_folder / "a.loopset")
    running.record(5, 1.0)
    assert running.session.unsaved() is True


def test_summary_counts_what_goes_into_the_set(running):
    two_takes(running)
    info = running.session.summary()
    assert info["recorded_pads"] == 2 and info["pad_count"] == 12
    assert info["samples"] == 3  # pad 0 twice (history) and pad 1
    assert info["undo_steps"] == len(running.store.state.undo_stack)
    assert info["has_settings"] is True and info["bytes"] > 0


# --------------------------------------------------------------- the swap


def _consistent(settings) -> AppState:
    """The session on disk loads and every sample it names is there."""
    store = EventStore(settings.log_dir, settings.pad_count)
    try:
        state = store.state
    finally:
        store.close()
    for name in sets.referenced_samples(state):
        assert (settings.samples_dir / name).is_file(), name
    return state


@pytest.mark.parametrize("fail_at", range(1, 12))
def test_swap_cut_short_at_any_step_ends_in_a_whole_session(running, monkeypatch, fail_at):
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    expected = content(running.store.state)
    # A different current session: one take, no set of it.
    running.close()
    shutil.rmtree(running.settings.data_dir)
    running.settings.data_dir.mkdir()
    running.open_store()
    running.record(7, 1.0)
    other = content(running.store.state)
    running.close()

    prepared = prepare_open(running.settings.data_dir, target, pad_count=12, sample_rate=8000)
    real_replace, calls = sess.os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) == fail_at:
            raise OSError("power cut")
        return real_replace(src, dst)

    monkeypatch.setattr(sess.os, "replace", flaky)
    try:
        commit_open(running.settings.data_dir, prepared)
        interrupted = False
    except OSError:
        interrupted = True
    monkeypatch.setattr(sess.os, "replace", real_replace)

    recover_swap(running.settings.data_dir)
    state = _consistent(running.settings)
    result = content(state)
    # Before the marker exists the old session simply stays; afterwards the swap is finished.
    assert result in (expected, other)
    if not interrupted:
        assert result == expected
    if fail_at >= 2:
        assert result == expected
    left = sorted(p.name for p in running.settings.data_dir.iterdir())
    assert left == ["data", "samples", "set-saved.json"] or (result == other and "samples" in left)
    assert not any(name.startswith((".replaced-", ".set-")) for name in left)


def test_recover_without_marker_only_cleans_up(running):
    two_takes(running)
    data_dir = running.settings.data_dir
    (data_dir / sess.STAGING_NAME / "data").mkdir(parents=True)
    (data_dir / ".replaced-samples").mkdir()
    before = content(running.store.state)
    assert recover_swap(data_dir) is False
    assert not (data_dir / sess.STAGING_NAME).exists()
    assert not (data_dir / ".replaced-samples").exists()
    assert content(running.store.state) == before
    assert (data_dir / "data" / "events.jsonl").is_file()


def test_commit_refuses_a_staging_that_is_gone(running):
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    prepared = running.session.prepare_open(target)
    sess.discard_prepared(prepared)
    with pytest.raises(sets.SetError):
        commit_open(running.settings.data_dir, prepared)
    assert (running.settings.data_dir / "data" / "events.jsonl").is_file()


# ------------------------------------------------------------------- redo


def test_open_clears_the_redo_stack_and_keeps_the_undo_stack(running, tmp_path, monkeypatch):
    """The redo stack comes with the undo package; here a state that carries one stands in for it."""
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    original = AppState.to_dict

    def with_redo(self):
        raw = original(self)
        raw.setdefault("redo_stack", [{"seq": 5, "pads": {"0": None}}])
        return raw

    monkeypatch.setattr(AppState, "to_dict", with_redo)
    work = tmp_path / "work"
    sets.open_set(target, work)
    lines = (work / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["type"] == "snapshot"
    assert event["data"]["state"]["redo_stack"] == []
    assert event["data"]["state"]["undo_stack"] == original(running.store.state)["undo_stack"]


def test_open_leaves_a_set_without_redo_untouched(running, tmp_path):
    two_takes(running)
    target = running.sets_folder / "a.loopset"
    running.session.save(target)
    work = tmp_path / "work"
    sets.open_set(target, work)
    with zipfile.ZipFile(target) as archive:
        assert (work / "data" / "events.jsonl").read_bytes() == archive.read("data/events.jsonl")


# ---------------------------------------------------------------- devices


def sound_card() -> FakeSoundDevice:
    return FakeSoundDevice(
        hostapis=[{"name": "ALSA", "default_input_device": 0, "default_output_device": 1}],
        devices=[dev("Eingebautes Mikro", 0, inputs=1), dev("Lautsprecher", 0, outputs=2)],
    )


SET_SETTINGS = """
volume = 0.5
[input_device]
name = "Focusrite"
hostapi = "ALSA"
[output_device]
name = "Lautsprecher"
hostapi = "ALSA"
"""


def test_missing_device_falls_back_to_the_system_default_with_a_hint():
    notes = device_notes(SET_SETTINGS, sound_card())
    assert len(notes) == 1
    assert "Focusrite" in notes[0] and "Systemstandard" in notes[0]  # the speaker is there: no hint


def test_no_devices_or_no_settings_give_no_hint():
    assert device_notes(None, sound_card()) == []
    assert device_notes("volume = 0.5\n", sound_card()) == []
    assert device_notes("not [toml", sound_card()) == []


def test_open_reports_the_missing_device(running, tmp_path):
    two_takes(running)
    settings_file = tmp_path / "from-another-pc.toml"
    settings_file.write_text(SET_SETTINGS, encoding="utf-8")
    target = running.sets_folder / "opa.loopset"
    sets.write_set(
        target, log_dir=running.settings.log_dir, samples_dir=running.settings.samples_dir,
        sample_rate=8000, pad_count=12, settings_file=settings_file,
    )
    running.session.sd = sound_card()
    prepared = running.session.prepare_open(target)
    assert len(prepared.notes) == 1 and "Focusrite" in prepared.notes[0]
    info = list_sets(running.sets_folder, sound_card())[0]
    assert info.usable and info.notes == prepared.notes


def test_settings_of_the_set_never_replace_the_local_ones(running, tmp_path):
    two_takes(running)
    settings_file = tmp_path / "other.toml"
    settings_file.write_text('data_dir = "C:/Users/opa/loopstation"\nvolume = 0.9\n', encoding="utf-8")
    target = running.sets_folder / "opa.loopset"
    sets.write_set(
        target, log_dir=running.settings.log_dir, samples_dir=running.settings.samples_dir,
        sample_rate=8000, pad_count=12, settings_file=settings_file,
    )
    prepared = running.session.prepare_open(target)
    commit_open(running.settings.data_dir, prepared)
    # The set's own settings.toml and its data_dir are not carried into the work folder.
    assert not (running.settings.data_dir / "settings.toml").exists()
    assert running.settings_file.read_text(encoding="utf-8") == "# test\nvolume = 0.5\n"


# ----------------------------------------------------------------- listing


def test_list_sets_newest_first_with_problems_marked(running):
    two_takes(running)
    running.session.save(running.sets_folder / "alt.loopset")
    running.clock.advance(3600)
    running.record(4, 1.0)
    running.session.save(running.sets_folder / "neu")  # a folder set
    (running.sets_folder / "notiz.txt").write_text("not a set", encoding="utf-8")
    (running.sets_folder / "kaputt.loopset").write_bytes(b"garbage")
    infos = list_sets(running.sets_folder)
    names = [info.name for info in infos]
    assert names[:2] == ["neu", "alt"] and "kaputt" in names and "notiz" not in names
    neu = infos[0]
    assert neu.usable and neu.recorded_pads == 3 and neu.undo_steps >= 3
    assert next(info for info in infos if info.name == "kaputt").usable is False


def test_list_sets_marks_a_too_new_set(running):
    two_takes(running)
    source = running.sets_folder / "a.loopset"
    running.session.save(source)
    new = running.sets_folder / "zukunft.loopset"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(new, "w") as out:
        for item in src.namelist():
            raw = src.read(item)
            if item == sets.MANIFEST_NAME:
                raw = raw.replace(b"format_version = 1", b"format_version = 3")
            out.writestr(item, raw)
    info = next(i for i in list_sets(running.sets_folder) if i.name == "zukunft")
    assert info.too_new and not info.usable and "neuere Loopstation" in info.error


def test_list_sets_of_a_missing_folder_is_empty(tmp_path):
    assert list_sets(tmp_path / "nope") == []
