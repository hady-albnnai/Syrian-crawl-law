# -*- coding: utf-8 -*-
"""
official_seed.py — بذّار المصادر الرسمية بنى ووردبريس (ف١).

بدل انتظار اكتشاف الروابط عبر تصفح الأقسام، يقرأ فهرس sitemap الخاص
بوردبريس (wp-sitemap.xml) ويستخرج روابط أنواع المحتوى القانوني المحددة
بconfig.MOJ_POST_TYPES (قرارات وتعاميم وزارة العدل). لا تُدرج أي صفحة
إلا إذا كان عنوانها ضمن مصدر approved؛ الاعتماد وإدراج هذه المهام مرحلتان
مستقلتان، والإدراج idempotent.

حدود الأدب: عدد صفحات sitemap لكل نوع محدود بconfig.MAX_SITEMAP_PAGES،
والبذر نفسه لا يجلب أي صفحة محتوى — الجلب يبقى حصراً عبر fetcher
بتأخيره وrobots واحترامه للبوابات.
"""
import re
from urllib.parse import urljoin

import requests

from config import (MAX_SITEMAP_PAGES, MOJ_BASE_URL, MOJ_POST_TYPES,
                    USER_AGENT)
from logging_setup import get_log

log = get_log("official_seed")

_SITEMAP_PAGE_RE = re.compile(r"wp-sitemap-posts-(\w+)-(\d+)\.xml")
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def _real_get(url: str):
    """جلب خفيف لملفات sitemap فقط — بترميز عربي سليم (نفس إصلاح
    fetcher: بلا charset بالترويسة يفترض requests اللاتيني فيفسد العربي)."""
    r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.status_code, r.text


def fetch_post_urls(base_url: str = MOJ_BASE_URL, post_types: dict = None,
                    http_get=None) -> list:
    """روابط أنواع المحتوى المطلوبة من فهرس sitemap — [(url, section)]."""
    http_get = http_get or _real_get
    post_types = post_types or MOJ_POST_TYPES

    st, index_xml = http_get(urljoin(base_url, "wp-sitemap.xml"))
    if st != 200:
        log.warning(f"فهرس sitemap غير متاح ({st}) — لا بذر")
        return []

    wanted = []
    for m in _SITEMAP_PAGE_RE.finditer(index_xml):
        ptype, page = m.group(1), int(m.group(2))
        if ptype in post_types and 1 <= page <= MAX_SITEMAP_PAGES:
            wanted.append((ptype, page))

    out = []
    for ptype, page in wanted:
        st, page_xml = http_get(
            urljoin(base_url, f"wp-sitemap-posts-{ptype}-{page}.xml"))
        if st != 200:
            log.warning(f"صفحة sitemap {ptype}-{page} غير متاحة ({st})")
            continue
        urls = _LOC_RE.findall(page_xml)
        log.info(f"sitemap {ptype}-{page}: {len(urls)} رابطاً")
        out.extend((u, post_types[ptype]) for u in urls)
    return out


def seed_wipo(conn, http_get=None, dry_run: bool = False) -> dict:
    """بذر قوانين ويبو ليكس — فهرس صفحة عضوية سوريا حياً + مثبتات config.

    الفهرس يُقرأ بكل بذر: صك مودع حديثاً يظهر تلقائياً. إن تعذّر الفهرس
    تعمل المثبتات وحدها (احتياط). الجلب هنا لصفحة الفهرس فقط — صفحات
    المحتوى تبقى حصراً للزحف عبر fetcher ببواباته وأدبه.
    """
    import crawl_queue as taskqueue
    import wipo_source
    from config import WIPO_INDEX_URL, WIPO_SEED_LAWS

    http_get = http_get or _real_get
    pairs = list(WIPO_SEED_LAWS)
    index_found = 0
    st, index_html = http_get(WIPO_INDEX_URL)
    if st == 200:
        urls = wipo_source.extract_index_links(index_html)
        index_found = len(urls)
        pairs.extend((u, "ويبو ليكس") for u in urls)
        log.info(f"فهرس ويبو (عضوية سوريا): {index_found} صكاً")
    else:
        log.warning(f"فهرس ويبو غير متاح ({st}) — المثبتات فقط")

    added = skipped = unapproved = 0
    for url, section in pairs:
        if dry_run:
            if taskqueue.approved_source_for_url(conn, url) is None:
                unapproved += 1
            else:
                log.info(f"[dry] {section} ← {url[:70]}")
            continue
        created, source_id = taskqueue.enqueue_approved_url(
            conn, url, section, "topic")
        if source_id is None:
            unapproved += 1
        elif created:
            added += 1
        else:
            skipped += 1
    stats = {"pins": len(WIPO_SEED_LAWS), "index_found": index_found,
             "added": added, "skipped": skipped, "unapproved": unapproved}
    log.info(f"بذر ويبو: فهرس {index_found} + مثبتات {len(WIPO_SEED_LAWS)} — "
            f"أُدرج {added}، موجود سابقاً {skipped}، بلا مصدر معتمد {unapproved}")
    return stats


def seed_moj(conn, http_get=None, post_types: dict = None,
             dry_run: bool = False) -> dict:
    """بذر روابط moj بالطابور كمهام topic — يعيد خلاصة الأعداد."""
    import crawl_queue as taskqueue

    pairs = fetch_post_urls(post_types=post_types, http_get=http_get)
    added = skipped = unapproved = 0
    for url, section in pairs:
        if dry_run:
            if taskqueue.approved_source_for_url(conn, url) is None:
                unapproved += 1
            else:
                log.info(f"[dry] {section} ← {url[:70]}")
            continue
        created, source_id = taskqueue.enqueue_approved_url(
            conn, url, section, "topic")
        if source_id is None:
            unapproved += 1
        elif created:
            added += 1
        else:
            skipped += 1
    stats = {"found": len(pairs), "added": added, "skipped": skipped,
             "unapproved": unapproved}
    log.info(f"بذر moj: عُثر على {stats['found']}، أُدرج {added}، "
             f"موجود سابقاً {skipped}، بلا مصدر معتمد {unapproved}")
    return stats


def seed_bunud(conn, http_get=None, dry_run: bool = False) -> dict:
    """B-2: بذر تشريعات «بنود» من خريطة الموقع (~1486 رابطاً).

    الرابط لا يحمل الهوية (slug إنجليزي) فلا تصفية قبل الجلب؛ التصفية
    بعده في الأنبوب: تصادم الهوية → dedup يُبقي الأكمل ويؤرشف الآخر.
    """
    import crawl_queue as taskqueue
    import bunud_source

    http_get = http_get or (lambda u: _real_get(u)[1])
    try:
        index_xml = http_get(bunud_source.SITEMAP_INDEX)
    except Exception as exc:
        log.warning(f"خريطة بنود غير متاحة: {exc}")
        return {"found": 0, "added": 0, "skipped": 0}
    urls = bunud_source.sitemap_law_urls(index_xml, http_get)
    added = skipped = unapproved = 0
    for url in urls:
        if dry_run:
            if taskqueue.approved_source_for_url(conn, url) is None:
                unapproved += 1
            continue
        created, source_id = taskqueue.enqueue_approved_url(
            conn, url, bunud_source.SECTION, "topic")
        if source_id is None:
            unapproved += 1
        elif created:
            added += 1
        else:
            skipped += 1
    stats = {"found": len(urls), "added": added, "skipped": skipped,
             "unapproved": unapproved}
    log.info(f"بذر بنود: خريطة {len(urls)} — أُدرج {added}، موجود سابقاً "
             f"{skipped}، بلا مصدر معتمد {unapproved}")
    return stats
