# -*- coding: utf-8 -*-
"""اختبارات استكشاف المصادر — محلية بالكامل (بلا شبكة).

تحرس: كشف المحرك، بوابة التقييم (موصى/مرفوض/محجوب)، تحليل نتائج البحث،
وسجل المصادر (idempotent + لا زحف قبل موافقة).
"""
from pathlib import Path

import pytest

import database
import discovery
from discovery import (DuckDuckGoHtmlProvider, Evaluation,
                       SearchUnavailable, detect_engine, evaluate_candidate,
                       parse_ddg_html, register_candidate, decide_source,
                       approved_sources)

FIX = Path(__file__).parent / "fixtures"
LEGAL_HTML = (FIX / "phpbb_legal_topic.html").read_text(encoding="utf-8")
NON_LEGAL_HTML = (FIX / "generic_non_legal.html").read_text(encoding="utf-8")
DDG_HTML = (FIX / "ddg_results.html").read_text(encoding="utf-8")


# ───────────────────────────── كشف المحرك ─────────────────────────────

def test_detect_engine_phpbb():
    assert detect_engine(LEGAL_HTML) == "phpbb"


def test_detect_engine_wordpress():
    assert detect_engine('<div class="entry-content wp-content">نص</div>') == "wordpress"


def test_detect_engine_generic():
    assert detect_engine(NON_LEGAL_HTML) == "generic"


# ───────────────────────────── بوابة التقييم ─────────────────────────────

def _patch_fetch(monkeypatch, html):
    import fetcher
    monkeypatch.setattr(fetcher, "fetch",
                        lambda url: {"ok": True, "status": 200, "html": html,
                                     "ms": 1, "final_url": url, "encoding": "utf-8"})
    # evaluate_candidate يستورد fetch داخل discovery — نربطه بالمسخ أيضاً
    monkeypatch.setattr(discovery, "fetch", fetcher.fetch)


def test_evaluate_recommends_legal_phpbb_source(monkeypatch):
    _patch_fetch(monkeypatch, LEGAL_HTML)
    ev = evaluate_candidate("https://example-law.sy/t12-civil")
    assert ev.ok is True
    assert ev.engine == "phpbb"
    assert ev.legal is True
    assert ev.score >= discovery.SOURCE_MIN_SCORE
    assert ev.verdict == "recommended"


def test_evaluate_rejects_non_legal_source(monkeypatch):
    _patch_fetch(monkeypatch, NON_LEGAL_HTML)
    ev = evaluate_candidate("https://food.example.com/recipe")
    assert ev.verdict == "rejected"
    assert ev.legal is False


def test_evaluate_marks_robots_blocked(monkeypatch):
    import fetcher
    monkeypatch.setattr(fetcher, "fetch",
                        lambda url: {"ok": False, "status": None, "html": "",
                                     "error": "blocked_by_robots"})
    monkeypatch.setattr(discovery, "fetch", fetcher.fetch)
    ev = evaluate_candidate("https://nope.example/x")
    assert ev.verdict == "blocked"


# ───────────────────────────── تحليل نتائج البحث ─────────────────────────────

def test_parse_ddg_html_extracts_results():
    rows = parse_ddg_html(DDG_HTML)
    assert len(rows) == 3
    assert rows[0]["url"].startswith("https://")
    assert "القانون المدني" in rows[0]["title"]


def test_ddg_provider_raises_on_challenge(monkeypatch):
    class _Resp:
        status_code = 202
        text = "<html>challenge</html>"
    prov = DuckDuckGoHtmlProvider()
    monkeypatch.setattr(prov.session, "post", lambda *a, **k: _Resp())
    with pytest.raises(SearchUnavailable):
        prov.search("القانون المدني السوري")


def test_ddg_provider_parses_results(monkeypatch):
    class _Resp:
        status_code = 200
        text = DDG_HTML
    prov = DuckDuckGoHtmlProvider()
    monkeypatch.setattr(prov.session, "post", lambda *a, **k: _Resp())
    cands = prov.search("القانون المدني السوري")
    assert len(cands) == 3
    assert cands[0].via == "search:ddg"


def test_bing_provider_requires_key(monkeypatch):
    monkeypatch.delenv("BING_API_KEY", raising=False)
    with pytest.raises(SearchUnavailable):
        discovery.BingApiProvider()


# ───────────────────────────── سجل المصادر ─────────────────────────────

def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "disc.db"))
    database.create_tables()
    return database.get_connection()


def _ev(url, verdict="recommended"):
    return Evaluation(url, True, "phpbb", True, 80.0, "قانون اختبار", verdict, [])


def test_register_candidate_idempotent(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    url = "https://example-law.sy/t12-civil"
    id1, created1 = register_candidate(conn, url, "search:ddg", _ev(url))
    id2, created2 = register_candidate(conn, url + "?x=1#f", "manual", _ev(url))
    assert created1 is True and created2 is False
    assert id1 == id2  # تطبيع الرابط → مفتاح واحد
    n = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
    assert n == 1
    conn.close()


def test_no_crawl_before_approval(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    url = "https://example-law.sy/t99"
    register_candidate(conn, url, "seed", _ev(url))
    assert approved_sources(conn) == []  # مقترح فقط — لا يدخل نطاق الزحف

    key = conn.execute("SELECT source_key FROM sources").fetchone()["source_key"]
    decide_source(conn, key, approve=True)
    appr = approved_sources(conn)
    assert len(appr) == 1 and appr[0]["base_url"].endswith("/t99")

    decide_source(conn, key, approve=False)
    assert approved_sources(conn) == []
    conn.close()


# ───────────── انحدار: علة الرمز العريض "es" في robots المصدر ─────────────

def test_overbroad_robots_token_regression(monkeypatch):
    """robots.txt المنتدى حوى 'User-agent: es' فطابق 'Research' بالمصادفة.
    المعرف الجديد يجب ألا يطابقه، مع بقاء قيود '*' نافذة."""
    import fetcher
    from urllib.robotparser import RobotFileParser
    rp = RobotFileParser()
    rp.parse((FIX / "robots_overbroad.txt").read_text(encoding="utf-8").splitlines())
    monkeypatch.setattr(fetcher, "RESPECT_ROBOTS", True)
    fetcher._ROBOT_CACHE.clear()
    fetcher._ROBOT_CACHE["law-library.example"] = rp
    base = "https://law-library.example/f3-montada"
    old_ua = "SyrianLawResearchBot/0.1 (Educational Legal Archiving Project)"
    from config import USER_AGENT
    assert "es" in old_ua.lower() and rp.can_fetch(old_ua, base) is False
    assert rp.can_fetch(USER_AGENT, base) is True          # محتوى: مسموح
    assert fetcher.is_allowed(base) is True
    assert rp.can_fetch(USER_AGENT, "https://law-library.example/abuse") is False
    fetcher._ROBOT_CACHE.clear()
