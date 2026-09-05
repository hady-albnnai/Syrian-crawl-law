# -*- mode: python ; coding: utf-8 -*-
"""mizan-harvester.spec — تجميع «حاصدة ميزان» (onedir).

البناء:  python -m PyInstaller packaging/mizan-harvester.spec
النواتج: dist/mizan-harvester/  (مجلد كامل قابل للنسخ/الضغط للتوزيع)

ملاحظات موثقة:
- onedir لا onefile: أسرع إقلاعاً وأسهل تدقيقاً للمحامين (بلا مستخرج مؤقت).
- الخطوط والسمات تُحمل عبر app/assets — datas أدناه.
- وحدات تستورد كسولاً داخل دوال الواجهة لا يراها التحليل الساكن —
  hiddenimports صريح (crawler/exporter/…).
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# المسارات داخل spec تُحل نسبةً لموقعه — نثبّت الجذر صراحة
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.dirname(SPEC_DIR)
block_cipher = None

hiddenimports = collect_submodules("app") + [
    # نواة تُستورد كسولاً من الشاشات/CLI
    "crawler", "crawl_queue", "exporter", "migrations", "database",
    "discovery", "fetcher", "extractor", "extractor_v4", "urls", "config",
    "logging_setup", "cli", "recon",
    # اعتمادات غير بايثونية التتبع
    "bs4", "lxml", "requests",
]

a = Analysis(
    [os.path.join(SPEC_DIR, "entry_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "app", "assets"), "app/assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "IPython"],
    win_no_prefer_redirects=False,
    win_private_config=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mizan-harvester",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # نافذة طرفية مصاحبة تسجل أحداث الزحف — مفيدة للدعم
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mizan-harvester",
)
