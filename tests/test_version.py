"""The app version is kept by hand in two places; they must agree."""

import tomllib
from pathlib import Path

import loopstation


def test_package_version_matches_pyproject() -> None:
    # loopstation.__version__ is written into the set manifest; the frozen
    # Windows bundle has no package metadata, so it cannot be read at runtime.
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    assert loopstation.__version__ == version
