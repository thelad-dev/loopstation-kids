"""Settings for the loop grid: switch and latency."""

from __future__ import annotations

import re
import string
import tomllib
from dataclasses import fields
from pathlib import Path

import pytest

from loopstation.config import (
    RESTART_KEYS,
    SETTING_COMMENTS,
    ConfigError,
    Settings,
    format_toml_value,
    load_settings,
    parse_settings,
    render_settings_text,
    settings_values,
)
from loopstation.controller import LIVE_DEVICE_SETTINGS, LIVE_LEVEL_SETTINGS, LIVE_SETTINGS


def test_shipped_settings_file_matches_the_defaults():
    shipped = load_settings(Path(__file__).parent.parent / "settings.toml")
    assert shipped == Settings()
    assert shipped.loop_sync is True and shipped.latency_ms is None


def test_soft_seam_is_on_by_default_and_can_be_switched_off():
    assert Settings().soft_seam is True
    assert parse_settings({}).soft_seam is True
    assert parse_settings({"soft_seam": False}).soft_seam is False
    with pytest.raises(ConfigError, match="soft_seam"):
        parse_settings({"soft_seam": "nein"}, "settings.toml")


def test_loop_sync_and_latency_values():
    assert parse_settings({"loop_sync": False}).loop_sync is False
    assert parse_settings({"latency_ms": "auto"}).latency_ms is None
    assert parse_settings({"latency_ms": 35}).latency_ms == 35.0
    assert parse_settings({"latency_ms": 12.5}).latency_ms == 12.5


@pytest.mark.parametrize("raw", [{"latency_ms": "Auto"}, {"latency_ms": -1}, {"latency_ms": 1001},
                                 {"latency_ms": True}, {"loop_sync": "ja"}])
def test_invalid_values_name_the_key(raw):
    with pytest.raises(ConfigError, match=next(iter(raw))):
        parse_settings(raw, "settings.toml")


# --- the shipped file against the code ----------------------------------------------------------

SHIPPED_PATH = Path(__file__).resolve().parent.parent / "settings.toml"
LIVE_MARKERS = ("Wirkt sofort", "Wirkt bei der nächsten")
RESTART_MARKER = "Neustart"


def _all_live_keys() -> set[str]:
    return set(LIVE_SETTINGS) | set(LIVE_DEVICE_SETTINGS) | {key for key, _ in LIVE_LEVEL_SETTINGS}


def _comment_block(lines: list[str], key: str) -> str:
    """The comment lines above ``key`` (up to the blank line; a directly preceding key line is skipped)."""
    index = next(i for i, line in enumerate(lines) if line.startswith(f"{key} ="))
    block = []
    while index > 0 and lines[index - 1].strip() and lines[index - 1][0] in "#" + string.ascii_lowercase:
        index -= 1
        if lines[index].startswith("#"):
            block.append(lines[index])
    return "\n".join(block)


def test_shipped_file_has_exactly_the_keys_values_and_types_of_the_defaults():
    raw = tomllib.loads(SHIPPED_PATH.read_text(encoding="utf-8"))
    defaults = settings_values(Settings())
    assert set(raw) == set(defaults)
    for key, default in defaults.items():
        # The file holds the text the settings writer would produce for the default.
        assert raw[key] == tomllib.loads(f"{key} = {format_toml_value(key, default)}")[key], key
        if isinstance(default, bool):
            assert type(raw[key]) is bool, key
        elif default is None or isinstance(default, str | Path):
            assert type(raw[key]) is str, key
        else:
            assert type(raw[key]) in (int, float), key
    assert parse_settings(raw, "settings.toml") == Settings()


def test_writer_leaves_the_shipped_file_untouched_for_the_defaults():
    text = SHIPPED_PATH.read_text(encoding="utf-8")
    assert render_settings_text(text, Settings()) == text


def test_a_file_made_from_nothing_has_every_key_with_its_comment():
    text = render_settings_text("", Settings())
    assert parse_settings(tomllib.loads(text)) == Settings()
    lines = text.splitlines()
    for key in settings_values(Settings()):
        assert f"# {SETTING_COMMENTS[key]}" in text, key
        assert _comment_block(lines, key), key


def test_live_and_restart_keys_partition_the_settings():
    names = {f.name for f in fields(Settings)}
    assert set(RESTART_KEYS).isdisjoint(_all_live_keys())
    assert set(RESTART_KEYS) | _all_live_keys() == names


def test_shipped_comments_say_live_or_restart_as_the_code_does():
    lines = SHIPPED_PATH.read_text(encoding="utf-8").splitlines()
    for key in settings_values(Settings()):
        block = _comment_block(lines, key)
        if key in RESTART_KEYS:
            assert RESTART_MARKER in block, key
            assert not any(marker in block for marker in LIVE_MARKERS), key
        else:
            assert any(marker in block for marker in LIVE_MARKERS), key
            assert RESTART_MARKER not in block, key


def test_writer_comments_say_live_or_restart_as_the_code_does():
    for key, comment in SETTING_COMMENTS.items():
        if key in RESTART_KEYS:
            assert "Wirkt erst nach einem Neustart" in comment, key
        else:
            assert any(marker in comment for marker in LIVE_MARKERS), key
            assert "Neustart" not in comment, key


def test_file_header_names_exactly_the_restart_keys():
    header = SHIPPED_PATH.read_text(encoding="utf-8").split("\n\n")[0]
    named = {key for key in settings_values(Settings()) if re.search(rf"\b{key}\b", header)}
    assert named == set(RESTART_KEYS)
