# -*- coding: utf-8 -*-
"""sitemap_seed.py — بذر طابور الزحف من sitemap موقع معتمد، بمسار محدد.

الحاجة: أرشيف التصنيف عند سانا (sana.sy/presidency/) يتوقف عند الصفحة 9 (ما بعدها 404)،
فلا يصل الزحف عبر الترقيم إلى مراسيم 2025 وما قبلها. خرائط الموقع (post-sitemapN.xml)
تعدّد كل المنشورات ومسار كل منها يحمل تصنيفه (/presidency/<id>/) فنبذر بالمسار وحده.

أدب الجلب: فهرس الخرائط ثم خرائطه بالتتابع، بفاصل Crawl-delay المنشور (robots) عبر
fetcher، وتُدرج الروابط فقط إن كان المصدر approved (crawl_queue.enqueue_approved_url).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests

import fetcher
from config import USER_AGENT
from logging_setup import get_log

log = get_log("sitemap_seed")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
MAX_SITEMAPS = 200


def _real_get(url: str):
    fetcher.is_allowed(url, record_log=False)      # يملأ Crawl-delay للمضيف
    fetcher.polite_sleep()
    fetcher.honor_crawl_delay(url)
    r = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.status_code, r.text


def collect_urls(base_url: str, path_prefix: str, http_get=None,
                 max_sitemaps: int = MAX_SITEMAPS) -> list:
    """روابط الخرائط التي يبدأ مسارها بـ path_prefix (مثل /presidency/) مع ترتيب الأحدث أولاً."""
    raw_get = http_get or _real_get

    def get(url):
        """أي عطل شبكة/ترميز في خريطة واحدة لا يُسقط البذر كله."""
        try:
            return raw_get(url)
        except Exception as exc:
            log.warning(f"SEEDMAP| fetch error {url.rsplit('/', 1)[-1]}: {type(exc).__name__}")
            return 0, ""
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    st, index_xml = get(urljoin(origin, "/sitemap_index.xml"))
    if st != 200:
        log.warning(f"SEEDMAP| index unavailable status={st} — nothing seeded")
        return []
    maps = _LOC_RE.findall(index_xml)[:max_sitemaps]
    host = urlparse(base_url).netloc
    seen, out = set(), []
    failed = 0
    for i, m in enumerate(maps, 1):
        st, xml = get(m)
        if st != 200:
            failed += 1
            log.warning(f"SEEDMAP| sitemap {i}/{len(maps)} unavailable status={st}")
            continue
        if i % 10 == 0 or i == len(maps):
            log.info(f"SEEDMAP| sitemap {i}/{len(maps)} urls_so_far={len(out)}")
        for loc in _LOC_RE.findall(xml):
            p = urlparse(loc)
            if p.netloc != host or not p.path.startswith(path_prefix):
                continue
            if p.path.rstrip("/") == path_prefix.rstrip("/"):   # صفحة التصنيف نفسها
                continue
            if loc not in seen:
                seen.add(loc)
                out.append(loc)
    # معرّفات ووردبريس تتزايد مع الزمن: الأحدث أولاً
    def _id(u):
        m = re.search(r"/(\d+)/?$", u)
        return int(m.group(1)) if m else 0
    out.sort(key=_id, reverse=True)
    log.info(f"SEEDMAP| collected sitemaps={len(maps)} failed={failed} urls={len(out)}")
    return out


def seed_from_sitemap(conn, base_url: str, path_prefix: str, section: str,
                      limit: int | None = None, dry_run: bool = False,
                      http_get=None) -> dict:
    import crawl_queue as taskqueue
    urls = collect_urls(base_url, path_prefix, http_get=http_get)
    if limit:
        urls = urls[:limit]
    added = skipped = unapproved = 0
    for url in urls:
        if dry_run:
            if taskqueue.approved_source_for_url(conn, url) is None:
                unapproved += 1
            continue
        created, source_id = taskqueue.enqueue_approved_url(conn, url, section, "topic")
        if source_id is None:
            unapproved += 1
        elif created:
            added += 1
        else:
            skipped += 1
    stats = {"found": len(urls), "added": added, "skipped": skipped, "unapproved": unapproved}
    log.info(f"SEEDMAP| found={stats['found']} added={added} existing={skipped} "
             f"unapproved={unapproved} dry={dry_run}")
    return stats
