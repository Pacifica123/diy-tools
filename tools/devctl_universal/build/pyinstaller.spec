# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for devctl GUI.

Run from the project root:
    pyinstaller build/pyinstaller.spec --clean --noconfirm

The final executable is written to:
    release/devctl-gui.exe
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.config import CONF

spec_dir = Path(SPECPATH).resolve()
if not spec_dir.is_dir():
    spec_dir = spec_dir.parent
project_root = spec_dir.parent
release_dir = project_root / "release"
release_dir.mkdir(exist_ok=True)

# Keep generated release payloads in release/ as documented by BUILD_WINDOWS_EXE.md
# instead of PyInstaller's default dist/ directory.
CONF["distpath"] = str(release_dir)

icon_file = project_root / "gui" / "assets" / "icon.ico"
icon_arg = str(icon_file) if icon_file.exists() else None

datas = [
    # Child mode imports bundled devctl.py from sys._MEIPASS, so keep it at the
    # bundle root even if PyInstaller also discovers it as a hidden import.
    (str(project_root / "devctl.py"), "."),
]
if icon_file.exists():
    datas.append((str(icon_file), "gui/assets"))


a = Analysis(
    [str(project_root / "gui" / "devctl_gui.py")],
    pathex=[str(project_root), str(project_root / "gui")],
    binaries=[],
    datas=datas,
    hiddenimports=["devctl", "devctl_runner"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="devctl-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)
