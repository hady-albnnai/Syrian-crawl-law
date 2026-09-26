# -*- coding: utf-8 -*-
"""autopilot.py — الطيار الآلي: اكتشاف المصادر وتقييمها تلقائياً.

الوضع الآمن الافتراضي:
  توليد مرشحين ← تقييم مهذب ومفسَّر ← تسجيل النتيجة للمراجعة.
لا اعتماد للمصدر ولا بدء للزحف إلا بطلب صريح منفصل.

الوضع الاختياري الصريح:
  اعتماد تلقائي ببوابة أعلى من «موصى به» اليدوي ← بذر طابور الزحف.

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
    "اجتهادات محكمة النقض السورية قرار أساس",
    "اجتهاد سوري المبدأ القانوني المحكمة الإدارية العليا",
]

# أقصى عدد استعلامات مولَّدة من إشارات نصية بكل دورة — يمنع انفجار عدد
# طلبات البحث لو حوى المتن مئات الإشارات (وثيقة قانونية واحدة قد تشير
# لعشرات التعديلات التاريخية).
MAX_REFERENCE_QUERIES = 10
# حد أعلى لطلبات البحث في الدورة، مع حصة صغيرة لكل قناة كي لا تطغى فجوات
# التشريع على الاستعلامات العامة واجتهادات المحاكم.
MAX_SEARCH_QUERIES_PER_RUN = 12
MAX_MISSING_TARGET_QUERIES_PER_RUN = 4
MAX_REFERENCE_SEARCH_QUERIES_PER_RUN = 2
MAX_GAP_SEARCH_QUERIES_PER_RUN = 1


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

    الاستعلامات الافتراضية مزيج محدود: أعلى 4 فجوات معلومة، الاستعلامات
    العامة والقضائية، إشارتان نصيتان، وفجوة فرع واحدة (بحد أقصى 12 طلب بحث).
    إذا حجب مزوّد أو انتهت مهلته، يُعطَّل لباقي الدورة ويُجرَّب Bing إن توفر.
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
        from missing_targets import missing_target_queries
        if queries is not None:
            effective_queries = list(queries)
        else:
            # حصة B-1 تحافظ على أولوية الصكوك الناقصة، مع إبقاء الاستعلامات
            # العامة/القضائية في الدورة؛ لا تُرسل عشرات الطلبات دفعة واحدة.
            effective_queries = (
                missing_target_queries(conn, limit=MAX_MISSING_TARGET_QUERIES_PER_RUN)
                + list(DEFAULT_QUERIES)
                + reference_driven_queries(conn, limit=MAX_REFERENCE_SEARCH_QUERIES_PER_RUN)
                + gap_driven_queries(conn)[:MAX_GAP_SEARCH_QUERIES_PER_RUN]
            )
        effective_queries = list(dict.fromkeys(effective_queries))[:MAX_SEARCH_QUERIES_PER_RUN]

        # مزوّد البحث الذي يحجبنا أو ينتهي وقته يُعطَّل لباقي الدورة؛ لا نكرر
        # 202/403 أو انتظار 25 ثانية لكل استعلام. إن توفر Bing ينتقل إليه فوراً.
        disabled_providers = set()
        for query in effective_queries:
            for provider in providers:
                if provider.name in disabled_providers:
                    continue
                try:
                    for cand in provider.search(query, limit=6):
                        add(cand)
                    break  # مزود واحد كافٍ لكل استعلام
                except SearchUnavailable as exc:
                    disabled_providers.add(provider.name)
                    log.info(f"قناة {provider.name} أُوقفت لهذه الدورة: {exc}")
                except Exception as exc:  # عطل شبكة/مهلة — القناة تُتجاوز لهذه الدورة
                    disabled_providers.add(provider.name)
                    log.info(f"قناة {provider.name} أُوقفت بعد عطل: {exc}")

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
    """(ok, سبب) — بوابة محافظة؛ لا تُمرر الاجتهادات أو النوع المجهول آلياً."""
    if ev.verdict != "recommended":
        return False, f"الحكم {ev.verdict}"
    if ev.source_type not in {"legislation", "mixed"} or not ev.legal:
        return False, f"نوع المحتوى {ev.source_type} لا يجتاز الاعتماد الآلي"
    if ev.score < AUTO_APPROVE_MIN_SCORE:
        return False, (f"الدرجة {ev.score:.1f} دون حد الاعتماد التلقائي "
                       f"{AUTO_APPROVE_MIN_SCORE}")
    if ev.articles < AUTO_APPROVE_MIN_ARTICLES:
        return False, (f"المواد المستخرجة {ev.articles} دون الحد "
                       f"{AUTO_APPROVE_MIN_ARTICLES}")
    return True, (f"بنية قانونية + درجة {ev.score:.1f} + {ev.articles} مادة "
                  f"(محرك {ev.engine})")


def consider_auto_approve(conn, cand_url: str, ev) -> bool:
    """اعتماد اختياري للمرشح غير المحسوم؛ لا يتجاوز قراراً بشرياً سابقاً."""
    ok, why = auto_verdict(ev)
    if not ok:
        log.info(f"   ⏸ مقترح فقط ({why}) — يحتاج موافقة يدوية")
        return False
    row = conn.execute("SELECT status, decided_by FROM sources WHERE source_key = ?",
                       (_source_key(cand_url),)).fetchone()
    if row is None or row["status"] != "proposed" or row["decided_by"]:
        log.info("   ⏸ لم يُمسّ المصدر: له قرار سابق أو ليس مقترحاً")
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


def run_discovery(conn, auto_approve: bool = False, use_search: bool = True,
                  max_evaluate: int = 12) -> dict:
    """يولّد المرشحين ويقيّمهم ويسجل الأدلة؛ الوضع الافتراضي مقترحات فقط."""
    stats = {"seen": 0, "evaluated": 0, "new": 0, "approved": 0,
             "recommended": 0, "proposed": 0, "rejected": 0, "low_relevance": 0,
             "blocked": 0, "approved_list": [], "errors": []}
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
            ev = evaluate_candidate(cand.url, cand.title, cand.snippet)
        except Exception as exc:
            stats["errors"].append(f"{cand.url}: {exc}")
            log.info(f"   ❌ عطل تقييم: {exc}")
            continue
        source_id, created = register_candidate(conn, cand.url, cand.via, ev)
        if created:
            stats["new"] += 1
        if ev.verdict in ("rejected", "needs_review"):
            stats["low_relevance"] += 1
        if ev.verdict == "recommended":
            stats["recommended"] += 1
        if ev.verdict == "blocked":
            stats["blocked"] += 1  # يبقى مقترحاً؛ robots قد تتغير لاحقاً

        if ev.verdict == "recommended" and auto_approve \
                and consider_auto_approve(conn, cand.url, ev):
            stats["approved"] += 1
            stats["approved_list"].append(
                {"url": canonicalize_url(cand.url),
                 "title": ev.title or cand.url, "engine": ev.engine,
                 "score": ev.score, "source_score": ev.source_score,
                 "articles": ev.articles, "source_type": ev.source_type,
                 "via": cand.via})
            continue

        # الاعتماد الآلي اختياري فقط؛ أما الحكم المنخفض فيبقى نتيجة تقييم
        # على صف مقترح عندما يكون auto_approve=False.
        if auto_approve and ev.verdict == "rejected":
            row = conn.execute("SELECT status, decided_by FROM sources WHERE id = ?",
                               (source_id,)).fetchone()
            if row and row["status"] == "proposed" and not row["decided_by"]:
                decide_source(conn, _source_key(cand.url), False,
                              decided_by="auto")
                stats["rejected"] += 1
        row = conn.execute("SELECT status FROM sources WHERE id = ?",
                           (source_id,)).fetchone()
        if row and row["status"] == "proposed":
            stats["proposed"] += 1
        conn.commit()

    conn.commit()
    log.info(f"🏁 التقييم: رُئي {stats['seen']} | قُيّم {stats['evaluated']} | "
             f"جديد {stats['new']} | مقترح للمراجعة {stats['proposed']} | "
             f"موصى به {stats['recommended']} | منخفض الصلة {stats['low_relevance']} | "
             f"مرفوض آلياً {stats['rejected']} | محجوب robots {stats['blocked']}")
    return stats


def run_autopilot(pages: int = 20, use_search: bool = True,
                  auto_approve: bool = False, crawl: bool = False,
                  max_evaluate: int = 12, stop_event=None,
                  dry_run: bool = False) -> dict:
    """يكتشف ويقيّم ويسجل مصادر للمراجعة؛ لا اعتماد ولا زحف افتراضياً.

    يمكن استدعاء الاعتماد أو الزحف صراحةً بعد التغيير المتعمد للخيارات.
    """
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
        start_crawling(max_pages=pages, dry_run=dry_run,
                       stop_event=stop_event)
    return stats
