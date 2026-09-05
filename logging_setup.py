# -*- coding: utf-8 -*-
"""logging_setup.py — السجلات الموحدة (التسليم 1).

بديل print المبعثر: وحدة واحدة تهيئ جذر "mizan" بمخرجين:
- طرفية (رسالة فقط — نفس تجربة المستخدم السابقة، UTF-8 على ويندوز)
- ملف logs/harvester.log (توقيت + مستوى + اسم الوحدة، للتدقيق)

الاستعمال:  log = get_log("fetch")  ثم log.info(...)
"""
import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"


def setup(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger("mizan")
    if root.handlers:
        return root
    root.setLevel(level)
    root.propagate = False

    try:  # إصلاح طباعة العربية على ويندوز (منقول من fetcher القديم)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    class _PipeSafeHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                super().emit(record)
            except BrokenPipeError:
                pass  # أغلق المستهلك الأنبوب (head/أنبوب مغلق) — ليس خطأ منتجياً

    console = _PipeSafeHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(exist_ok=True)
        fh = logging.FileHandler(LOG_DIR / "harvester.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(fh)
    except OSError:
        pass  # الطرفية تكفي إن تعذر الملف
    return root


def get_log(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(f"mizan.{name}")
