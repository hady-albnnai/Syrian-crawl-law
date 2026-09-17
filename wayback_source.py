# -*- coding: utf-8 -*-
"""
wayback_source.py — زحف الأصول المؤرشفة عبر Wayback (ف٢، قرار «ج»).

المسار الثاني من القرار: المتبنّى من HF (طبقة 3) يقبع بنفس doc_id الذي
يحمله الرابط الأصلي (parliament.gov.sy / jus.moj.gov.sy — طبقة 1)، فأي
أصل يُستدرج بنجاح من الأرشيف يمر بميزان «استُبدلت بنسخة أفضل» فيرقّي
الصف في مكانه تلقائياً — بلا أي تدخل.

الوصفة (تُقاس حياً أول ما يعود أرشيف الإنترنت — كان مطفأ وقت البناء):
  ١. CDX: /cdx/search/cdx?url={الأصل}&fl=timestamp,statuscode
     &filter=statuscode:200&collapse=digest&output=json — كل اللقطات 200.
  ٢. أحدث لقطة: https://web.archive.org/web/{ts}id_/{الأصل}
     — لاحقة id_ تُرجع المحتوى الأصلي الخام بلا حقن شريط الأرشيف.
الأدب: robots + التأخير المهذب عبر fetcher لكل طلب (CDX واللقطات).
روابط PDF (صفوف jus.moj الفارغة) مؤجلة — تحتاج مسار PDF كامل.
"""
import json
from urllib.parse import quote

import requests

from config import USER_AGENT, WAYBACK_CDX_LIMIT
from logging_setup import get_log

log = get_log("wayback")

CDX_BASE = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_BASE = "https://web.archive.org/web/"
SECTION = "أرشيف مجلس الشعب (Wayback)"


def _real_get(url: str):
    """جلب بأدب الزحف الكامل: robots + تأخير fetcher المهذب — لكل من
    استعلام CDX وجلب اللقطة. بترميز عربي سليم (نمط official_seed)."""
    import fetcher

    if not fetcher.is_allowed(url):
        return None, ""
    fetcher.polite_sleep()
    r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.status_code, r.text


def cdx_snapshots(original_url: str, http_get=None,
                  limit: int = None) -> list:
    """[(timestamp, statuscode)] بتسلسل CDX (تصاعدي) — 200 فقط.

    http_get محقون للاختبارات المحلية (§8.8: لا اختبارات على مزود حي).
    """
    http_get = http_get or _real_get
    q = (f"{CDX_BASE}?url={quote(original_url)}&output=json"
         f"&fl=timestamp,statuscode&filter=statuscode:200"
         f"&collapse=digest&limit={limit or WAYBACK_CDX_LIMIT}")
    status, body = http_get(q)
    if status is None:
        return []          # robots — يعالجها المستدعي كحجب
    if status != 200:
        return []
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    if not rows or not isinstance(rows, list):
        return []
    return [(r[0], r[1]) for r in rows[1:] if len(r) >= 2]


def latest_good_snapshot(original_url: str, http_get=None) -> str:
    """طابع أحدث لقطة 200 — أو سلسلة فارغة إن لا أرشيف."""
    snaps = cdx_snapshots(original_url, http_get=http_get)
    if not snaps:
        return ""
    return max(ts for ts, _code in snaps)


def as_pipeline_result(original_url: str, http_get=None) -> dict:
    """أصل مؤرشف كنتيجة أنبوب: {ok, html, final_url=الرابط الأصلي}.

    final_url هو الأصل نفسه — لا رابط الأرشيف — حتى يكون doc_id مستقراً
    على الرابط الرسمي فتمشي آلية الترقية عند المتبنّى الموجود.
    الفشل يعيد {ok: False, error} بأكواد صادقة.
    """
    http_get = http_get or _real_get
    q = (f"{CDX_BASE}?url={quote(original_url)}&output=json"
         f"&fl=timestamp,statuscode&filter=statuscode:200"
         f"&collapse=digest&limit={WAYBACK_CDX_LIMIT}")
    status, body = http_get(q)
    if status is None:
        return {"ok": False, "error": "wayback_blocked_robots"}
    if status != 200:
        return {"ok": False, "error": f"wayback_cdx_{status}"}
    try:
        rows = json.loads(body)
        snaps = [r[0] for r in rows[1:]] if rows else []
    except (ValueError, TypeError, IndexError):
        snaps = []
    if not snaps:
        return {"ok": False, "error": "wayback_no_snapshot"}
    ts = max(snaps)

    snap_url = f"{SNAPSHOT_BASE}{ts}id_/{original_url}"
    status, html = http_get(snap_url)
    if status is None:
        return {"ok": False, "error": "wayback_blocked_robots"}
    if status != 200 or not html or len(html) < 500:
        return {"ok": False, "error": f"wayback_fetch_{status}"}
    return {"ok": True, "html": html, "final_url": original_url,
            "status": 200, "encoding": "utf-8"}
