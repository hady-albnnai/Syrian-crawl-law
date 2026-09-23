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
    "logging_setup", "cli", "recon", "autopilot", "engines", "answer",
    "search", "chunker",
    # خطة الاكتشاف الذاتي (self-discovery) — تُستورد كسولاً من core_data
    # وشاشة «الفجوات والتعلّم» — كانت غائبة فتفشل بالنسخة المجمَّدة فقط.
    "law_identity", "dedup", "source_quality", "learning", "gap_analysis",
    # عقد الحزمة وبوابتها والحقن في ميزان — كلها تُستورد داخل دوال (كسولاً)،
    # فPyInstaller لا يراها. غيابها كان يجعل البوابة والحقن يفشلان في النسخة
    # المجمَّدة فقط، والشاشة تبتلع الخطأ وتعرض نصّه بدل أن تسقط.
    "verify_package", "package_manifest", "mizan_injector", "official_seed",
    "community_seed", "doc_nature", "law_parts", "postprocess", "named_laws", "regulations", "exclusions", "issue_date", "precedent_parser", "precedent_source", "damascusbar_source", "precedent_export", "article_links", "missing_targets", "core_laws", "syrialaw_api", "precedent_syrialaw", "precedent_wp", "precedent_blogger", "bunud_source", "law_status", "chunker", "source_matrix",
    # أوامر CLI تُستورد داخل دوالها — كانت غائبة فـ`hf-import` و`wayback-crawl`
    # يفشلان في النسخة المجمَّدة وحدها (كشفها حارس tests/test_packaging_drift.py)
    "hf_syria_laws", "wayback_source", "wipo_source", "answer", "search",
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
