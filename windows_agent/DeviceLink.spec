# -*- mode: python ; coding: utf-8 -*-
import os
import customtkinter
from PyInstaller.utils.hooks import collect_all

customtkinter_path = os.path.dirname(customtkinter.__file__)

# Helper to recursively gather all files in a directory
def gather_dir_files(src_dir, dest_root):
    gathered = []
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            full_path = os.path.join(root, file)
            # Skip python cache files
            if '__pycache__' in full_path or file.endswith('.pyc'):
                continue
            rel_path = os.path.relpath(root, src_dir)
            if rel_path == '.':
                dest_dir = dest_root
            else:
                dest_dir = os.path.join(dest_root, rel_path)
            # For Windows PyInstaller compatibility, keep paths normalized
            dest_dir = dest_dir.replace('\\', '/')
            gathered.append((full_path, dest_dir))
    return gathered

datas = [
    ('icon.ico', '.'), 
    ('icon.png', '.')
]
datas += gather_dir_files(customtkinter_path, 'customtkinter')

binaries = []
hiddenimports = ['_cffi_backend', 'requests', 'sseclient']

tmp_ret = collect_all('customtkinter')
# Add collected binaries and hiddenimports
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# Add any collected datas from collect_all that don't duplicate
for d in tmp_ret[0]:
    if 'customtkinter' not in d[1]:
        datas.append(d)

a = Analysis(
    ['DeviceLink.pyw'],
    pathex=[],
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
    name='DeviceLink',
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
    icon=['icon.ico'],
)
