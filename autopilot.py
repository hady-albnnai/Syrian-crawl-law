# -*- coding: utf-8 -*-
"""autopilot.py — الطيار الآلي: الزاحف يلاقي مصادره لحالو ويتعامل معها.

حلقة كاملة بلا إدخال يدوي:
  توليد مرشحين ← تقييم مهذب (robots + استخراج v4 + درجة قانونية)
  ← اعتماد تلقائي ببوابة أعلى من «موصى به» اليدوي ← بذر طابور الزحف.

قنوات التوليد (كلها آلية):
  1) دليل البذور المرفق (SEED_SOURCES).
  2) بحث: DuckDuckGo بلا مفتاح، وBing بمفتاح إن وُجد (الصد يُعالج صراحة).
  3) تنقيب المتن المخزون: الروابط الخارجية داخل لقطات data/snapshots —
     المتن يقود إلى مصادره المجاورة («يلقّى مصادره لحالو» عملياً).
  4) خرائط المواقع: robots.txt (Sitemap:) ثم /sitemap.xml للمصادر المعتمدة.

بوابة الاعتماد التلقائي (auto_verdict) — أعلى من SOURCE_MIN_SCORE اليدوي:
  حكم recommended + درجة ≥ AUTO_APPROVE_MIN_SCORE + مواد مستخرجة فعلية
  ≥ AUTO_APPROVE_MIN_ARTICLES. كل قرار يُسجل في sources بـ decided_by='auto'
  للتدقيق، ولا يزحف شيء قبل ذلك.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import crawl_queue as taskqueue
import law_identity
from config import BASE_URL
from crawler import SNAPSHOT_DIR
from discovery import (Candidate, DuckDuckGoHtmlProvider, SearchUnavailable,
                       _source_key, approved_sources, decide_source,
                       evaluate_candidate, register_candidate,
                       seed_candidates)
from engines import is_legal_anchor
from fetcher import fetch
from logging_setup import get_log
from urls import canonicalize_url

log = get_log("autopilot")

# بوابة الاعتماد التلقائي — أعلى من «موصى به» اليدوي (55) لأن القرار آلي.
AUTO_APPROVE_MIN_SCORE = 70.0
AUTO_APPROVE_MIN_ARTICLES = 3

# مضيفون لا يُقترحون مصادرَ تشريعية أبداً (شبكات/اختصارات روابط).
_SKIP_HOSTS = {
    "facebook.com", "twitter.com", "x.com", "youtube.com", "instagram.com",
    "telegram.org", "t.me", "wa.me", "whatsapp.com", "google.com", "goo.gl",
    "blogspot.com", "wikipedia.org", "archive.org", "linkedin.com",
}

DEFAULT_QUERIES = [
    "القانون المدني السوري نص كامل",
    "قانون العقوبات السوري مواد",
    "مرسوم تشريعي سوري كامل",
]

# أقصى عدد استعلامات مولَّدة من إشارات نصية بكل دورة — يمنع انفجار عدد
# طلبات البحث لو حوى المتن مئات الإشارات (وثيقة قانونية واحدة قد تشير
# لعشرات التعديلات التاريخية).
MAX_REFERENCE_QUERIES = 10


# ═══════════════════ القطعة الثانية: إشارات نصية → استعلامات بحث ═══════════════════

def reference_driven_queries(conn, limit: int = MAX_REFERENCE_QUERIES) -> list:
    """يستخرج إشارات القوانين المذكورة **نصياً** (لا كروابط) داخل متن كل
    وثيقة نشطة محفوظة فعلاً، ويولّد استعلام بحث لكل إشارة **غير موجودة
    أصلاً** بالقاعدة (بمطابقة identity_key) — القطعة الثانية من خطة
    الاكتشاف الذاتي (DESIGN-SELF-DISCOVERY.md §3).

    فحص §3.4: لا بحث عن إشارة موجودة أصلاً بالمتن — توفير موارد شبكة.
    """
    known_keys = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT identity_key FROM documents "
            "WHERE identity_key IS NOT NULL").fetchall()
    }
    rows = conn.execute(
        "SELECT clean_content FROM documents WHERE status = 'active' "
        "AND clean_content IS NOT NULL").fetchall()

    queries, seen_keys = [], set()
    for row in rows:
        for ref in law_identity.extract_law_references(row[0]):
            key = ref["identity_key"]
            if key in known_keys or key in seen_keys:
                continue
            seen_keys.add(key)
            queries.append(law_identity.reference_to_search_query(ref))
            if len(queries) >= limit:
                return queries
    return queries


# ═══════════════════ المضيفون المعروفون (لا تُقترح مرة أخرى) ═══════════════════

def _registrable(netloc: str) -> str:
    """أقرب تقدير للنطاق المسجَّل: آخر عنوانين (بلا www)."""
    parts = (netloc or "").lower().removeprefix("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (netloc or "").lower()


def known_registrables(conn) -> set:
    """نطاقات المتن الحالي + المصادر المسجلة + المصدر الأساسي."""
    hosts = {urlparse(BASE_URL).netloc}
    try:
        rows = conn.execute("SELECT source_url FROM documents").fetchall()
        hosts |= {urlparse(r["source_url"] or "").netloc for r in rows}
        rows = conn.execute("SELECT base_url FROM sources").fetchall()
        hosts |= {urlparse(r["base_url"] or "").netloc for r in rows}
    except Exception:
        pass  # جداول غير موجودة بعد — المجموعة الأساسية تكفي
    hosts.discard("")
    regs = {_registrable(h) for h in hosts}
    regs |= set(_SKIP_HOSTS)
    return {r for r in regs if r}


# ═══════════════════ القناة 3: تنقيب المتن المخزون ═══════════════════

def mine_corpus_links(conn, snapshot_dir: Path = None, max_files: int = 60,
                      limit: int = 12) -> list:
    """روابط خارجية بإشارات قانونية من لقطات HTML المخزنة — نقية بقدر الإمكان:
    لا شبكة هنا، فقط قراءة اللقطات. تُقيَّم لاحقاً كأي مرشح."""
    snapshot_dir = Path(snapshot_dir) if snapshot_dir else SNAPSHOT_DIR
    known = known_registrables(conn)
    scores = {}
    files = sorted(snapshot_dir.glob("*.html"))[:max_files] \
        if snapshot_dir.exists() else []
    for path in files:
        try:
            soup = BeautifulSoup(path.read_text(encoding="utf-8",
                                                errors="ignore"), "lxml")
        except Exception:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith(("http://", "https://")):
                continue
            reg = _registrable(urlparse(href).netloc)
            if not reg or reg in known:
                continue
            text = a.get_text(" ", strip=True)
            score = 2 if is_legal_anchor(text, href) else 0
            if score == 0:
                continue
            key = canonicalize_url(href)
            prev = scores.get(key)
            if prev is None or score > prev[0]:
                scores[key] = (score, href, text[:80])
    ranked = sorted(scores.values(), key=lambda t: -t[0])[:limit]
    return [Candidate(url=url, title=title, via="corpus")
            for _score, url, title in ranked]


# ═══════════════════ القناة 4: خرائط المواقع ═══════════════════

_LEGAL_URL_RE = re.compile(
    r"law|qanoon|qanun|marsom|decree|legal|tashri|قانون|مرسوم", re.IGNORECASE)


def sitemap_candidates(base_url: str, limit: int = 15) -> list:
    """Sitemap: من robots.txt ثم /sitemap.xml — روابط بنمط تشريعي فقط."""
    out = []
    maps = []
    robots = fetch(base_url.rstrip("/") + "/robots.txt")
    if robots.get("ok"):
        for line in robots["html"].splitlines():
            if line.lower().startswith("sitemap:"):
                maps.append(line.split(":", 1)[1].strip())
    if not maps:
        maps = [base_url.rstrip("/") + "/sitemap.xml"]
    for sm in maps[:2]:
        result = fetch(sm)
        if not result.get("ok"):
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", result["html"]):
            if _LEGAL_URL_RE.search(loc):
                out.append(Candidate(url=loc.strip(), via="sitemap"))
            if len(out) >= limit:
                return out
    return out


# ═══════════════════ توليد المرشحين (القنوات مجتمعة) ═══════════════════

def generate_candidates(conn, use_search: bool = True,
                        queries: list = None) -> list:
    """مرشحون من كل القنوات — مُلغى تكرارهم، وبلا نطاقات معروفة/مستثناة.

    الاستعلامات المستخدمة عند queries=None (السلوك الافتراضي): الثلاثة
    الثابتة (DEFAULT_QUERIES) + استعلامات مولَّدة من إشارات نصية داخل
    المتن المحفوظ فعلاً (reference_driven_queries, §3) + استعلامات موجَّهة
    للفروع الناقصة التغطية فعلياً (gap_analysis.gap_driven_queries, §7)
    — لا تحلّ محل بعضها، تُضاف معاً (اتساع الاستعلامات مطلوب صراحة).
    """
    known = known_registrables(conn)
    cands, seen = [], set()

    def add(cand: Candidate):
        if not cand.url.startswith(("http://", "https://")):
            return
        if _registrable(urlparse(cand.url).netloc) in known:
            return
        key = canonicalize_url(cand.url)
        if key in seen:
            return
        seen.add(key)
        cands.append(cand)

    for cand in seed_candidates():
        add(cand)

    if use_search:
        providers = [DuckDuckGoHtmlProvider()]
        try:
            from discovery import BingApiProvider
            providers.append(BingApiProvider())
        except SearchUnavailable:
            pass  # بلا مفتاح — DDG وحده
        from gap_analysis import gap_driven_queries
        effective_queries = list(queries) if queries is not None else (
            list(DEFAULT_QUERIES) + reference_driven_queries(conn)
            + gap_driven_queries(conn))
        for query in effective_queries:
            for provider in providers:
                try:
                    for cand in provider.search(query, limit=6):
                        add(cand)
                    break  # مزود واحد كافٍ لكل استعلام
                except SearchUnavailable as exc:
                    log.info(f"قناة {provider.name} غير متاحة: {exc}")
                except Exception as exc:  # عطل شبكة عابر — القناة تُتجاوز
                    log.info(f"قناة {provider.name} تعطلت: {exc}")

    for cand in mine_corpus_links(conn):
        add(cand)

    for src in approved_sources(conn):
        try:
            for cand in sitemap_candidates(src["base_url"]):
                add(cand)
        except Exception as exc:
            log.info(f"خريطة موقع {src['base_url']} تعذرت: {exc}")

    return cands


# ═══════════════════ بوابة الاعتماد التلقائي ═══════════════════

def auto_verdict(ev) -> tuple:
    """(ok, سبب) — أعلى من «موصى به» اليدوي لأن القرار بلا تدخل بشري."""
    if ev.verdict != "recommended":
        return False, f"الحكم {ev.verdict}"
    if ev.score < AUTO_APPROVE_MIN_SCORE:
        return False, (f"الدرجة {ev.score:.1f} دون حد الاعتماد التلقائي "
                       f"{AUTO_APPROVE_MIN_SCORE}")
    if ev.articles < AUTO_APPROVE_MIN_ARTICLES:
        return False, (f"المواد المستخرجة {ev.articles} دون الحد "
                       f"{AUTO_APPROVE_MIN_ARTICLES}")
    return True, (f"بنية قانونية + درجة {ev.score:.1f} + {ev.articles} مادة "
                  f"(محرك {ev.engine})")


def consider_auto_approve(conn, cand_url: str, ev) -> bool:
    """يعتمد ويبذر الطابور إن اجتاز البوابة — يعيد هل اعتُمد."""
    ok, why = auto_verdict(ev)
    if not ok:
        log.info(f"   ⏸ مقترح فقط ({why}) — يحتاج موافقة يدوية")
        return False
    decide_source(conn, _source_key(cand_url), True, decided_by="auto")
    taskqueue.enqueue(conn, cand_url, ev.title or cand_url, "section")
    log.info(f"   🤖 اعتُمد تلقائياً وبُذر في الطابور — {why}")
    return True


# ═══════════════════ الحلقة الكاملة ═══════════════════

def bootstrap_primary_source(conn):
    """يسجل المنتدى الأساسي مصدراً معتمداً (مرة) — تُدار كل المصادر بجدول واحد."""
    key = _source_key(BASE_URL)
    if conn.execute("SELECT 1 FROM sources WHERE source_key = ?",
                    (key,)).fetchone():
        return False
    from datetime import datetime
    conn.execute('''
        INSERT INTO sources (source_key, base_url, name, engine, credibility,
                             status, discovered_via, discovered_at,
                             decided_at, decided_by)
        VALUES (?, ?, ?, 'phpbb', 0.9, 'approved', 'seed-primary', ?, ?, 'user')
    ''', (key, canonicalize_url(BASE_URL), "مكتبة القانون السوري (منتدى)",
          datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    return True


def run_discovery(conn, auto_approve: bool = True, use_search: bool = True,
                  max_evaluate: int = 12) -> dict:
    """يولّد ← يقيّم ← يسجل ← (يعتمد تلقائياً + يبذر) — يعيد إحصاءات التدقيق."""
    stats = {"seen": 0, "evaluated": 0, "new": 0, "approved": 0,
             "rejected": 0, "blocked": 0, "approved_list": [], "errors": []}
    bootstrap_primary_source(conn)

    candidates = generate_candidates(conn, use_search=use_search)
    log.info(f"🔎 {len(candidates)} مرشحاً جديداً من القنوات الآلية")

    for cand in candidates:
        stats["seen"] += 1
        if stats["evaluated"] >= max_evaluate:
            continue
        stats["evaluated"] += 1
        log.info(f"[{stats['evaluated']}/{max_evaluate}] تقييم: "
                 f"{cand.url[:80]} (عبر: {cand.via})")
        try:
            ev = evaluate_candidate(cand.url)
        except Exception as exc:
            stats["errors"].append(f"{cand.url}: {exc}")
            log.info(f"   ❌ عطل تقييم: {exc}")
            continue
        _id, created = register_candidate(conn, cand.url, cand.via, ev)
        if created:
            stats["new"] += 1
        if ev.verdict == "blocked":
            stats["blocked"] += 1  # يبقى proposed — robots قد تتغير لاحقاً
        if ev.verdict == "recommended":
            if auto_approve and consider_auto_approve(conn, cand.url, ev):
                stats["approved"] += 1
                stats["approved_list"].append(
                    {"url": canonicalize_url(cand.url),
                     "title": ev.title or cand.url, "engine": ev.engine,
                     "score": ev.score, "articles": ev.articles,
                     "via": cand.via})
                continue
        if ev.verdict != "blocked":
            stats["rejected"] += 1
        if ev.verdict == "rejected":
            # الحكم يُسجل في صف المصدر نفسه (لا في الإحصاء فقط) — للتدقيق.
            decide_source(conn, _source_key(cand.url), False,
                          decided_by="auto")
        conn.commit()

    conn.commit()
    log.info(f"🏁 الطيار: رُئي {stats['seen']} | قُيّم {stats['evaluated']} | "
             f"جديد {stats['new']} | اعتُمد {stats['approved']} | "
             f"مقترح/مرفوض {stats['rejected']} | محجوب {stats['blocked']}")
    return stats


def run_autopilot(pages: int = 20, use_search: bool = True,
                  auto_approve: bool = True, crawl: bool = True,
                  max_evaluate: int = 12) -> dict:
    """اكتشاف ذاتي كامل ثم زحف المعتمد — نقطة الدخول للأمر والواجهة."""
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()
    try:
        stats = run_discovery(conn, auto_approve=auto_approve,
                              use_search=use_search, max_evaluate=max_evaluate)
    finally:
        conn.close()
    if crawl and pages > 0:
        from crawler import start_crawling
        start_crawling(max_pages=pages)
    return stats
