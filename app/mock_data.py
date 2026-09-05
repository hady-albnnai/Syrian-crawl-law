# -*- coding: utf-8 -*-
"""mock_data.py — بيانات تجريبية واقعية لطور النموذج الأولي.

⚠️ هذا الملف مؤقت بطبيعته: عند بناء النواة (التسليمات 1–3) يُستبدل
MockDataProvider بواجهة تقرأ من storage.py الحقيقية. الواجهة لا تعرف
الفرق — كلاهما يقدم نفس الشكل (عقد Core+Shell في DESIGN-TOOL-APP.md §2).
"""
from dataclasses import dataclass

SOURCE_NAME = "law-library.syriaforums.net — مكتبة القانون السوري (منتدى phpBB)"
SOURCE_CREDIBILITY = 0.6

SECTIONS = [
    "القانون المدني", "القانون الجزائي", "أصول المحاكمات",
    "الأحوال الشخصية", "القانون التجاري", "الدساتير والقانون الدستوري",
    "القانون الإداري",
]

LOG_EVENTS = [
    ("09:41:02", "fetch", "✓ f3-montada — 200 OK — 142KB — 312ms", "ok"),
    ("09:41:05", "queue", "أُضيف 24 موضوعاً جديداً إلى الطابور الدائم", "info"),
    ("09:41:09", "fetch", "✓ t128-القانون-المدني — 200 OK — 96KB — 288ms", "ok"),
    ("09:41:10", "extract", "القانون المدني: 589 مادة — هرمية: 4 أبواب — جودة 0.94", "ok"),
    ("09:41:14", "robots", "حُجب /ucp.php?mode=register — احتراماً لـ robots.txt", "warn"),
    ("09:41:18", "quality", "t210 — يحتاج مراجعة (0.42): لا بنية مواد واضحة", "warn"),
    ("09:41:22", "save", "وثيقة + 90 مادة حُفظت (idempotent — لا تكرار عند الإعادة)", "ok"),
    ("09:41:27", "fetch", "✗ t305 — HTTP 404 — سُجّل في crawl_log", "err"),
    ("09:41:31", "extract", "قانون البينات: 90 مادة — جودة 0.88", "ok"),
    ("09:41:36", "save", "وثيقة + 308 مادة حُفظت — الأحوال الشخصية", "ok"),
]


@dataclass
class DocumentRow:
    title: str
    kind: str          # قانون / مرسوم تشريعي / نص منشور
    branch: str
    articles: int
    quality: float
    status: str        # human_verified / auto_extracted / needs_review
    year: int


DOCUMENTS = [
    DocumentRow("القانون المدني السوري", "قانون 84", "مدني", 589, 0.94, "human_verified", 1949),
    DocumentRow("قانون العقوبات العام", "قانون 148", "جزائي", 759, 0.91, "human_verified", 1949),
    DocumentRow("قانون أصول المحاكمات المدنية", "قانون 1", "أصول مدنية", 500, 0.89, "auto_extracted", 2016),
    DocumentRow("قانون البينات السوري", "قانون 350", "بينات", 90, 0.88, "auto_extracted", 1947),
    DocumentRow("قانون الأحوال الشخصية", "قانون 59", "أحوال شخصية", 308, 0.86, "auto_extracted", 1953),
    DocumentRow("قانون التجارة", "مرسوم 149", "تجاري", 750, 0.83, "auto_extracted", 1949),
    DocumentRow("قانون مجلس الدولة", "مرسوم 55", "إداري", 87, 0.81, "auto_extracted", 1959),
    DocumentRow("قانون الإيجار", "قانون 6", "مدني", 42, 0.79, "needs_review", 2001),
    DocumentRow("منشور منتدى: نقاش حول عقد الإيجار", "نص منشور", "غير مصنف", 0, 0.42, "needs_review", 0),
]

STATUS_LABELS = {
    "human_verified": ("مراجَع بشرياً", "badgeSuccess"),
    "auto_extracted": ("استخراج آلي", "badgeInfo"),
    "needs_review": ("يحتاج مراجعة", "badgeWarning"),
}

PACKAGE_TREE = [
    ("mizan_package_2026-09-05/", True),
    ("+-- laws_decrees_index.csv    (18 صفاً — أعمدة ميزان حرفياً)", False),
    ("+-- files/                      (18 ملف نصي md — أسماء لاتينية آمنة)", False),
    ("+-- articles/                   (18 ملف JSON — عقد المادة §6.2)", False),
    ("+-- manifest.json               (إصدارات + أعداد + بصمات sha256)", False),
    ("`-- REPORT.md                   (تقرير بشري + إخلاء مسؤولية)", False),
]

VALIDATION_CHECKS = [
    ("sha256 وsize_bytes مطابقة لكل ملف في الفهرس", True),
    ("لا id مكرر ولا عنوان فارغ", True),
    ("كل الوثائق المصدَّرة quality ≥ 0.75", True),
    ("وثائق needs_review مستثناة افتراضياً (2)", True),
    ("REPORT.md يذكر التاريخ والمصدر وطريقة العد", True),
]
