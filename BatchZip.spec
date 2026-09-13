from PyInstaller.utils.hooks import collect_all


qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all("qfluentwidgets")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=qfw_binaries,
    datas=qfw_datas + [("assets", "assets")],
    hiddenimports=qfw_hiddenimports + ["winotify"],
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
    name="BatchZip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/icon/app_icon.ico",
    version="version_info.txt",
)
