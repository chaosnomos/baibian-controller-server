# -*- mode: python ; coding: utf-8 -*-
# TPadServer PyInstaller 打包配置
# 将 Python 脚本和所有依赖打包成单个 exe 文件（无控制台窗口）

block_cipher = None

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pynput.mouse._win32',
        'pynput.keyboard._win32',
        'pynput.mouse._dummy',
        'pynput.keyboard._dummy',
        'pynput._util.win32',
        'bleak',
        'bleak.backends.winrt.client',
        'bleak.backends.winrt.scanner',
        'bleak.backends.winrt.service',
        'bleak.backends.winrt.characteristic',
        'bleak.backends.winrt.descriptor',
        'bleak.backends.winrt.manufacturer_data',
        'winrt.windows.devices.bluetooth',
        'winrt.windows.devices.bluetooth.advertisement',
        'winrt.windows.devices.bluetooth.genericattributeprofile',
        'winrt.windows.devices.enumeration',
        'winrt.windows.devices.radios',
        'winrt.windows.foundation',
        'winrt.windows.foundation.collections',
        'winrt.windows.storage.streams',
        'winrt._runtime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pytest',
        'unittest',
    ],
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
    name='TPadServer',
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
    icon=None,
)
