# -*- coding: utf-8 -*-
"""precedent_blogger.py — اجتهادات من مدوّنات بلوغر عبر تغذية JSON الكاملة (ف٤، 2026-09-23).

bibliotdroit.com: 10,212 منشوراً (مغربي في معظمه)؛ 43 منشوراً يحمل اجتهادات
سورية بهوية = 1,569 استشهاداً (قِيس بالكامل). التغذية تُعطي المتن كاملاً بلا
جلب صفحة صفحة: `feeds/posts/default?alt=json&max-results=150&start-index=N`.

القاعدة: المنشور يُقبل فقط إن حوى «سوري» وأنتج المحلل العام ≥ MIN_HITS
استشهاداً سورياً بهوية؛ ثم يُكتب عبر `ingest_page` نفسه → pending.
"""
from __future__ import annotations

import json
import time

import requests

from config import USER_AGENT
from logging_setup import get_log
from precedent_parser import parse_text
from precedent_source import article_text, ingest_page, already_ingested

log = get_log("precedent_blogger")

PAGE = 150
MIN_HITS = 3
POLITE_DELAY = 0.5


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
    raise RuntimeError(f"blogger_feed_failed: {url} — {last}")


def harvest(conn, blog: str, http_get=None, dry_run: bool = False,
            max_posts: int | None = None, min_hits: int = MIN_HITS) -> dict:
    blog = blog.rstrip("/")
    if "://" not in blog:
        blog = "https://" + blog
    site = blog.split("://", 1)[1].replace("www.", "")
    st = {"site": site, "posts": 0, "candidates": 0, "pages_written": 0, "citations": 0,
          "written": 0, "unsourced": 0, "seen": 0}
    start = 1
    while True:
        if max_posts and st["posts"] >= max_posts:
            break
        url = f"{blog}/feeds/posts/default?alt=json&max-results={PAGE}&start-index={start}"
        try:
            code, body, _ = _get(url, http_get)
        except RuntimeError as e:
            log.info(f"   ⚠️ {e}")
            break
        if code != 200:
            break
        entries = json.loads(body).get("feed", {}).get("entry", [])
        if not entries:
            break
        for e in entries:
            st["posts"] += 1
            content = e.get("content", {}).get("$t", "")
            if "سوري" not in content:
                continue
            link = next((l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"), None)
            if not link:
                continue
            text = article_text(content)
            hits = [c for c in parse_text(text) if c.is_exportable()]
            if len(hits) < min_hits:
                continue
            st["candidates"] += 1
            if already_ingested(conn, link):
                st["seen"] += 1
                continue
            if dry_run:
                st["citations"] += len(hits)
                continue
            r = ingest_page(conn, link, content, source_site=site)
            st["pages_written"] += 1
            for k in ("citations", "written", "unsourced"):
                st[k] += r[k]
            log.info(f"   {site}: {e['title']['$t'][:50]} — كُتب {r['written']}")
        start += len(entries)
        time.sleep(POLITE_DELAY)
    return st
