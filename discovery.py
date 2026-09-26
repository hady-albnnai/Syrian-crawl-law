# -*- coding: utf-8 -*-
"""discovery.py — استكشاف المصادر: الزاحف يبحث عن مصادره بنفسه.

بدل الاعتماد على مصدر واحد محجوز في config، تفتش الأداة عن مصادر قانونية
جديدة عبر ثلاث قنوات، ثم تمرر كل مرشح عبر بوابة تقييم موحدة، ولا يزحف
أي مصدر إلا بعد موافقة صريحة من المستخدم (الخيار الآمن افتراضياً):

  1) محركات بحث عبر SearchProvider:
     - DuckDuckGoHtmlProvider (بلا مفتاح — قد يُصدّ بتحدي روبوت: يعالج صراحة)
     - BingApiProvider (بمفتاح من .env — مسار التوزيع الموثوق)
  2) إدراج يدوي لروابط يقترحها المستخدم.
  3) دليل بذور مرفق بمصادر قانونية سورية معروفة (SEED_SOURCES).

التقييم: جلب مهذب يحترم robots ← استخراج التشريعات والاجتهادات ← فئة
رسمية النطاق + درجة مصدر مفسَّرة (الصلة/البنية/الاكتمال/الوصول) ← حكم
وتبرير محفوظان. التقييم منفصل عن قرار الاعتماد؛ الوضع الآمن يسجّل proposed.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import SEARCH_TIMEOUT, USER_AGENT
from crawler import canonicalize_url
from engines import detect_engine  # إعادة تصدير للتوافق — التعريف في engines
from extractor import is_legal_content, legal_score
from extractor_v4 import extract_main_content
from fetcher import fetch
from source_quality import (domain_tier_for_url, is_complete_text,
                            source_assessment_score)

# الحد الأدنى للدرجة القانونية لقبول محتوى تشريعي كمرشح.
SOURCE_MIN_SCORE = 55.0
# حد درجة التقييم الكلي الذي يسمح بوسم المصدر «موصى به» للمراجعة، لا اعتماده.
SOURCE_ASSESSMENT_MIN_SCORE = 55.0

_LEGAL_SIGNAL_RE = re.compile(
    r"قانون|مرسوم|تشريع|الماد[ةه]|الجريدة الرسمية|مجلس الشعب|"
    r"رئيس الجمهورية|القانون رقم|نص تشريعي", re.IGNORECASE)
_PRECEDENT_SIGNAL_RE = re.compile(
    r"اجتهاد|محكمة النقض|النقض|الهيئة العامة|القرار رقم|قرار قضائي|"
    r"المبدأ القانوني|أساس لعام|اساس لعام|المحكمة الإدارية العليا", re.IGNORECASE)
_LEGAL_LINK_RE = re.compile(
    r"قانون|مرسوم|تشريع|law|qanoon|qanun|decree|legislation", re.IGNORECASE)
_PRECEDENT_LINK_RE = re.compile(
    r"اجتهاد|قضائي|محكمة|قرار|حكم|precedent|judgment|court|case", re.IGNORECASE)

SEED_SOURCES = [
    ("https://law-library.syriaforums.net/", "مكتبة القانون السوري (منتدى)", 0.6),
    # بذور إضافية تُقيَّم عند الطلب ولا يُزحف لها قبل الموافقة:
    ("https://www.syrian-lawyer.club/", "بوابة المحامي السوري", 0.7),
]


@dataclass
class Candidate:
    url: str
    title: str = ""
    snippet: str = ""
    via: str = ""


@dataclass
class Evaluation:
    url: str
    ok: bool
    engine: str = "unknown"
    legal: bool = False
    score: float = 0.0                # الدرجة القانونية القديمة للتوافق
    title: str = ""
    verdict: str = "rejected"         # recommended / needs_review / rejected / blocked
    reasons: list = field(default_factory=list)
    articles: int = 0                 # مواد مستخرجة فعلياً — بوابة الطيار الآلي
    source_score: float = 0.0         # تقييم المصدر 0..100، لا قرار اعتماد
    source_type: str = "unknown"      # legislation / precedent / mixed / potential_legal / nonlegal
    domain_tier: int = 4
    details: dict = field(default_factory=dict)
    http_status: int | None = None
    sample_count: int = 0


# ═════════════════════════ بوابة التقييم ═════════════════════════

def _normal_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _link_evidence(soup, page_url: str) -> tuple[int, int]:
    """عدد روابط القانون والاجتهاد داخل الموقع نفسه؛ الروابط الخارجية لا
    ترفع تقييم مصدر يستضيف محتوى لا يملكه."""
    host = _normal_host(page_url)
    laws, precedents = set(), set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, (anchor.get("href") or "").strip())
        if urlparse(href).scheme not in ("http", "https") or _normal_host(href) != host:
            continue
        signal = (anchor.get_text(" ", strip=True) + " " + urlparse(href).path)
        key = canonicalize_url(href)
        if _LEGAL_LINK_RE.search(signal):
            laws.add(key)
        if _PRECEDENT_LINK_RE.search(signal):
            precedents.add(key)
    return len(laws), len(precedents)


def _precedent_citation_count(text: str) -> int:
    """عدد الاستشهادات القضائية ذات الهوية التي يستخرجها المحلل السوري.
    لا نعدّ مجرد ورود كلمة «قرار» دليلاً كافياً."""
    try:
        from precedent_parser import parse_text
        citations = parse_text((text or "")[:100_000], min_confidence=0.4)
        return len({c.identity_key() for c in citations if c.identity_key()})
    except Exception:
        return 0


def evaluate_candidate(url: str, title_hint: str = "",
                       snippet: str = "") -> Evaluation:
    """يفحص مرشحاً آلياً: الوصول، رسمية النطاق، صلة المحتوى، بنيته، واكتماله.

    الدرجة والحكم توصية للمراجعة فقط؛ لا يغيّران حالة المصدر ولا يبدآن الزحف.
    يستخدم الجلب المهذب (robots والتأخير) والمستخرج v4، ومحلل الاجتهادات
    السوري، وروابط الصفحة الداخلية. يبقى تقييم المرشح مبنياً على الصفحة
    المكتشفة لا على زحف كامل للموقع.
    """
    tier = domain_tier_for_url(url)
    result = fetch(url)
    if not result.get("ok"):
        err = result.get("error", "fetch_failed")
        verdict = "blocked" if err == "blocked_by_robots" else "rejected"
        return Evaluation(
            url=url, ok=False, verdict=verdict,
            reasons=[f"فشل الجلب: {err}", f"فئة النطاق: {tier}"],
            domain_tier=tier,
            details={"error": err, "domain_tier": tier,
                     "http_status": result.get("status")},
            http_status=result.get("status"), sample_count=0)

    html = result.get("html") or ""
    final_url = result.get("final_url") or url
    engine = detect_engine(html)
    soup = BeautifulSoup(html, "lxml")
    ext = extract_main_content(html, final_url)
    if ext.get("success"):
        text = ext.get("clean_text") or ""
        page_title = ext.get("title") or ""
        extracted_articles = ext.get("articles", []) or []
        extraction_ok = True
    else:
        # الصفحة الرئيسية قد تكون فهرساً جيداً لا «مقالاً» له حاوية واحدة؛
        # نقيّم نصها وروابطها بدلاً من إسقاطها فوراً.
        page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
        body = soup.body or soup
        text = body.get_text(" ", strip=True)[:100_000]
        extracted_articles = []
        extraction_ok = False
    title = page_title or title_hint or ""
    text = (text or "")[:100_000]
    score = legal_score(text, title)
    old_legal_signal = is_legal_content(text, title)
    articles = [a for a in extracted_articles if not a.get("is_preamble")]
    n_articles = len(articles)
    complete = is_complete_text(text, extracted_articles) if n_articles else None
    citation_count = _precedent_citation_count(text)
    legal_links, precedent_links = _link_evidence(soup, final_url)

    evidence_text = " ".join((title, snippet or "", text[:50_000]))
    legal_signals = len(set(m.group(0) for m in _LEGAL_SIGNAL_RE.finditer(evidence_text)))
    precedent_signals = len(set(m.group(0) for m in
                                 _PRECEDENT_SIGNAL_RE.finditer(evidence_text)))
    url_signal = bool(_LEGAL_LINK_RE.search(url) or _PRECEDENT_LINK_RE.search(url))

    law_evidence = bool(n_articles or legal_links >= 2 or
                        (old_legal_signal and legal_signals >= 1 and
                         (score >= SOURCE_MIN_SCORE or legal_signals >= 2)))
    precedent_evidence = bool(citation_count or precedent_links >= 2 or
                              (precedent_signals >= 2 and len(text) >= 250))
    if law_evidence and precedent_evidence:
        source_type = "mixed"
    elif law_evidence:
        source_type = "legislation"
    elif precedent_evidence:
        source_type = "precedent"
    elif legal_signals or precedent_signals or url_signal:
        source_type = "potential_legal"
    else:
        source_type = "nonlegal"

    assessment = source_assessment_score(
        domain_tier=tier, source_type=source_type, accessible=True,
        article_count=n_articles, precedent_count=citation_count,
        legal_link_count=legal_links + precedent_links,
        text_chars=len(text), complete_text=complete, engine=engine)
    source_score = assessment["score"]
    if source_type in {"legislation", "precedent", "mixed"} \
            and source_score >= SOURCE_ASSESSMENT_MIN_SCORE:
        verdict = "recommended"
    elif source_type == "potential_legal" and source_score >= 35:
        verdict = "needs_review"
    else:
        verdict = "rejected"

    reasons = [f"درجة تقييم المصدر: {source_score:.1f}/100"]
    reasons.append(f"رسمية النطاق: الفئة {tier}")
    if n_articles:
        reasons.append(f"استخرج {n_articles} مادة تشريعية"
                       + ("؛ تسلسل النص متصل" if complete else "؛ اكتمال النص غير محسوم"))
    else:
        reasons.append("لم تُستخرج مواد تشريعية من الصفحة")
    if citation_count:
        reasons.append(f"حلّل محلل الاجتهادات {citation_count} استشهاداً بهوية قرار")
    else:
        reasons.append("لم يُعثر على استشهاد قضائي ذي هوية مكتملة")
    if legal_links or precedent_links:
        reasons.append(f"روابط داخلية قانونية: {legal_links + precedent_links}")
    if source_type == "nonlegal":
        reasons.append("لم تُكتشف إشارات أو بنية قانونية كافية")
    elif source_type == "potential_legal":
        reasons.append(f"إشارات قانونية أولية فقط: تشريعية {legal_signals}، "
                       f"قضائية {precedent_signals}")
    if not extraction_ok:
        reasons.append("لم يُستخرج متن مقال؛ فُحص نص الصفحة وروابطها كفهرس")
    reasons.append(f"المحرك المكتشف: {engine}")
    reasons.append(f"الحكم الآلي: {verdict} (لا يساوي اعتماد المصدر)")

    details = {
        "domain_tier": tier,
        "source_type": source_type,
        "source_score": source_score,
        "components": assessment["components"],
        "evidence": {
            "legal_score": score,
            "legal_content_signal": bool(old_legal_signal),
            "article_count": n_articles,
            "precedent_citation_count": citation_count,
            "legal_internal_links": legal_links,
            "precedent_internal_links": precedent_links,
            "legal_signal_count": legal_signals,
            "precedent_signal_count": precedent_signals,
            "text_chars": len(text),
            "complete_text": complete,
            "extraction_ok": extraction_ok,
        },
        "http_status": result.get("status"),
        "final_url": final_url,
    }
    return Evaluation(
        url=url, ok=True, engine=engine,
        legal=bool(law_evidence), score=score, title=title,
        verdict=verdict, reasons=reasons, articles=n_articles,
        source_score=source_score, source_type=source_type,
        domain_tier=tier, details=details,
        http_status=result.get("status"), sample_count=1)


# ═════════════════════════ مزودو البحث ═════════════════════════

class SearchUnavailable(RuntimeError):
    """يُرفع عندما يصدّ المزود الطلب (تحدي روبوت/حظر) — يعالج في الواجهة."""


class SearchProvider:
    name = "base"

    def search(self, query: str, limit: int = 10) -> list:
        raise NotImplementedError


def parse_ddg_html(html: str) -> list:
    """تحليل صفحة نتائج DuckDuckGo HTML — دالة نقية قابلة للاختبار."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select("a.result__a"):
        out.append({"url": (a.get("href") or "").strip(),
                    "title": a.get_text(strip=True)})
    return out


