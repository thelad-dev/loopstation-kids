"""Rubber Band is not shipped (GPL): the installer downloads it only on request.

These tests pin what can be checked without Windows: the download constants, the spec's
excludes (the real spec is run with stubbed build classes), the workflow's steps (parsed, not
grepped) and the Linux script's consent switches. The checksum check itself is Inno Setup's
DownloadTemporaryFile and only runs on Windows: the windows-installer workflow installs with
consent (right and wrong checksum) and without, and fails if the app is missing afterwards.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parent.parent
WINDOWS = ROOT / "packaging" / "windows"


def defines() -> dict[str, str]:
    text = (WINDOWS / "rubberband.inc").read_text()
    return dict(re.findall(r'^\s*#define (\w+) "([^"]*)"', text, flags=re.M))


def test_download_constants_are_a_pinned_pypi_wheel_with_a_checksum():
    values = defines()
    url = values["RubberBandUrl"]
    assert url.startswith("https://files.pythonhosted.org/packages/")
    assert url.endswith(f"pylibrb-{values['RubberBandVersion']}-cp312-abi3-win_amd64.whl")
    assert re.fullmatch(r"[0-9a-f]{64}", values["RubberBandSha256"])
    assert values["RubberBandSize"]


def test_the_wheel_version_matches_the_pin_used_for_the_tests():
    constraints = (WINDOWS / "constraints.txt").read_text()
    assert f"pylibrb=={defines()['RubberBandVersion']}" in constraints


def load_spec_arguments() -> dict[str, dict]:
    """Run the real PyInstaller spec with stubbed build classes and return each call's keyword arguments."""
    calls: dict[str, dict] = {}

    def stub(name):
        def build(*args, **kwargs):
            calls[name] = kwargs
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        return build

    icon = ROOT / "build" / "loopstation.ico"
    created = not icon.exists()
    if created:
        icon.parent.mkdir(exist_ok=True)
        icon.write_bytes(b"")
    try:
        namespace = {"SPECPATH": str(WINDOWS), "Analysis": stub("Analysis"), "PYZ": stub("PYZ"),
                     "EXE": stub("EXE"), "COLLECT": stub("COLLECT")}
        exec(compile((WINDOWS / "loopstation.spec").read_text(), "loopstation.spec", "exec"), namespace)
    finally:
        if created:
            icon.unlink()
    return calls


def test_the_bundle_never_contains_rubber_band():
    analysis = load_spec_arguments()["Analysis"]
    assert "pylibrb" in analysis["excludes"]
    assert "pylibrb" not in analysis["hiddenimports"]
    for name in ("requirements.txt", "pyproject.toml"):
        text = (ROOT / name).read_text()
        deps = text.split("[project.optional-dependencies]")[0] if name == "pyproject.toml" else text
        assert "pylibrb" not in deps  # not a dependency of the app


def test_windows_workflow_runs_the_consent_and_failure_paths():
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "windows-installer.yml").read_text())
    steps = next(iter(flow["jobs"].values()))["steps"]
    by_name = {step["name"]: step.get("run", "") for step in steps if "name" in step}
    bundle = by_name["Check Rubber Band is NOT in the bundle"]
    assert "pylibrb*" in bundle and "throw" in bundle
    download = by_name["Try the optional Rubber Band download (consent given, then a wrong checksum)"]
    assert download.count("/TASKS=rubberband") == 2  # consent given: right and wrong checksum
    assert "throw" in download
    try_installer = by_name["Try the installer (install, update, uninstall; recordings stay)"]
    assert "/TASKS=rubberband" not in try_installer  # without consent nothing is downloaded


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs a real bash (on Windows bash is the WSL launcher stub)",
)
@pytest.mark.parametrize(
    ("args", "installs"),
    [([], False), (["--yes"], False), (["--no-rubberband"], False), (["--rubberband"], True)],
)
def test_linux_script_installs_rubber_band_only_with_explicit_consent(args, installs):
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "install-linux.sh"), "--dry-run", "--no-system-packages", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert ("pylibrb" in result.stdout) is installs
    if not installs:
        assert "Rubber Band wird nicht installiert" in result.stdout
