"""Settings for the loop grid: switch and latency."""

from __future__ import annotations

from pathlib import Path

import pytest

from loopstation.config import ConfigError, Settings, load_settings, parse_settings


def test_shipped_settings_file_matches_the_defaults():
    shipped = load_settings(Path(__file__).parent.parent / "settings.toml")
    assert shipped == Settings()
    assert shipped.loop_sync is True and shipped.latency_ms is None


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
