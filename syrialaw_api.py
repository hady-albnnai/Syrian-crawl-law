# -*- coding: utf-8 -*-
"""syrialaw_api.py — مصدر syria-law.com عبر واجهة ووردبريس REST (ف٤، 2026-09-22).

الاكتشاف (مُقاس فعلياً 2026-09-22):
- `wp-json/wp/v2/lawss` = 193 تصنيفاً، كل تصنيف = قانون كامل (مثل «بينات ـ
  المرسوم رقم 359 لعام 1947» بـ180 منشوراً).
- `wp-json/wp/v2/laws?lawss=<id>` = منشور لكل مادة (العنوان «مادة N من …»،
  المحتوى نص المادة) أو عنوان باب/فصل (بلا رقم مادة — يُحفظ كسطر هرمية).
- إجمالي `laws` 16,372 منشوراً + `splaws`/`splawss` (211 تصنيفاً) قوانين خاصة.
- الموقع حجب زحف HTML الكثيف ليلة 2026-09-17 ⇒ هنا طلب واحد لكل 100 مادة
  (≈2 طلب لكل قانون) مع مهلة أدب بين الطلبات.

المسار: نفس أنبوب HF (`to_import_html` → `crawler._handle_topic`) فتمرّ
الوثيقة بكل البوابات (استخراج، هوية، تكرار، حالة نفاذ). طبقة النطاق كما في
`config.OFFICIAL_DOMAIN_TIERS` (مجتمعية) — لا تتقدم على مصدر رسمي.
"""
from __future__ import annotations

import html as _html
import json
import re
import time

import requests

from config import USER_AGENT
from logging_setup import get_log
from urls import canonicalize_url

log = get_log("syrialaw_api")

BASE = "https://syria-law.com/wp-json/wp/v2/"
SECTION = "syria-law.com (واجهة REST — ف٤)"
POLITE_DELAY = 1.0
TAXONOMIES = {"laws": "lawss", "splaws": "splawss"}
_ART_RE = re.compile(r"(?:المادة|مادة)\s*\(?\s*(\d+)\s*\)?")


RETRIES = 4


def _get(url: str, http_get=None):
    """جلب مع إعادة محاولة متدرجة (الموقع بطيء أحياناً: مهلة قراءة 40 ث قُيست)."""
    if http_get:
        return http_get(url)
    last = None
    for i in range(RETRIES):
        try:
            r = requests.get(url, timeout=90, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"http {r.status_code}")
            return r.status_code, r.text, dict(r.headers)
        except requests.RequestException as e:  # مهلة/انقطاع — ننتظر ونعيد
            last = e
            log.info(f"   ⏳ إعادة محاولة {i + 1}/{RETRIES}: {e.__class__.__name__}")
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"syrialaw_fetch_failed: {url} — {last}")


def list_laws(post_type: str = "laws", http_get=None) -> list[dict]:
    """كل تصنيفات القوانين [{id,name,count,link}]."""
    tax = TAXONOMIES[post_type]
    out, page = [], 1
    while True:
        st, body, hdr = _get(f"{BASE}{tax}?per_page=100&page={page}&_fields=id,name,count,link", http_get)
        if st != 200:
            break
        rows = json.loads(body)
        out.extend({"id": r["id"], "name": _html.unescape(r["name"]).strip(),
                    "count": r["count"], "link": r["link"]} for r in rows)
        total_pages = int((hdr or {}).get("X-WP-TotalPages") or (hdr or {}).get("x-wp-totalpages") or 1)
        if page >= total_pages or not rows:
            break
        page += 1
        time.sleep(POLITE_DELAY)
    return out


def fetch_articles(term_id: int, post_type: str = "laws", http_get=None) -> list[dict]:
    """كل منشورات قانون واحد: [{num, title, text}] بترتيب رقم المادة."""
    tax = TAXONOMIES[post_type]
    rows, page = [], 1
    while True:
        st, body, hdr = _get(f"{BASE}{post_type}?{tax}={term_id}&per_page=100&page={page}&_fields=id,title,content", http_get)
        if st != 200:
            break
        chunk = json.loads(body)
        rows.extend(chunk)
        total_pages = int((hdr or {}).get("X-WP-TotalPages") or (hdr or {}).get("x-wp-totalpages") or 1)
        if page >= total_pages or not chunk:
            break
        page += 1
        time.sleep(POLITE_DELAY)
    out = []
    for r in rows:
        title = _html.unescape(re.sub(r"\s+", " ", r["title"]["rendered"])).strip()
        text = _html.unescape(re.sub(r"<[^>]+>", "\n", r["content"]["rendered"]))
        text = re.sub(r"\n{2,}", "\n", text).strip()
        m = _ART_RE.search(title)
        out.append({"num": int(m.group(1)) if m else None, "title": title, "text": text})
    out.sort(key=lambda a: (a["num"] is None, a["num"] or 0))
    return out


