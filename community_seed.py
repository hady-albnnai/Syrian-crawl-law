# -*- coding: utf-8 -*-
"""
community_seed.py — بذّار الطبقة المجتمعية (ف٢-ج من ميثاق التوسعة).

syria-law.com: ووردبريس/Yoast بنمط moj.gov.sy نفسه (قِيس ف٢-ج 2026-09-16)
— فهرس sitemap_index.xml يعرض خرائط أنواع المحتوى. نقبل خرائط القوانين
حصراً (laws/splaws)؛ خرائط موسوعة الاجتهادات (ijtihadat — صفحات موسوعية
قصيرة قِيست 1.5k حرف أغلبها قوائم تنقّل) تُستبعد أدباً: 65 ألف جلب
نعرف سلفاً أن بوابات الجودة سترفض أغلبها — لا نحمّل الموقع ما سيُرفض.

الإسناد: الطبقة الافتراضية 4 (مصدر مجتمعي) — خلف كل مصدر رسمي بآلية
dedup: إن وُجد نص رسمي لنفس الهوية يفوز ويصير نسخة المجتمع «بديلة
موثقة»؛ وإن انفرد المجتمع بقانون فهو مكسب لا يُعوَّض.
"""
import re
from urllib.parse import urljoin

import requests

from config import SYRIA_LAW_BASE_URL, SYRIA_LAW_MAX_SITEMAPS, USER_AGENT
from logging_setup import get_log

log = get_log("community_seed")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_SITEMAP_NAME_RE = re.compile(r"/(laws|splaws)-sitemap\d+\.xml$")
_LAW_PAGE_RE = re.compile(r"/(laws|splaws)/[^/]+")
# مقتطفات أحادية بعنوان «(ال)مادة-… من قانون…» — قِيس زحف ف٢-ج: 57٪
# من الخرائط (12,229 من 21,419: مادة- 10,629 + المادة- 1,600) وكلها
# 1-2 مادة ترفضها بوابة الجودة.
# تُرشَّح من البذر ذاته أدباً: لا نحمّل الموقع ما نعرف أنه سيُرفض.
_EXCERPT_SLUG_RE = re.compile(r"^(?:ال)?مادة-")
SECTION = "قوانين سوريا (syria-law)"


def _is_excerpt_page(url: str) -> bool:
    """صفحة مقتطف أحادي؟ (slug يبدأ ب«مادة-» — مقيس بالزحف الحي)."""
    from urllib.parse import unquote
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return bool(_EXCERPT_SLUG_RE.match(unquote(slug)))


def _real_get(url: str):
    """جلب خفيف لملفات sitemap فقط — بترميز عربي سليم (نمط official_seed)."""
    r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.status_code, r.text


def fetch_law_urls(base_url: str = SYRIA_LAW_BASE_URL,
                   max_sitemaps: int = None, http_get=None) -> list:
    """روابط صفحات القوانين من خرائط laws/splaws — [(url, section)].

    الأدب: تأخير fetcher المهذب بين ملفات sitemap بالوضع الحي حصراً
    (الاختبارات تحقن جلبها فلا تنتظر).
    """
    if http_get is None:
        import fetcher
    max_sitemaps = max_sitemaps or SYRIA_LAW_MAX_SITEMAPS

    st, index_xml = (http_get or _real_get)(
        urljoin(base_url, "sitemap_index.xml"))
    if st != 200:
        log.warning(f"فهرس sitemap غير متاح ({st}) — لا بذر")
        return []
    maps = [u for u in _LOC_RE.findall(index_xml)
            if _SITEMAP_NAME_RE.search(u)][:max_sitemaps]

    out = []
    for m in maps:
        if http_get is None:
            fetcher.polite_sleep()
        st, xml = (http_get or _real_get)(m)
        if st != 200:
            log.warning(f"خريطة {m.rsplit('/', 1)[-1]} غير متاحة ({st})")
            continue
        out.extend((u, SECTION) for u in _LOC_RE.findall(xml)
                   if _LAW_PAGE_RE.search(u) and not _is_excerpt_page(u))
    log.info(f"خرائط القوانين: {len(maps)} خريطة ← {len(out)} رابطاً")
    return out


def seed_syria_law(conn, http_get=None, dry_run: bool = False) -> dict:
    """بذر روابط قوانين syria-law بالطابور كمهام topic — idempotent."""
    import crawl_queue as taskqueue

    pairs = fetch_law_urls(http_get=http_get)
    added = skipped = 0
    for url, section in pairs:
        if dry_run:
            continue
        if taskqueue.enqueue(conn, url, section, "topic"):
            added += 1
        else:
            skipped += 1
    stats = {"found": len(pairs), "added": added, "skipped": skipped}
    log.info(f"بذر syria-law: عُثر على {stats['found']}، أُضيف {added}، "
             f"موجود سابقاً {skipped}")
    return stats
