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

التقييم: جلب مهذب يحترم robots ← استخراج ← درجة قانونية ← كشف المحرك
(phpBB/WordPress/عام) ← حكم (موصى به / مرفوض) بأسباب مسجلة.
المرشح يُسجل في جدول sources بحالة proposed — idempotent بمفتاح مستقر.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import requests

from config import USER_AGENT
from crawler import canonicalize_url
from extractor import extract_main_content, is_legal_content, legal_score
from fetcher import fetch

# حد الدرجة القانونية لقبول مرشح مصدر (سلم 0..100 من legal_score)
SOURCE_MIN_SCORE = 55.0

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
    score: float = 0.0
    title: str = ""
    verdict: str = "rejected"          # recommended / rejected / blocked
    reasons: list = field(default_factory=list)


# ═════════════════════════ كشف بنية المصدر ═════════════════════════

def detect_engine(html: str) -> str:
    """يكشف محرك الموقع ليختار الزاحف محوّله المناسب لاحقاً."""
    low = html.lower()
    if "postbody" in low or "viewtopic" in low or "fa_ticker_content" in low:
        return "phpbb"
    if "wp-content" in low or "entry-content" in low or "wordpress" in low:
        return "wordpress"
    return "generic"


# ═════════════════════════ بوابة التقييم ═════════════════════════

def evaluate_candidate(url: str) -> Evaluation:
    """يقيّم مرشح مصدر بجلب مهذب (يحترم robots) ثم استخراج وتحليل."""
    result = fetch(url)
    if not result.get("ok"):
        err = result.get("error", "fetch_failed")
        verdict = "blocked" if err == "blocked_by_robots" else "rejected"
        return Evaluation(url, False, verdict=verdict,
                          reasons=[f"فشل الجلب: {err}"])

    html = result["html"]
    engine = detect_engine(html)
    ext = extract_main_content(html, url)
    if not ext["success"]:
        return Evaluation(url, True, engine, False, 0.0, "",
                          "rejected", ["تعذر استخراج محتوى رئيسي"])

    text, title = ext["clean_text"], ext["title"]
    score = legal_score(text, title)
    legal = is_legal_content(text, title)
    reasons = []
    if legal:
        reasons.append("بنية مواد تشريعية مكتشفة")
    else:
        reasons.append("لا بنية مواد واضحة")
    reasons.append(f"المحرك: {engine}")

    verdict = "recommended" if (legal and score >= SOURCE_MIN_SCORE) else "rejected"
    if verdict == "rejected":
        reasons.append(f"الدرجة {score:.1f} دون حد القبول {SOURCE_MIN_SCORE}")
    return Evaluation(url, True, engine, legal, score, title, verdict, reasons)


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
                                 data={"q": query}, timeout=25)
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
            params={"q": query, "mkt": "ar-SA", "count": limit}, timeout=25)
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
    """يسجل مرشحاً في sources — idempotent بمفتاح مستقر. يعيد (id, created)."""
    key = _source_key(candidate_url)
    cur = conn.cursor()
    cur.execute("SELECT id FROM sources WHERE source_key = ?", (key,))
    row = cur.fetchone()
    if row is not None:
        return row["id"], False
    cur.execute('''
        INSERT INTO sources
        (source_key, base_url, name, engine, credibility, status,
         discovered_via, discovered_at)
        VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)
    ''', (key, canonicalize_url(candidate_url), ev.title or candidate_url,
          ev.engine, 0.6, via, datetime.now().isoformat()))
    return cur.lastrowid, True


def decide_source(conn, source_key: str, approve: bool):
    """موافقة/رفض صريحان — لا زحف قبل approve (الخيار الآمن افتراضياً)."""
    conn.execute(
        "UPDATE sources SET status = ?, decided_at = ? WHERE source_key = ?",
        ("approved" if approve else "rejected",
         datetime.now().isoformat(), source_key))
    conn.commit()


def approved_sources(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT base_url, name, credibility FROM sources "
                "WHERE status = 'approved' ORDER BY id")
    return [dict(r) for r in cur.fetchall()]


def seed_candidates() -> list:
    """دليل البذور المرفق — يُقيَّم عند الطلب ولا يُزحف قبل الموافقة."""
    return [Candidate(url, name, via="seed") for url, name, _ in SEED_SOURCES]
