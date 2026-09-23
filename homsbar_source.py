# -*- coding: utf-8 -*-
"""homsbar_source.py — فرع نقابة المحامين بحمص: خريطة الموقع ⇒ مقالات الاجتهاد ⇒ المرفقات (ف٥، 2026-09-23).

القياس الحي للموقع (موثق في DELIVERY/SOURCE-REFINEMENT-2026-09-23.md):
- خريطة ووردبريس الأساسية `wp-sitemap.xml` موجودة (`sitemap_index.xml` غير موجود)،
  وفيها نوع `juris_article` = 12 مقال اجتهادات (هيئة عامة، مجلس دولة، إيجاري…).
- واجهة REST مقفلة (`restx_logged_out`/401) ⇒ المسار الوحيد: خريطة الموقع + قراءة
  HTML مباشرة.
- كل مقال = صفحة تعريفية + روابط تحميل مباشرة بصيغة «انقر هنا للتحميل» تشير إلى
  `wp-content/uploads/...` بامتدادات .doc/.docx/.zip (وقد يخالطها pdf).

المسار: تعداد مقالات الاجتهاد من الخريطة ← جلب كل صفحة ← استخراج روابط الرفع ←
تنزيل الملفات ← تفريغ النص محلياً بحسب النوع (بلا تبعيات جديدة) ← المحلل العام
`parse_text` ← قبول المقال إن أعطى ≥ MIN_HITS استشهاداً سورياً بهوية ← كتابة
عبر `ingest_page` نفسها ⇒ حالة `pending` حتى الاعتماد.

استئناف العمل: هوية المقال هي رابط صفحته؛ `already_ingested` يمنع إعادة التنزيل.
"""
from __future__ import annotations

import io
import re
import time
import zipfile
import html as _html
from urllib.parse import urljoin

import requests

from config import USER_AGENT
from logging_setup import get_log
from precedent_parser import parse_text
from precedent_source import ingest_page, already_ingested, article_text

log = get_log("homsbar_source")

BASE = "https://www.homsbar.org"
SOURCE_SITE = "homsbar.org"
MIN_HITS = 3
POLITE_DELAY = 1.0
_ATT_EXT = r"(?:docx?|zip|pdf|txt)"
_ATT_RX = re.compile(rf"""(?:href|src)\s*=\s*["']([^"']*wp-content/uploads/[^"']*\.{_ATT_EXT})["']""", re.I)
_MAX_ZIP_MEMBERS = 200
_MAX_ZIP_TOTAL = 50 * 1024 * 1024


# ------------------------------------------------------------- الجلب المهذب
def _get(url: str, as_bytes: bool = False, http_get=None):
    if http_get:
        return http_get(url)
    last = None
    for i in range(4):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"http {r.status_code}")
            return r.status_code, (r.content if as_bytes else r.text), dict(r.headers)
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"homsbar_fetch_failed: {url} — {last}")


# ------------------------------------------------------------- تعداد المقالات
def list_juris_urls(http_get_text=None, base: str = BASE) -> list[str]:
    """خريطة الموقع الأساسية ⇒ خرائط `juris_article` ⇒ روابط المقالات."""
    try:
        code, body, _ = _get(base + "/wp-sitemap.xml", http_get=http_get_text)
    except RuntimeError as e:
        log.info(f"   ⚠️ {e}")
        return []
    if code != 200:
        return []
    sub_maps = re.findall(r"<loc>\s*([^<]*juris_article[^<]*)\s*</loc>", body)
    urls: list[str] = []
    for sm in sub_maps:
        time.sleep(POLITE_DELAY / 2)
        try:
            c2, b2, _ = _get(sm.strip(), http_get=http_get_text)
        except RuntimeError as e:
            log.info(f"   ⚠️ {e}")
            continue
        if c2 == 200:
            urls += [u.strip() for u in re.findall(r"<loc>\s*([^<]+)\s*</loc>", b2)]
    return urls


def page_attachments(page_html: str, base: str = BASE) -> list[str]:
    """روابط الرفع في صفحة المقال (مطلقة، بلا تكرار، بترتيب الورود).

    يُطبّع «www.» كي لا يُحسب الرابط النسبي والمطلق المكرر مرتين
    (صفحات الموقع تخلط بين الصيغتين).
    """
    out, seen = [], set()
    for m in _ATT_RX.finditer(page_html or ""):
        u = urljoin(base + "/", _html.unescape(m.group(1)))
        u = re.sub(r"(?<=://)www\.", "", u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ------------------------------------------------------------- تفريغ الملفات
def _docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            return _zip_text(raw)  # أرشيف مقنّع بامتداد docx
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    txt = re.sub(r"<[^>]+>", "", xml)
    return _html.unescape(txt)


def _pdf_text(raw: bytes) -> str:
    try:
        import fitz  # pymupdf — اختياري هنا؛ غيابه لا يكسر بقية الأنواع
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        return "\n".join(p.get_text() for p in doc)
    except Exception:
        return ""


_AR_RUN = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF0-9\s\.\,\;\:\(\)\[\]«»ـ\-/\"'\?\!\*\%&\+]+")


