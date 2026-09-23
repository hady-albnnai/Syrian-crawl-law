# -*- coding: utf-8 -*-
"""precedent_wp.py — اجتهادات من أي موقع ووردبريس يعرض «العنوان = إسناد القرار،
المتن = المبدأ» عبر REST (ف٤، قِيس 2026-09-23 على syrian-arbitration.com).

مجلة التحكيم السورية: تصنيف 28 «اجتهادات المحاكم السورية» = 86 منشوراً؛ العنوان
مثل «غرفة المخاصمة ورد القضاة / محكمة النقض – القرار /68/ – أساس /88/ – تاريخ
2025/07/22» والمتن = مبدأ قصير ثم جملة «يمكنكم متابعة الوثيقة أدناه…» تُقصّ.

القاعدة نفسها: يُكتب فقط ما يملك هوية كاملة (محكمة + رقم + سنة/أساس) عبر
`precedent_source.upsert_citation` → pending لمراجعة المالك.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
from urllib.parse import urlparse

import requests

from config import USER_AGENT
from logging_setup import get_log
from precedent_parser import parse_citation, MIN_PRINCIPLE_TITLED
from precedent_source import upsert_citation, already_ingested

log = get_log("precedent_wp")

POLITE_DELAY = 1.0
PER_PAGE = 50
# مواقع معروفة: النطاق → (معرّف التصنيف، اسم العرض)
KNOWN_SITES = {
    "syrian-arbitration.com": (28, "مجلة التحكيم السورية"),
}
_BOILER_RE = re.compile(r"يمكنكم\s+متابعة\s+الوثيقة.*$", re.S)


def _get(url: str, http_get=None):
    if http_get:
        return http_get(url)
    last = None
    for i in range(4):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"http {r.status_code}")
            return r.status_code, r.text, dict(r.headers)
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"wp_precedents_fetch_failed: {url} — {last}")


def clean_principle(content_html: str) -> str:
    text = _html.unescape(re.sub(r"<[^>]+>", "\n", content_html or ""))
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = _BOILER_RE.sub("", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def classify(title: str, content_html: str):
    """يعيد (Citation|None, reason). reason ∈ ok|no_identity|short."""
    t = _html.unescape(title or "").replace("–", "-").replace("—", "-")
    principle = clean_principle(content_html)
    if len(principle) < MIN_PRINCIPLE_TITLED:
        return None, "short"
    c = parse_citation(t)
    c.principle_text = principle
    c.title_keywords = t
    if not c.identity_key():
        return None, "no_identity"
    return c, "ok"


def harvest(conn, site: str, category: int | None = None, http_get=None,
            max_pages: int | None = None, dry_run: bool = False) -> dict:
    domain = urlparse(site if "://" in site else f"https://{site}").netloc.lower().replace("www.", "")
    if category is None:
        category = KNOWN_SITES.get(domain, (None,))[0]
    base = f"https://{domain}/wp-json/wp/v2/posts"
    st = {"site": domain, "pages": 0, "posts": 0, "written": 0, "new_decisions": 0,
          "new_principles": 0, "no_identity": 0, "short": 0, "seen": 0}
    page = 1
    while True:
        if max_pages and st["pages"] >= max_pages:
            break
        cat = f"&categories={category}" if category else ""
        url = f"{base}?per_page={PER_PAGE}&page={page}{cat}&_fields=id,title,content,link"
        try:
            code, body, hdr = _get(url, http_get)
        except RuntimeError as e:
            log.info(f"   ⚠️ {e}")
            break
        if code != 200:
            break
        rows = json.loads(body)
        if not rows:
            break
        st["pages"] += 1
        for r in rows:
            st["posts"] += 1
            link = r.get("link") or f"https://{domain}/?p={r['id']}"
            if already_ingested(conn, link):
                st["seen"] += 1
                continue
            c, reason = classify(r["title"]["rendered"], r["content"]["rendered"])
            if c is None:
                st[reason] += 1
                continue
            if dry_run:
                st["written"] += 1
                continue
            res = upsert_citation(conn, c, link, None, domain)
            if res.get("skipped"):
                st["no_identity"] += 1
                continue
            st["written"] += 1
            st["new_decisions"] += int(res["new_decision"])
            st["new_principles"] += int(res["new_principle"])
        if not dry_run:
            conn.commit()
        log.info(f"   {domain} صفحة {page}: {len(rows)} منشور | كُتب {st['written']} | بلا هوية {st['no_identity']}")
        total_pages = int((hdr or {}).get("X-WP-TotalPages") or (hdr or {}).get("x-wp-totalpages") or page)
        if page >= total_pages:
            break
        page += 1
        time.sleep(POLITE_DELAY)
    return st
