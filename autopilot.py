# -*- coding: utf-8 -*-
"""autopilot.py — تقييم مرشحي المصادر مع فصل صريح للمراحل.

المسار الحالي: توليد/تقييم مرشحين مهذب (robots + استخراج + درجة) ثم تسجيل
التقييم في sources بحالة proposed. لا اعتماد أو queue أو جلب للوثائق
ينشأ ضمناً من مرحلة أخرى. الاعتماد الآلي متوقف افتراضياً؛ حتى allowlist
المضيفين فارغة، ولا تُملأ إلا بعد معايرة سورية مستقلة.

قنوات التوليد:
  1) دليل البذور: مرشح seed لا whitelist.
  2) بحث خارجي عند اختيار search_via صراحةً؛ لا مزود افتراضياً.
  3) تنقيب المتن المخزون (محلي).
  4) خرائط المواقع للمصادر المعتمدة.
  5) التتبع بين المصادر (snowball): الروابط القانونية الخارجية في صفحات
     مصادرنا المعتمدة — اكتشاف مستقل بلا محرك بحث.

إدراج المصدر المعتمد في الطابور له أمر منفصل (`queue-approved`)، وجلب
صفحات الطابور له أمر/مرحلة crawl منفصلة.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

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
# لا اعتماد آلي افتراضياً: لا تُضاف نطاقات إلى هذه المجموعة إلا بعد
# قياسها على مجموعة مصادر سورية ذهبية ومراجعة الاختصاص/الدور/الحقوق.
AUTO_APPROVE_TRUSTED_HOSTS = frozenset()

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

_COMPOUND_PUBLIC_SUFFIXES = {
    # قائمة محافظة للنطاقات متعددة المستويات الشائعة؛ أهمها gov.sy حيث
    # إن الاقتصار على آخر عنوانين يدمج moj.gov.sy وparliament.gov.sy خطأً.
    "gov.sy", "edu.sy", "com.sy", "org.sy", "net.sy", "mil.sy",
    "gov.jo", "edu.jo", "com.jo", "gov.lb", "edu.lb", "com.lb",
    "gov.iq", "edu.iq", "com.iq", "gov.eg", "edu.eg", "com.eg",
    "gov.sa", "edu.sa", "com.sa", "gov.ae", "edu.ae", "com.ae",
    "gov.kw", "edu.kw", "com.kw", "gov.qa", "edu.qa", "com.qa",
    "gov.bh", "edu.bh", "com.bh", "gov.om", "edu.om", "com.om",
    "gov.ma", "edu.ma", "com.ma", "gov.tn", "edu.tn", "com.tn",
    "gov.dz", "edu.dz", "com.dz", "gov.ye", "edu.ye", "com.ye",
    "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "org.au",
    "gov.au", "edu.au", "co.nz", "org.nz", "govt.nz",
}


def _registrable(netloc: str) -> str:
    """تقدير محافظ لهوية الناشر، مع مراعاة نطاقات متعددة المستويات المعروفة.

    ليس بديلاً عن Public Suffix List الكاملة؛ في حالة غير معروفة نرجع
    آخر عنوانين، لكن لا نُسقط جهات سورية مستقلة تحت gov.sy/edu.sy.
    """
    host = (netloc or "").lower().split(":", 1)[0].rstrip(".")
    host = host.removeprefix("www.")
    parts = host.split(".") if host else []
    if len(parts) < 2:
        return host
    suffix2 = ".".join(parts[-2:])
    if suffix2 in _COMPOUND_PUBLIC_SUFFIXES:
        return ".".join(parts[-3:]) if len(parts) >= 3 else suffix2
    return suffix2


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


# ═══════════════════ القناة 5: التتبع بين المصادر (snowball) ═══════════════════

MAX_SNOWBALL_SOURCES = 8            # مصادر معتمدة تُفحص في الدورة الواحدة
MAX_SNOWBALL_PAGES_PER_SOURCE = 3   # الصفحة الرئيسية + أحدث صفحات مزحوفة
SNOWBALL_LIMIT = 15                 # أقصى مرشحين ينتجهم هذا المسار


def external_legal_links(html: str, page_url: str, known: set) -> dict:
    """روابط خارجية بإشارة قانونية من صفحة واحدة: {url_معياري: (رابط، نص)}.

    نقية (بلا شبكة). تتجاهل روابط المضيف نفسه والنطاقات المعروفة/المستثناة.
    """
    out = {}
    own = _registrable(urlparse(page_url).netloc)
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        return out
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith(("http://", "https://")):
            continue
        reg = _registrable(urlparse(href).netloc)
        if not reg or reg == own or reg in known:
            continue
        text = a.get_text(" ", strip=True)
        if not is_legal_anchor(text, href):
            continue
        out.setdefault(canonicalize_url(href), (href, text[:80]))
    return out


def _snowball_pages(conn, base_url: str, pages: int) -> list:
    """الصفحة الرئيسية للمصدر + أحدث صفحاته المزحوفة بنجاح (نفس الناشر)."""
    urls = [base_url]
    reg = _registrable(urlparse(base_url).netloc)
    try:
        rows = conn.execute(
            "SELECT url FROM crawl_tasks WHERE status='success' "
            "ORDER BY updated_at DESC LIMIT 400").fetchall()
    except Exception:
        rows = []
    for row in rows:
        if len(urls) >= pages:
            break
        u = row["url"] if hasattr(row, "keys") else row[0]
        if u and u != base_url and _registrable(urlparse(u).netloc) == reg:
            urls.append(u)
    return urls


def snowball_candidates(conn, record_log: bool = True,
                        max_sources: int = MAX_SNOWBALL_SOURCES,
                        pages_per_source: int = MAX_SNOWBALL_PAGES_PER_SOURCE,
                        limit: int = SNOWBALL_LIMIT, today=None) -> list:
    """اكتشاف مستقل بلا محرك بحث: ما تشير إليه مصادرنا المعتمدة.

    مصدر تشير إليه عدة مصادر قانونية معتمدة أقوى دليلاً من مصدر تشير إليه
    واحدة. كل مرشح يمر لاحقاً بالتقييم نفسه (بما فيه فحص الاختصاص).
    الفحص مهذب (robots والتأخير) ومحدود؛ ويدور اختيار المصادر يومياً كي
    تُغطى كلها عبر الدورات. لا يعتمد ولا يدرج مهاماً.
    """
    from datetime import date
    sources = approved_sources(conn)
    if not sources:
        return []
    n = len(sources)
    shift = (today or date.today()).toordinal() % n
    ordered = sources[shift:] + sources[:shift]
    known = known_registrables(conn)
    endorsed_by: dict = {}   # url معياري -> {ناشرون}
    sample: dict = {}        # url معياري -> (رابط، نص)
    for src in ordered[:max_sources]:
        publisher = _registrable(urlparse(src["base_url"]).netloc)
        seen_pages = set()
        for page in _snowball_pages(conn, src["base_url"], pages_per_source):
            key = canonicalize_url(page)
            if key in seen_pages:
                continue
            seen_pages.add(key)
            try:
                res = fetch(page, record_log=record_log)
            except Exception as exc:
                log.info(f"تتبع {page[:60]} تعذر: {exc}")
                continue
            if not res.get("ok"):
                continue
            found = external_legal_links(res.get("html") or "",
                                         res.get("final_url") or page, known)
            for ckey, (href, text) in found.items():
                endorsed_by.setdefault(ckey, set()).add(publisher)
                sample.setdefault(ckey, (href, text, publisher))
    ranked = sorted(endorsed_by, key=lambda k: (-len(endorsed_by[k]), k))[:limit]
    return [Candidate(url=sample[k][0], title=sample[k][1],
                      via=f"snowball:{sample[k][2]}"
                          + (f"+{len(endorsed_by[k]) - 1}" if len(endorsed_by[k]) > 1 else ""))
            for k in ranked]


# ═══════════════════ القناة 4: خرائط المواقع ═══════════════════

_LEGAL_URL_RE = re.compile(
    r"law|qanoon|qanun|marsom|decree|legal|tashri|قانون|مرسوم", re.IGNORECASE)


def sitemap_candidates(base_url: str, limit: int = 15,
                       record_log: bool = True) -> list:
    """Sitemap: من robots.txt ثم /sitemap.xml — روابط بنمط تشريعي فقط."""
    out = []
    maps = []
    robots = fetch(base_url.rstrip("/") + "/robots.txt",
                   record_log=record_log)
    if robots.get("ok"):
        for line in robots["html"].splitlines():
            if line.lower().startswith("sitemap:"):
                maps.append(line.split(":", 1)[1].strip())
    if not maps:
        maps = [base_url.rstrip("/") + "/sitemap.xml"]
    for sm in maps[:2]:
        result = fetch(sm, record_log=record_log)
        if not result.get("ok"):
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", result["html"]):
            if _LEGAL_URL_RE.search(loc):
                out.append(Candidate(url=loc.strip(), via="sitemap"))
            if len(out) >= limit:
                return out
    return out


# ═══════════════════ توليد المرشحين (القنوات مجتمعة) ═══════════════════

def generate_candidates(conn, use_search: bool = False,
                        queries: list = None,
                        search_via: str | None = None,
                        record_log: bool = True,
                        snowball: bool = True) -> list:
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
        if search_via not in {"ddg", "bing"}:
            raise ValueError("يلزم اختيار search_via صراحةً من ddg أو bing")
        if search_via == "ddg":
            providers = [DuckDuckGoHtmlProvider()]
        else:
            from discovery import BingApiProvider
            providers = [BingApiProvider()]
        from gap_analysis import gap_driven_queries
        # B-1: الفجوات المعلومة (صكوك مستهدَفة بتعديل/إلغاء/أمومة وغير
        # محصودة) تتقدّم على كل شيء — الزاحف يبحث عمّا يعرف أنه ينقصه.
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
                + gap_driven_queries(conn)[:MAX_GAP_SEARCH_QUERIES_PER_RUN])
        effective_queries = list(dict.fromkeys(effective_queries))[:MAX_SEARCH_QUERIES_PER_RUN]
        # مزوّد يحجبنا أو تنتهي مهلته يُعطَّل لباقي الدورة؛ لا نكرر 202/403.
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
                except Exception as exc:  # عطل شبكة/مهلة — القناة تُتجاوز
                    disabled_providers.add(provider.name)
                    log.info(f"قناة {provider.name} أُوقفت بعد عطل: {exc}")

    for cand in mine_corpus_links(conn):
        add(cand)

    for src in approved_sources(conn):
        try:
            for cand in sitemap_candidates(src["base_url"],
                                           record_log=record_log):
                add(cand)
        except Exception as exc:
            log.info(f"خريطة موقع {src['base_url']} تعذرت: {exc}")

    if snowball:
        try:
            for cand in snowball_candidates(conn, record_log=record_log):
                add(cand)
        except Exception as exc:
            log.info(f"قناة التتبع بين المصادر تعذرت: {exc}")

    return cands


# ═══════════════════ بوابة الاعتماد التلقائي ═══════════════════

def auto_verdict(ev) -> tuple:
    """(ok, سبب) — أعلى من «موصى به» اليدوي لأن القرار بلا تدخل بشري."""
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
    """اعتماد استثنائي لمضيف allowlist فقط؛ لا يدرج أي مهمة في الطابور.

    الـallowlist فارغة عمداً حتى تُعاير على مجموعة مصادر سورية موثقة.
    الاعتماد وإدراج المهام مرحلتان منفصلتان حتى عند السماح بهذا المسار.
    """
    host = (urlparse(cand_url).hostname or "").lower().removeprefix("www.")
    trusted = {h.lower().removeprefix("www.") for h in AUTO_APPROVE_TRUSTED_HOSTS}
    if host not in trusted:
        log.info("   ⏸ المصدر بقي مقترحاً — لا يوجد مضيف موثوق للاعتماد الآلي")
        return False
    source = conn.execute(
        "SELECT source_role, publisher_country, collection_scope, domain_tier "
        "FROM sources WHERE source_key=?", (_source_key(cand_url),)).fetchone()
    if (source is None or source["source_role"] not in
            {"official_publisher", "court", "bar_association"} or
            source["publisher_country"] not in {"SY", "Syria", "سوريا", "سورية"} or
            not (source["collection_scope"] or "").strip() or
            source["domain_tier"] is None or source["domain_tier"] > 1):
        log.info("   ⏸ لا تكفي بيانات دور المصدر/الدولة/المجموعة/الرسمية للاعتماد")
        return False
    ok, why = auto_verdict(ev)
    if not ok:
        log.info(f"   ⏸ مقترح فقط ({why}) — يحتاج موافقة يدوية")
        return False
    decide_source(conn, _source_key(cand_url), True, decided_by="auto")
    log.info(f"   🤖 اعتُمد وفق allowlist الثابتة، بلا إدراج للطابور — {why}")
    return True


# ═══════════════════ الحلقة الكاملة ═══════════════════

def bootstrap_primary_source(conn):
    """يسجل المنتدى الأساسي كبذرة مرشحة فقط؛ لا whitelist ولا اعتماد."""
    key = _source_key(BASE_URL)
    if conn.execute("SELECT 1 FROM sources WHERE source_key = ?",
                    (key,)).fetchone():
        return False
    from datetime import datetime
    conn.execute('''
        INSERT INTO sources (source_key, base_url, name, engine, credibility,
                             status, discovered_via, discovered_at, source_role)
        VALUES (?, ?, ?, 'phpbb', 0.6, 'proposed', 'seed-primary', ?, 'unknown')
    ''', (key, canonicalize_url(BASE_URL), "مكتبة القانون السوري (منتدى)",
          datetime.now().isoformat()))
    conn.commit()
    return True


def run_discovery(conn, auto_approve: bool = False, use_search: bool = False,
                  max_evaluate: int = 12,
                  search_via: str | None = None,
                  dry_run: bool = False) -> dict:
    """يولّد ويقيّم مرشحين فقط؛ لا يعتمد ولا يدرج مهاماً.

    ``dry_run=True`` يمنع أي كتابة DB (بما فيها تسجيل seed الأساسي
    والمرشحين) لكنه لا يمنع الشبكة التي يحتاجها تقييم المصادر.
    ``auto_approve`` محفوظ لتوافق المستدعين التاريخيين ولا يغيّر الحالة.
    """
    if auto_approve:
        log.info("تجاهل auto_approve: قرار الاعتماد منفصل عن الاكتشاف وموقوف هنا")
    stats = {"seen": 0, "evaluated": 0, "new": 0, "approved": 0,
             "proposed": 0, "rejected": 0, "blocked": 0,
             "approved_list": [], "errors": []}
    if not dry_run:
        bootstrap_primary_source(conn)

    candidates = generate_candidates(conn, use_search=use_search,
                                     search_via=search_via,
                                     record_log=not dry_run)
    log.info(f"🔎 {len(candidates)} مرشحاً جديداً من القنوات الآلية")

    for cand in candidates:
        stats["seen"] += 1
        if stats["evaluated"] >= max_evaluate:
            continue
        stats["evaluated"] += 1
        log.info(f"[{stats['evaluated']}/{max_evaluate}] تقييم: "
                 f"{cand.url[:80]} (عبر: {cand.via})")
        try:
            ev = evaluate_candidate(cand.url, title_hint=cand.title,
                                   snippet=cand.snippet,
                                   record_log=not dry_run)
        except Exception as exc:
            stats["errors"].append(f"{cand.url}: {exc}")
            log.info(f"   ❌ عطل تقييم: {exc}")
            continue
        if dry_run:
            created = False
        else:
            _id, created = register_candidate(conn, cand.url, cand.via, ev)
            if created:
                stats["new"] += 1
        if ev.verdict == "blocked":
            stats["blocked"] += 1  # يبقى مرشحاً؛ robots قد تتغير لاحقاً
            stats["proposed"] += 1
        elif ev.verdict == "recommended":
            # التوصية ليست اعتماداً؛ لا يحوّل هذا المسار status إلى approved.
            stats["proposed"] += 1
        else:
            # الدرجة الآلية ليست قرار رفض نهائياً؛ يمكن أن يكون الاستخراج
            # ناقصاً أو نوع المصدر مختلفاً. يسجل السبب ويبقى مصدره proposed.
            stats["rejected"] += 1
            stats["proposed"] += 1
        if not dry_run:
            conn.commit()

    if not dry_run:
        conn.commit()
    log.info(f"🏁 التقييم: رُئي {stats['seen']} | قُيّم {stats['evaluated']} | "
             f"جديد {stats['new']} | اعتُمد allowlist={stats['approved']} | "
             f"بقي مقترحاً {stats['proposed']} | غير موصى آلياً {stats['rejected']} | "
             f"محجوب robots {stats['blocked']}")
    return stats


def run_autopilot(pages: int = 20, use_search: bool = False,
                  auto_approve: bool = False, crawl: bool = False,
                  max_evaluate: int = 12, stop_event=None,
                  dry_run: bool = False,
                  search_via: str | None = None,
                  discover: bool = False) -> dict:
    """يشغّل المراحل التي طُلبت صراحة فقط.

    افتراضياً لا يفتح قاعدة البيانات ولا يتصل بالشبكة. ``discover=True``
    يشغّل التقييم ويسجل المقترحات؛ مع ``dry_run=True`` لا تُكتب المقترحات.
    ``crawl=True`` يستهلك المهام الموجودة مسبقاً. لا يربط الاعتماد أو الإدراج
    بأحد الخيارين.
    """
    stats = {"seen": 0, "evaluated": 0, "new": 0, "approved": 0,
             "proposed": 0, "rejected": 0, "blocked": 0,
             "approved_list": [], "errors": []}
    if discover:
        if dry_run:
            import sqlite3
            from urllib.parse import quote
            from database import DB_PATH
            db_path = Path(DB_PATH)
            if db_path.exists():
                uri = "file:" + quote(str(db_path.resolve()), safe="/:") + "?mode=ro"
                conn = sqlite3.connect(uri, uri=True)
            else:
                if use_search:
                    raise ValueError("dry-run مع البحث يحتاج قاعدة موجودة؛ "
                                     "لن تُنشأ قاعدة تلقائياً للمعاينة")
                conn = sqlite3.connect(":memory:")
                conn.executescript("""
                    CREATE TABLE documents (source_url TEXT, clean_content TEXT,
                                            status TEXT, identity_key TEXT);
                    CREATE TABLE sources (id INTEGER, base_url TEXT, name TEXT,
                                          credibility REAL, status TEXT);
                """)
            conn.row_factory = sqlite3.Row
        else:
            from database import create_tables, get_connection
            create_tables()
            conn = get_connection()
        try:
            if dry_run and use_search:
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"documents", "law_amendments"}.issubset(tables):
                    raise ValueError("dry-run مع البحث يحتاج مخطط قاعدة مكتمل؛ "
                                     "لم يُنشأ أو يُهاجر أي مخطط تلقائياً")
            stats = run_discovery(conn, auto_approve=auto_approve,
                                  use_search=use_search,
                                  max_evaluate=max_evaluate,
                                  search_via=search_via,
                                  dry_run=dry_run)
        finally:
            conn.close()
    if crawl and pages > 0:
        from crawler import start_crawling
        start_crawling(max_pages=pages, dry_run=dry_run,
                       stop_event=stop_event)
    return stats
