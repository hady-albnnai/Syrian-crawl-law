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


# ------------------------------------------------- إصلاح طبقة نص الـPDF (ف٥)
# ملفات قديمة (مجموعات الهيئة العامة ونحوها) تخرج من الـPDF بطبقة نص فيها
# خللان موثقان، يُصلحان هنا **بلا تخمين قانوني**:
#   1 دخائل محارف من خريطة الخط: رموز/أرقام لاتينية داخل الكلمات العربية
#     («النق¦ض» «أ6سا6س» «مDDان») ⇒ تُحذف لأنها بين حروف عربية حصراً.
#   2 أسطر مكتوبة بالترتيب البصري (كلمات معكوسة): «2016 لعام 159 القضية أساس»
#     ⇒ تُقلب كلمات في السطر فقط إن كان القلب يرفع درجة القرائن البنيوية.
_ARL = "\u0621-\u064a"
_ARX = "\u0621-\u064a\u064b-\u065f\u0670"      # الحروف + التشكيل
_JUNK = r"\x00-\x1f\x7f-\x9f\xa6\xae\xb7*@{}0-9A-Za-z\u02ee\u0114\u0040\ufffd"
# الدخائل بين حرفين عربيين حصراً — لا تمس الأرقام المستقلة ولا سلاسل الأرقام
_JUNK_INSIDE_RE = re.compile(rf"(?<=[{_ARX}:])[{_JUNK}]+(?=[{_ARX}])")
# فصل لصق «كلمة+رقم» قبل القلب حتى تصير الوحدات صحيحة — النقطتان تُفصلان
# عن الأرقام فقط («للعام140:قرار») لا بين حرفين («القضية:أساس» تبقى ملزوقة)
_AR_DIGIT_SPLIT_RE = re.compile(rf"(?<=[{_ARX}])(?=\d)|(?<=\d)(?=[{_ARX}:])|(?<=:)(?=\d)")
_CORRUPT_RE = re.compile(r"المبد[\s\u060d]+أ")  # فصل شكل الهمزة عن «المبدأ» (طبقة قديمة)
_ORIENT_RXS = [re.compile(p) for p in (
    r"تاريخ\s*:?\s*\d{4}[/\\\-]",           # تاريخ تتبعه سنة ⇒ الترتيب منطقي
    r"(?:قرار|اساس|القضية|رقم)\s*:?\s*\d{1,6}",
    r"لعام\s*\d{4}", r"لسنة\s*\d{4}",
    r"محكمة\s+النقض", r"الهيئة\s+العامة",
    r"العدد(?:ان)?\s*/?\s*\d", r"القاعدة\s*:?\s*\d", r"الصفحة\s*:?\s*\d",
    r"الغرفة|الدوائر|الدائرة",
)]


def _orient_score(line: str) -> int:
    return sum(len(rx.findall(line)) for rx in _ORIENT_RXS)


def _orient_line(line: str) -> str:
    line = _AR_DIGIT_SPLIT_RE.sub(" ", line)
    toks = line.split()
    if len(toks) < 2:
        return line
    rev = " ".join(toks[::-1])
    return rev if _orient_score(rev) > _orient_score(line) else line


def repair_pdf_text(text: str) -> str:
    """إصلاح دخائل المحارف + اتجاه الأسطر البصرية — بلا أي تخمين قانوني."""
    text = text or ""
    prev = None
    while prev != text:                     # دخائل متراكبة («مDDان» ⇒ تمريران)
        prev = text
        text = _JUNK_INSIDE_RE.sub("", text)
    text = _CORRUPT_RE.sub("المبدأ", text)
    return "\n".join(_orient_line(l) for l in text.split("\n"))


def extract_pdf_text(source) -> str:
    """نص صفحات الملف كلها مطبَّعاً. `source`: مسار أو بايتات."""
    doc = fitz.open(source) if not isinstance(source, (bytes, bytearray)) \
        else fitz.open(stream=bytes(source), filetype="pdf")
    try:
        parts = [p.get_text() for p in doc if p.get_text().strip()]
    finally:
        doc.close()
    return repair_pdf_text(normalize_text("\n\n".join(parts)))


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
