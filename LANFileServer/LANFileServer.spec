# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_dir = Path(SPEC).resolve().parent

a = Analysis(
    ['/Users/jobs/Documents/Github/JobsGenesis/JobsPythonTools.py/LANFileServer.py/LANFileServer/LANFileServer.py'],
    pathex=[],
    binaries=[],
    datas=[(str(project_dir.parent / 'icon.png'), '.')],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='LANFileServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='universal2',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LANFileServer',
)
app = BUNDLE(
    coll,
    name='LANFileServer.app',
    icon=None,
    bundle_identifier=None,
)
