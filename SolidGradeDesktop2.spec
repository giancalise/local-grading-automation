# -*- mode: python ; coding: utf-8 -*-
#
# Milestone 2 changed two things here. Both are the kind of omission that
# produces a build which starts fine and is broken in a way the developer
# never sees, so they are called out rather than left to be inferred:
#
#   1. datas now ships the ui/ folder. Without it the frozen app serves a
#      404 for "/" and the window opens empty -- the code all works, the
#      files simply are not there. app.py's _resource_path() looks next to
#      the exe first, then sys._MEIPASS.
#
#   2. hiddenimports now names pywebview's EdgeChromium backend. pywebview
#      selects its platform backend by importing it dynamically at runtime,
#      which static import scanning cannot see, so a frozen build drops it
#      and falls back to a backend that cannot render this UI (or fails to
#      start a window at all). This is the same class of failure as the
#      scipy.ndimage one below, and it is caught by the same discipline:
#      name it explicitly rather than trusting the scan.
#
# scipy.ndimage remains on the list for the reason SPEC_v0.2 2.4 and
# DISCOVERY_REPORT.md Phase 4.2 give: trimesh needs it for VoxelGrid.fill()
# but declares scipy only as an optional extra. MILESTONE_1_REPORT.md notes
# that current pyinstaller-hooks-contrib ships a trimesh hook that already
# pulls it in, so this is now belt-and-braces -- the 2.4 self-test is the
# real backstop, not this flag.

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('test_underdefined.SLDPRT', '.'),   # 2.4 self-test fixture
        ('ui', 'ui'),                        # the Milestone 2 UI
    ],
    hiddenimports=[
        'scipy.ndimage',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
    ],
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
    name='SolidGradeDesktop2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
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
    name='SolidGradeDesktop2',
)
