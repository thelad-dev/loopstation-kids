"""Rubber Band is not shipped (GPL): the installer downloads it only on request.

These tests pin what can be checked without Windows: the download constants, that the task
is off by default and has a consent page, that the bundle excludes pylibrb, and the Linux
script's consent switches. The download itself (real URL, checksum, failure path) is proven
by the windows-installer workflow.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WINDOWS = ROOT / "packaging" / "windows"


def defines() -> dict[str, str]:
    text = (WINDOWS / "rubberband.inc").read_text()
    return dict(re.findall(r'^\s*#define (\w+) "([^"]*)"', text, flags=re.M))


def test_download_constants_are_a_pinned_pypi_wheel_with_a_checksum():
    values = defines()
    url = values["RubberBandUrl"]
    assert url.startswith("https://files.pythonhosted.org/packages/")
    assert url.endswith(f"pylibrb-{values['RubberBandVersion']}-cp311-cp311-win_amd64.whl")
    assert re.fullmatch(r"[0-9a-f]{64}", values["RubberBandSha256"])
    assert values["RubberBandSize"]


def test_the_wheel_version_matches_the_pin_used_for_the_tests():
    constraints = (WINDOWS / "constraints.txt").read_text()
    assert f"pylibrb=={defines()['RubberBandVersion']}" in constraints


def test_installer_task_is_off_by_default_and_has_a_consent_page():
    iss = (WINDOWS / "loopstation.iss").read_text()
    task = next(line for line in iss.splitlines() if line.startswith('Name: "rubberband"'))
    assert "Flags: unchecked" in task and "(GPL)" in task
    assert 'Name: "{app}\\rubberband"' in iss  # removed again on uninstall
    for needed in ("Lizenz: GNU General Public License", "Herkunft: {#RubberBandUrl}",
                   "Größe:", "Prüfsumme (SHA-256): {#RubberBandSha256}"):
        assert needed in iss
    # The page only shows when the task is ticked, and the download is checked and fails safe.
    assert "not WizardIsTaskSelected('rubberband')" in iss
    assert "DownloadTemporaryFile('{#RubberBandUrl}', 'pylibrb.zip', '{#RubberBandSha256}'" in iss
    assert "Rubber Band nicht installiert, einfache Engine aktiv" in iss


def test_the_bundle_never_contains_rubber_band():
    spec = (WINDOWS / "loopstation.spec").read_text()
    assert '"pylibrb"' in re.search(r"excludes=\[(.*?)\]", spec).group(1)
    assert "hiddenimports" in spec and "pylibrb" not in re.search(r"hiddenimports=\[(.*?)\]", spec).group(1)
    for name in ("requirements.txt", "pyproject.toml"):
        text = (ROOT / name).read_text()
        deps = text.split("[project.optional-dependencies]")[0] if name == "pyproject.toml" else text
        assert "pylibrb" not in deps  # not a dependency of the app


def test_windows_workflow_checks_the_download_and_not_a_bundle():
    flow = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text()
    bundle_check = next(line for line in flow.splitlines() if "foreach ($pattern in @(" in line)
    assert "pylibrb" not in bundle_check  # the bundle check no longer expects Rubber Band
    assert "Rubber Band must not be bundled" in flow
    assert "/TASKS=rubberband" in flow and "/DRubberBandSha256=" in flow
    assert "a failed download left" in flow


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
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
