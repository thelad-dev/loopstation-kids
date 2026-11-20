# PyInstaller spec for the Windows build (onedir: one folder, fast start, nothing unpacked to %TEMP%).
#
#   python packaging/windows/make_icon.py build/loopstation.ico
#   pyinstaller --noconfirm packaging/windows/loopstation.spec
#
# Result: dist/Loopstation/Loopstation.exe plus its _internal folder.
# The hooks from pyinstaller-hooks-contrib bundle Qt (PySide6), the PortAudio
# DLLs of sounddevice (with and without ASIO) and the libsndfile DLL of soundfile. mido loads its MIDI
# backend by name at run time, so it is listed as a hidden import here. Rubber Band (pylibrb, GPL) is
# deliberately excluded; the windows-installer workflow checks that it is not in the bundle.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - SPECPATH is set by PyInstaller
ICON = ROOT / "build" / "loopstation.ico"
if not ICON.is_file():
    raise SystemExit(f"{ICON} is missing: run python packaging/windows/make_icon.py build/loopstation.ico first")

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "windows" / "entry.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "settings.toml"), ".")],
    hiddenimports=["loopstation.installed", "mido.backends.rtmidi", "rtmidi"],
    # pylibrb (Rubber Band, GPL) must never end up in the bundle, even if the build
    # environment has it: the installer downloads it only on request.
    excludes=["tkinter", "pylibrb"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Loopstation",
    console=False,
    icon=str(ICON),
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="Loopstation",
    upx=False,
)
