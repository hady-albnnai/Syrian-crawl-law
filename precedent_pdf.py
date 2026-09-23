# -*- coding: utf-8 -*-
"""precedent_pdf.py — حصاد الاجتهادات من ملفات PDF محلية (ف٥، 2026-09-23).

الصيغة المصمَّمة لها: أطروحة الدكتوراه من مستودع جامعة دمشق (370 صفحة بهوامش
استشهادات) وما شابهها من ملفات لا يستطيع الزاحف الوصول إليها من خارج الشبكة —
المالك ينزّل الملف على جهازه ثم يوجّه الأمر إليه:

    python -m cli precedents-pdf مسار\\الملف.pdf --source-url <رابط الأصل>

اكتشاف قِيس أثناء البناء: بعض ملفات PDF تُخرج العربية «بأشكال العرض»
(نطاقا U+FB50–FDFF وU+FE70–FEFF) لا بالحروف القياسية (نقض)، فتنكسر أنماط
المحلل. الحل المطبق هنا: تطبيع NFKC الشامل لكل النص المستخرج — قِيس أنه
يحوّل أشكال العرض إلى حروفها القياسية بلا فقد.

المسار: فتح الملف بـ pymupdf ⇒ نص الصفحات كلها ⇒ تطبيع وتنظيف ⇒ المحلل العام
⇒ بوابة MIN_HITS ⇒ كتابة عبر `ingest_page` ⇒ pending حتى الاعتماد.
الهوية للاستئناف: `--source-url` إن أُعطيت، وإلا مسار الملف.
"""
from __future__ import annotations

import re
import unicodedata

from logging_setup import get_log
from precedent_parser import parse_text
from precedent_source import ingest_page, already_ingested

try:  # الاسم الجديد أولاً؛ القديم احتياطاً للتثبيتات الأقدم
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

log = get_log("precedent_pdf")

MIN_HITS = 3


def normalize_text(text: str) -> str:
    """تطبيع شامل: أشكال العرض ⇒ حروف قياسية، وتنظيف الأسطر والمسافات.

    دالة نقية — قابلة للاختبار مباشرة على معطيات حقيقية من ملفات حقيقية.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r", "").replace("\x0c", "\n")
    text = re.sub(r"[ \t\u200b\u200e\u200f]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(source) -> str:
    """نص صفحات الملف كلها مطبَّعاً. `source`: مسار أو بايتات."""
    doc = fitz.open(source) if not isinstance(source, (bytes, bytearray)) \
        else fitz.open(stream=bytes(source), filetype="pdf")
    try:
        parts = [p.get_text() for p in doc if p.get_text().strip()]
    finally:
        doc.close()
    return normalize_text("\n\n".join(parts))


def harvest_pdf(conn, path: str, source_url: str | None = None,
                source_site: str | None = None, dry_run: bool = False,
                min_hits: int = MIN_HITS, extractor=None) -> dict:
    """حقن `extractor(path)->str` للاختبار؛ الافتراضي `extract_pdf_text`."""
    extractor = extractor or extract_pdf_text
    identity = source_url or f"file:{path}"
    site = source_site or ("pdf" if not str(identity).startswith("http")
                           else str(identity).split("/")[2].removeprefix("www."))
    st = {"source": identity, "site": site, "citations": 0, "written": 0,
          "unsourced": 0, "skipped_low": 0, "seen": 0, "pages_written": 0}
    if already_ingested(conn, identity):
        st["seen"] = 1
        return st
    text = extractor(path)
    hits = [c for c in parse_text(text) if c.is_exportable()]
    if len(hits) < min_hits:
        st["skipped_low"] = 1
        log.info(f"   ⚠️ {identity}: {len(hits)} استشهاداً فقط — دون بوابة الجودة ({min_hits})")
        return st
    st["citations"] = len(hits)
    if dry_run:
        return st
    r = ingest_page(conn, identity, "", source_site=site,
                    text_fn=lambda _h, _t=text: _t)
    st["pages_written"] = 1
    for k in ("written", "unsourced"):
        st[k] = r[k]
    log.info(f"   {site}: كُتب {r['written']} استشهاداً من {identity}")
    return st
