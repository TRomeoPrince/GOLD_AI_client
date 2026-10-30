# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent

hiddenimports = []
hiddenimports += collect_submodules("MetaTrader5")
hiddenimports += collect_submodules("numpy")

binaries = []
binaries += collect_dynamic_libs("MetaTrader5")
binaries += collect_dynamic_libs("numpy")

datas = []
datas += collect_data_files("numpy")
datas += collect_data_files("tzdata")
datas += [(str(PROJECT_ROOT / "assets" / name), "assets") for name in ("BACKGROUND.jpg", "PROFIT.jpg", "LOSS.jpg")]

a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="AZT_Trial_Client",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
