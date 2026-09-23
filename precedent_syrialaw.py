# -*- coding: utf-8 -*-
"""precedent_syrialaw.py — اجتهادات syria-law.com عبر REST (ف٤، قِيس 2026-09-23).

`wp-json/wp/v2/ijtihadat` = 65,535 منشوراً؛ كل منشور = مبدأ واحد ثم سطر إسناد
بين قوسين في آخره. المجموعات (من عيّنة 400): الموسوعة القانونية لأنس كيلاني
(عقوبات — سورية ومصر ولبنان)، موسوعة جرائم الأمن الاقتصادي (سنان)، قانون
الإيجارات (شفيق طعمة)، قانون البينات بين الفقه والاجتهاد (عطري)، «الاجتهادات
الخاصة». ~42% من المنشورات تحمل إسناداً مقروءاً.

القاعدة: يُكتب فقط ما يملك هوية سورية كاملة (محكمة + رقم قرار + سنة/أساس)
عبر `precedent_source.upsert_citation` نفسه — قرارات مصر ولبنان تُستبعد
(لا هوية سورية) وتُعدّ «أجنبي». كل شيء يدخل pending لمراجعة المالك
(`precedents-approve`) كما في مسار mohamah.
"""
from __future__ import annotations

import html as _html
import json
import re
import time

import requests

from config import USER_AGENT
from logging_setup import get_log
from precedent_parser import parse_citation, MIN_PRINCIPLE
from precedent_source import upsert_citation, already_ingested

log = get_log("precedent_syrialaw")

BASE = "https://syria-law.com/wp-json/wp/v2/ijtihadat"
SOURCE_SITE = "syria-law.com"
POLITE_DELAY = 1.0
PER_PAGE = 100
_TAIL_REF_RE = re.compile(r"\(([^()]{10,300})\)\s*$")
_FOREIGN_RE = re.compile(r"^\s*(?:مصر|لبنان|فرنسا|الاردن|الأردن|العراق|تونس|المغرب|الجزائر|الكويت)\b")


def _get(url: str, http_get=None):
    if http_get:
        return http_get(url)
    last = None
    for i in range(4):
        try:
            r = requests.get(url, timeout=90, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"http {r.status_code}")
            return r.status_code, r.text, dict(r.headers)
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"syrialaw_ijtihadat_fetch_failed: {url} — {last}")


def split_post(title: str, content_html: str) -> dict:
    """{'collection','principle','ref'} — المبدأ = ما قبل قوس الإسناد الأخير."""
    text = _html.unescape(re.sub(r"<[^>]+>", "\n", content_html or ""))
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    m = _TAIL_REF_RE.search(text)
    ref = m.group(1).strip() if m else None
    principle = text[: m.start()].strip() if m else text
    collection = re.sub(r"\s+\d+\s*$", "", _html.unescape(title or "")).strip()
    return {"collection": collection, "principle": principle, "ref": ref}


def classify(post: dict):
    """يعيد (Citation|None, reason). reason ∈ ok|no_ref|foreign|no_identity|short."""
    if not post["ref"]:
        return None, "no_ref"
    if _FOREIGN_RE.match(post["ref"]):
        return None, "foreign"
    if len(post["principle"]) < MIN_PRINCIPLE:
        return None, "short"
    c = parse_citation("(" + post["ref"] + ")")
    c.principle_text = post["principle"]
    c.title_keywords = post["collection"] or None
    if not c.identity_key():
        return None, "no_identity"
    return c, "ok"


def harvest(conn, http_get=None, start_page: int = 1, max_pages: int | None = None,
            dry_run: bool = False, stop_when_seen: bool = True) -> dict:
    """يمرّ على صفحات REST (100 منشور/صفحة). يتوقف عند صفحة كل روابطها مُدخلة
    سابقاً (استئناف رخيص) إلا إذا stop_when_seen=False."""
    st = {"pages": 0, "posts": 0, "written": 0, "new_decisions": 0, "new_principles": 0,
          "no_ref": 0, "foreign": 0, "no_identity": 0, "short": 0, "seen": 0, "last_page": start_page}
    page = start_page
    while True:
        if max_pages and st["pages"] >= max_pages:
            break
        url = f"{BASE}?per_page={PER_PAGE}&page={page}&_fields=id,title,content,link"
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
        st["last_page"] = page
        page_seen = 0
        for r in rows:
            st["posts"] += 1
            link = r.get("link") or f"https://syria-law.com/?p={r['id']}"
            if already_ingested(conn, link):
                st["seen"] += 1
                page_seen += 1
                continue
            post = split_post(r["title"]["rendered"], r["content"]["rendered"])
            c, reason = classify(post)
            if c is None:
                st[reason] += 1
                continue
            if dry_run:
                st["written"] += 1
                continue
            res = upsert_citation(conn, c, link, None, SOURCE_SITE)
            if res.get("skipped"):
                st["no_identity"] += 1
                continue
            st["written"] += 1
            st["new_decisions"] += int(res["new_decision"])
            st["new_principles"] += int(res["new_principle"])
        if not dry_run:
            conn.commit()
        log.info(f"   صفحة {page}: {len(rows)} منشور | كُتب {st['written']} | أجنبي {st['foreign']} | بلا إسناد {st['no_ref']}")
        total_pages = int((hdr or {}).get("X-WP-TotalPages") or (hdr or {}).get("x-wp-totalpages") or page)
        if stop_when_seen and page_seen == len(rows) and page > start_page:
            break
        if page >= total_pages:
            break
        page += 1
        time.sleep(POLITE_DELAY)
    return st
