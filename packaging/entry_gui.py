# -*- coding: utf-8 -*-
"""entry_gui.py — نقطة الدخول المجمدة (PyInstaller).

يفصل التجميع عن app.main حتى تبقى حزمة app قابلة للاستيراد كوحدة
ويبقى --smoke متاحاً من الثنائي المجمد (تستخدمه CI).
"""
import sys
from pathlib import Path

# التشغيل من داخل مجلد onedir: بيانات العمل (قاعدة/لقطات/حزم) بجانب الثنائي
import os
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