class DuckDuckGoHtmlProvider(SearchProvider):
    """بحث بلا مفتاح عبر نقطة html — مهذب، ويعالج تحدي الروبوت صراحة."""
    name = "ddg"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.7",
        })

    def search(self, query: str, limit: int = 10) -> list:
        resp = self.session.post("https://html.duckduckgo.com/html/",
                                 data={"q": query}, timeout=SEARCH_TIMEOUT)
        if resp.status_code in (202, 403, 429) or "result__a" not in resp.text:
            raise SearchUnavailable(
                f"صدّ DuckDuckGo الطلب (HTTP {resp.status_code}) — "
                "جرّب BingApiProvider بمفتاح أو الإدراج اليدوي")
        rows = parse_ddg_html(resp.text)[:limit]
        return [Candidate(r["url"], r["title"], via="search:ddg") for r in rows if r["url"]]


class BingApiProvider(SearchProvider):
    """بحث موثوق بمفتاح API من .env (BING_API_KEY) — مسار نسخة التوزيع."""
    name = "bing"

    def __init__(self, api_key: str = ""):
        import os
        self.key = api_key or os.environ.get("BING_API_KEY", "")
        if not self.key:
            raise SearchUnavailable("BING_API_KEY غير مضبوط في .env")

    def search(self, query: str, limit: int = 10) -> list:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": self.key},
            params={"q": query, "mkt": "ar-SA", "count": limit},
            timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        return [Candidate(h["url"], h.get("name", ""), h.get("snippet", ""),
                          via="search:bing")
                for h in resp.json().get("webPages", {}).get("value", [])]