def to_import_html(law_name: str, articles: list[dict]) -> str:
    """HTML بنمط الأنبوب: سطر «المادة N» ثم نصها (بلا عناوين أبواب)."""
    paras = []
    for a in articles:
        if a["num"] is None:
            # عناوين الأبواب تأتي بلا ترتيب موثوق من الواجهة — تُهمل حتى لا
            # تلتصق بنص آخر مادة (قِيس: «الباب السابع» ذُيّل بالمادة 159).
            continue
        body = a["text"] or ""
        if not re.match(r"^\s*(المادة|مادة)\s*\(?\s*\d+", body):
            body = f"المادة {a['num']}\n{body}"
        paras.append("<p>" + body.replace("\n", "<br/>") + "</p>")
    return (f'<html><body><article><div class="entry-content"><h1>{law_name}</h1>\n'
            + "\n".join(paras) + "\n</div></article></body></html>")


def import_laws(conn, post_type: str = "laws", only_names: list[str] | None = None,
                dry_run: bool = False, http_get=None, limit: int | None = None) -> dict:
    """تبنٍّ مرحلي لكل قوانين الموقع عبر البوابات. يعيد أعداد المصير."""
    import crawl_queue as taskqueue
    import crawler
    from source_quality import domain_tier_for_url

    stats = {"laws": 0, "imported": 0, "alternate": 0, "skipped": 0,
             "needs_review": 0, "failed": 0, "empty": 0}
    terms = list_laws(post_type, http_get)
    if only_names:
        terms = [t for t in terms if any(n in t["name"] for n in only_names)]
    if limit:
        terms = terms[:limit]
    for t in terms:
        stats["laws"] += 1
        url = t["link"]
        done = conn.execute(
            "SELECT 1 FROM crawl_tasks WHERE url=? AND status='success'",
            (canonicalize_url(url),)).fetchone()
        if done and not dry_run:
            stats["skipped"] += 1  # استئناف: قانون حُفظ بدورة سابقة
            continue
        try:
            arts = fetch_articles(t["id"], post_type, http_get)
        except RuntimeError as e:  # فشل قانون واحد لا يوقف الدورة
            log.info(f"   ⚠️ {t['name'][:50]}: {e}")
            stats["failed"] += 1
            continue
        numbered = [a for a in arts if a["num"] is not None]
        log.info(f"• {t['name'][:60]} — {len(numbered)} مادة")
        if not numbered:
            stats["empty"] += 1
            continue
        key = canonicalize_url(url)
        taskqueue.enqueue(conn, url, SECTION, "topic")
        row = conn.execute("SELECT id FROM crawl_tasks WHERE url=?", (key,)).fetchone()
        task = {"id": row["id"], "url": url, "section": SECTION, "kind": "topic",
                "domain_tier": domain_tier_for_url(url)}
        cs = {"pages": 0, "docs": 0, "articles": 0, "skipped": 0, "failures": 0}
        if dry_run:
            cs["pages"] = 1
        crawler._handle_topic(conn, task, to_import_html(t["name"], arts), dry_run, cs)
        status = conn.execute("SELECT status FROM crawl_tasks WHERE id=?", (row["id"],)).fetchone()["status"]
        doc = conn.execute("SELECT status FROM documents WHERE doc_id=?", (crawler.make_doc_id(url),)).fetchone()
        if cs["failures"]:
            stats["failed"] += 1
        elif cs["skipped"]:
            stats["skipped"] += 1
        elif status == "needs_review":
            stats["needs_review"] += 1
        elif doc is not None and doc["status"] == "alternate_source":
            stats["alternate"] += 1
        else:
            stats["imported"] += 1
        time.sleep(POLITE_DELAY)
    conn.commit()
    return stats