def _arabic_runs(s: str, min_len: int = 25) -> list[str]:
    runs = []
    for r in _AR_RUN.findall(s):
        r = r.strip()
        if len(r) >= min_len and any("\u0600" <= ch <= "\u06FF" for ch in r):
            runs.append(r)
    return runs


def _legacy_doc_text(raw: bytes) -> str:
    """Word 97-2003 (.doc): استخراج استرشادي بلا تبعيات خارجية.

    يُجرّب ترميزان شائعان لتخزين العربية في ملفات وورد الثنائية —
    UTF-16LE (الأغلب) وCP1256 — ويُعاد النص الأكثر غنى بالمقاطع العربية؛
    والمحضر النهائي للمحلل العام وبوابة الجودة (MIN_HITS)، لا لهذا الاستخراج.
    """
    candidates = []
    try:
        candidates.append(raw.decode("utf-16-le", "ignore"))
    except Exception:
        pass
    try:
        candidates.append(raw.decode("cp1256", "ignore"))
    except Exception:
        pass
    best = ""
    for c in candidates:
        t = "\n".join(_arabic_runs(c))
        if len(t) > len(best):
            best = t
    return best


def _zip_text(raw: bytes, depth: int = 0) -> str:
    if depth > 2:
        return ""
    parts, total = [], 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return ""
    for info in zf.infolist():
        if info.is_dir() or len(parts) >= _MAX_ZIP_MEMBERS or total >= _MAX_ZIP_TOTAL:
            continue
        if not re.search(rf"\.{_ATT_EXT}$", info.filename, re.I):
            continue
        total += info.file_size
        data = zf.read(info)
        t = extract_text(data, depth + 1)
        if t.strip():
            parts.append(t)
    return "\n\n".join(parts)


def extract_text(raw: bytes, depth: int = 0) -> str:
    """تفريغ النص من ملف بحسب بصمته الفعلية — لا بحسب امتداده وحده."""
    if not raw:
        return ""
    if raw[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if "word/document.xml" in z.namelist():
                    return _docx_text(raw)
        except zipfile.BadZipFile:
            pass
        return _zip_text(raw, depth)
    if raw[:5] == b"%PDF-":
        return _pdf_text(raw)
    if raw[:4] == b"\xd0\xcf\x11\xe0":
        return _legacy_doc_text(raw)
    head = raw[:512].lstrip()
    if head.startswith(b"<") or b"<html" in raw[:2048].lower():
        return article_text(raw.decode("utf-8", "ignore"))
    for enc in ("utf-8", "cp1256"):
        try:
            t = raw.decode(enc)
            runs = _arabic_runs(t, min_len=15)
            if runs:
                return "\n".join(runs)
        except Exception:
            continue
    return ""


# ------------------------------------------------------------- الحصاد
def harvest(conn, http_get_text=None, http_get_bytes=None, dry_run: bool = False,
            max_pages: int | None = None, min_hits: int = MIN_HITS,
            base: str = BASE) -> dict:
    st = {"site": SOURCE_SITE, "juris_pages": 0, "attachments": 0, "downloaded": 0,
          "candidates": 0, "skipped_low": 0, "pages_written": 0, "citations": 0,
          "written": 0, "unsourced": 0, "seen": 0}
    urls = list_juris_urls(http_get_text, base)
    log.info(f"{SOURCE_SITE}: {len(urls)} مقال اجتهادات في خريطة الموقع")
    for url in urls:
        if max_pages and st["juris_pages"] >= max_pages:
            break
        st["juris_pages"] += 1
        if already_ingested(conn, url):
            st["seen"] += 1
            continue
        try:
            code, page_html, _ = _get(url, http_get=http_get_text)
        except RuntimeError as e:
            log.info(f"   ⚠️ {e}")
            continue
        if code != 200:
            continue
        atts = page_attachments(page_html, base)
        st["attachments"] += len(atts)
        texts = []
        for a in atts:
            time.sleep(POLITE_DELAY / 2)
            try:
                c2, raw, _ = _get(a, as_bytes=True, http_get=http_get_bytes)
            except RuntimeError as e:
                log.info(f"   ⚠️ {e}")
                continue
            if c2 != 200 or not raw:
                continue
            st["downloaded"] += 1
            texts.append(extract_text(raw))
        text = "\n\n".join(t for t in texts if t.strip())
        hits = [c for c in parse_text(text) if c.is_exportable()]
        if len(hits) < min_hits:
            st["skipped_low"] += 1
            continue
        st["candidates"] += 1
        if dry_run:
            st["citations"] += len(hits)
            log.info(f"   {url} — {len(hits)} استشهاداً (فحص جاف)")
            continue
        r = ingest_page(conn, url, page_html, source_site=SOURCE_SITE,
                        text_fn=lambda _h, _t=text: _t)
        st["pages_written"] += 1
        for k in ("citations", "written", "unsourced"):
            st[k] += r[k]
        log.info(f"   {SOURCE_SITE}: كُتب {r['written']} من {url}")
        time.sleep(POLITE_DELAY)
    return st