# ═════════════════════════ سجل المصادر ═════════════════════════

def _source_key(url: str) -> str:
    return "sha256:" + hashlib.sha256(
        canonicalize_url(url).encode("utf-8")).hexdigest()


def register_candidate(conn, candidate_url: str, via: str,
                       ev: Evaluation) -> tuple:
    """يسجل المرشح ونتيجة تقييمه القابلة للتدقيق؛ لا يغيّر قراراً سابقاً.

    إعادة الاكتشاف تحدّث آخر تقييم فقط، وتبقي status/decided_by كما هما حتى
    لا يتحول التقييم الآلي إلى موافقة أو رفض خفي.
    """
    key = _source_key(candidate_url)
    now = datetime.now().isoformat()
    reasons_json = json.dumps(ev.reasons or [], ensure_ascii=False)
    details_json = json.dumps(ev.details or {}, ensure_ascii=False,
                              sort_keys=True)
    cur = conn.cursor()
    cur.execute("SELECT id FROM sources WHERE source_key = ?", (key,))
    row = cur.fetchone()
    if row is not None:
        cur.execute('''
            UPDATE sources
               SET name = CASE WHEN name IS NULL OR name = '' OR name = base_url
                               THEN ? ELSE name END,
                   engine = ?, domain_tier = ?, evaluation_score = ?,
                   evaluation_verdict = ?, source_type = ?,
                   evaluation_reasons_json = ?, evaluation_details_json = ?,
                   evaluated_at = ?, evaluation_sample_count = ?
             WHERE id = ?
        ''', (ev.title or candidate_url, ev.engine or "unknown",
              ev.domain_tier, ev.source_score, ev.verdict, ev.source_type,
              reasons_json, details_json, now, ev.sample_count, row["id"]))
        return row["id"], False
    cur.execute('''
        INSERT INTO sources
        (source_key, base_url, name, engine, credibility, status,
         discovered_via, discovered_at, domain_tier, evaluation_score,
         evaluation_verdict, source_type, evaluation_reasons_json,
         evaluation_details_json, evaluated_at, evaluation_sample_count)
        VALUES (?, ?, ?, ?, 0.6, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (key, canonicalize_url(candidate_url), ev.title or candidate_url,
          ev.engine or "unknown", via, now, ev.domain_tier, ev.source_score,
          ev.verdict, ev.source_type, reasons_json, details_json, now,
          ev.sample_count))
    return cur.lastrowid, True


def decide_source(conn, source_key: str, approve: bool,
                  decided_by: str = "user"):
    """موافقة/رفض صريحان — لا زحف قبل approve (الخيار الآمن افتراضياً).

    decided_by: 'user' (الافتراضي — شاشة/أمر) أو 'auto' (الطيار الآلي عند
    اجتياز بوابة أعلى — انظر autopilot.auto_verdict). القرار مسجل دائماً.
    """
    conn.execute(
        "UPDATE sources SET status = ?, decided_at = ?, decided_by = ? "
        "WHERE source_key = ?",
        ("approved" if approve else "rejected",
         datetime.now().isoformat(), decided_by, source_key))
    conn.commit()


def approved_sources(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT base_url, name, credibility FROM sources "
                "WHERE status = 'approved' ORDER BY id")
    return [dict(r) for r in cur.fetchall()]


def seed_candidates() -> list:
    """دليل البذور المرفق — يُقيَّم عند الطلب ولا يُزحف قبل الموافقة."""
    return [Candidate(url, name, via="seed") for url, name, _ in SEED_SOURCES]
