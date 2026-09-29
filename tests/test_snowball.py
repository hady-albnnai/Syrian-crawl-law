"""قناة التتبع بين المصادر (snowball): اكتشاف مستقل بلا محرك بحث — دون شبكة."""
from datetime import date

import autopilot
import database
from autopilot import (Candidate, external_legal_links, generate_candidates,
                       snowball_candidates)

PAGE_A = """<html><body>
<a href="https://qanoon-portal.example/civil-law">القانون المدني الكامل</a>
<a href="https://facebook.com/x">تابعنا على فيسبوك</a>
<a href="https://weather.example/forecast">توقعات الطقس اليوم</a>
<a href="https://known-site.example/laws">قوانين</a>
<a href="https://a-source.example/laws/2">القانون الثاني</a>
<a href="/relative/law">قانون نسبي</a>
</body></html>"""

PAGE_B = """<html><body>
<a href="https://qanoon-portal.example/civil-law">القانون المدني</a>
<a href="https://other-legal.example/decrees">المراسيم التشريعية</a>
</body></html>"""


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "sb.db"))
    database.create_tables()
    return database.get_connection()


def _setup(monkeypatch, pages, sources):
    monkeypatch.setattr(autopilot, "approved_sources", lambda conn: sources)
    monkeypatch.setattr(autopilot, "known_registrables",
                        lambda conn: {"known-site.example"})
    fetched = []

    def fake_fetch(url, record_log=True):
        fetched.append(url)
        html = pages.get(url)
        return ({"ok": True, "html": html, "final_url": url} if html
                else {"ok": False, "html": ""})
    monkeypatch.setattr(autopilot, "fetch", fake_fetch)
    return fetched


def test_external_legal_links_filters_own_known_and_nonlegal():
    got = external_legal_links(PAGE_A, "https://a-source.example/",
                               {"known-site.example"})
    hosts = {u.split("/")[2] for u, _ in got.values()}
    assert hosts == {"qanoon-portal.example"}


def test_snowball_ranks_by_number_of_endorsing_sources(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    srcs = [{"base_url": "https://a-source.example/", "name": "A", "credibility": 3},
            {"base_url": "https://b-source.example/", "name": "B", "credibility": 3}]
    _setup(monkeypatch, {"https://a-source.example/": PAGE_A,
                         "https://b-source.example/": PAGE_B}, srcs)
    cands = snowball_candidates(conn, today=date(2026, 1, 1))
    urls = [c.url for c in cands]
    assert urls[0] == "https://qanoon-portal.example/civil-law"  # مؤيَّد من مصدرين
    assert "https://other-legal.example/decrees" in urls
    assert all(c.via.startswith("snowball:") for c in cands)
    assert "+1" in cands[0].via
    conn.close()


def test_snowball_uses_recent_successful_pages_of_same_publisher(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO crawl_tasks (url, status, updated_at) VALUES "
                 "('https://a-source.example/laws/2','success','2026-09-01'),"
                 "('https://elsewhere.example/x','success','2026-09-02'),"
                 "('https://a-source.example/laws/3','failed','2026-09-03')")
    conn.commit()
    srcs = [{"base_url": "https://a-source.example/", "name": "A", "credibility": 3}]
    fetched = _setup(monkeypatch, {"https://a-source.example/": "<html></html>",
                                   "https://a-source.example/laws/2": PAGE_B}, srcs)
    cands = snowball_candidates(conn, today=date(2026, 1, 1))
    assert fetched == ["https://a-source.example/", "https://a-source.example/laws/2"]
    assert {c.url for c in cands} == {"https://other-legal.example/decrees",
                                      "https://qanoon-portal.example/civil-law"}
    conn.close()


def test_snowball_is_bounded_and_survives_fetch_errors(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    srcs = [{"base_url": f"https://s{i}.example/", "name": str(i), "credibility": 3}
            for i in range(12)]
    fetched = _setup(monkeypatch, {}, srcs)

    def boom(url, record_log=True):
        fetched.append(url)
        raise RuntimeError("net down")
    monkeypatch.setattr(autopilot, "fetch", boom)
    assert snowball_candidates(conn, max_sources=5, today=date(2026, 1, 1)) == []
    assert len(fetched) == 5  # سقف المصادر
    conn.close()


def test_snowball_without_approved_sources_does_nothing(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    fetched = _setup(monkeypatch, {}, [])
    assert snowball_candidates(conn) == []
    assert fetched == []
    conn.close()


def test_snowball_rotation_covers_all_sources_over_days(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    srcs = [{"base_url": f"https://s{i}.example/", "name": str(i), "credibility": 3}
            for i in range(4)]
    fetched = _setup(monkeypatch, {}, srcs)
    seen = set()
    for d in range(4):
        fetched.clear()
        snowball_candidates(conn, max_sources=1, today=date.fromordinal(739000 + d))
        seen.update(fetched)
    assert len(seen) == 4
    conn.close()


def test_generate_candidates_includes_snowball_and_can_disable_it(tmp_path, monkeypatch):
    import gap_analysis
    import missing_targets
    conn = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(autopilot, "seed_candidates", lambda: [])
    monkeypatch.setattr(autopilot, "mine_corpus_links", lambda conn: [])
    monkeypatch.setattr(autopilot, "sitemap_candidates", lambda *a, **k: [])
    monkeypatch.setattr(autopilot, "reference_driven_queries", lambda conn, limit=10: [])
    monkeypatch.setattr(missing_targets, "missing_target_queries", lambda conn, limit=40: [])
    monkeypatch.setattr(gap_analysis, "gap_driven_queries", lambda conn: [])
    monkeypatch.setattr(autopilot, "snowball_candidates",
                        lambda conn, record_log=True: [Candidate(
                            url="https://found.example/", title="t", via="snowball:x")])
    on = generate_candidates(conn, use_search=False)
    off = generate_candidates(conn, use_search=False, snowball=False)
    assert any(c.via == "snowball:x" for c in on)
    assert not any(c.via == "snowball:x" for c in off)
    conn.close()


def test_cli_sources_check_is_read_only(tmp_path, monkeypatch):
    import argparse
    import cli
    import discovery
    conn = _db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO sources (source_key, base_url, name, engine, status) "
                 "VALUES ('k','https://a-source.example/','A','wordpress','approved')")
    conn.commit()
    before = conn.execute("SELECT status, evaluation_verdict FROM sources").fetchall()
    conn.close()
    calls = []

    def make_ev():
        from discovery import Evaluation
        ev = Evaluation(url="https://a-source.example/", ok=True)
        ev.jurisdiction = "syrian"
        ev.verdict = "recommended"
        ev.source_score = 80.0
        ev.details = {"jurisdiction": {"verdict": "syrian", "syrian_score": 6,
                                       "foreign_score": 0}}
        return ev

    def fake_eval(url, title_hint="", snippet="", record_log=True):
        calls.append(record_log)
        return make_ev()
    monkeypatch.setattr(discovery, "evaluate_candidate", fake_eval)
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_sources(argparse.Namespace(action="check", id=None)) == 0
    assert calls == [False]  # لا تسجيل في crawl_log
    assert any("syrian" in m and "a-source.example" in m for m in lines), lines
    assert not any("تعذر" in m for m in lines), lines
    conn = database.get_connection()
    assert conn.execute("SELECT status, evaluation_verdict FROM sources").fetchall() == before
    conn.close()


def test_english_only_legal_links_and_platform_hosts_are_ignored():
    html = ('<a href="https://foundation.wikimedia.org/wiki/Legal:Terms">Legal</a>'
            '<a href="https://some-law.example/laws">Laws and Legislation</a>'
            '<a href="https://ok.example/qanoon">القوانين السورية</a>'
            '<a href="https://gov.sy/laws">Laws</a>')
    got = external_legal_links(html, "https://a-source.example/",
                               autopilot.known_registrables_for_test()
                               if hasattr(autopilot, "known_registrables_for_test")
                               else set(autopilot._SKIP_HOSTS))
    hosts = {u.split("/")[2] for u, _ in got.values()}
    assert hosts == {"ok.example", "gov.sy"}


def test_corpus_mining_rotates_over_all_snapshots(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    snap = tmp_path / "snaps"
    snap.mkdir()
    for i in range(10):
        (snap / f"{i:02d}.html").write_text(
            f'<a href="https://site{i}.example/laws">القوانين رقم {i}</a>',
            encoding="utf-8")
    seen = set()
    for d in range(5):
        for c in autopilot.mine_corpus_links(conn, snapshot_dir=snap, max_files=2,
                                             today=date.fromordinal(739000 + d)):
            seen.add(c.url)
    assert len(seen) == 10  # كل الملفات العشرة قُرئت عبر 5 أيام
    conn.close()


def _wiki_fake(pages, hits):
    def get(params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": t} for t in hits]}}
        return {"query": {"pages": pages}}
    return get


def test_wikipedia_channel_ranks_sy_first_and_dedupes_per_host(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(autopilot, "known_registrables",
                        lambda c: {"known-site.example"} | set(autopilot._SKIP_HOSTS))
    pages = {
        "1": {"title": "قانون أ", "extlinks": [
            {"*": "https://moj.gov.sy/laws/1"}, {"*": "https://portal.example/a"},
            {"*": "https://known-site.example/x"},
            {"*": "//protocol-relative.example/home"},
            {"*": "https://commons.wikimedia.org/x"}, {"*": "mailto:x@y.z"}]},
        "2": {"title": "قانون ب", "extlinks": [
            {"*": "https://portal.example/b"}, {"*": "https://portal.example/a"},
            {"*": "https://moj.gov.sy/laws/2"}]},
    }
    cands = autopilot.wikipedia_candidates(
        conn, queries=["قانون سوري"], http_get=_wiki_fake(pages, ["قانون أ", "قانون ب"]))
    hosts = [c.url.split("/")[2] for c in cands]
    assert hosts[0] == "moj.gov.sy"                        # .sy أولاً
    assert hosts[1] == "portal.example"                    # مؤيَّد بمقالين
    assert len(hosts) == len(set(hosts))                   # رابط واحد لكل نطاق
    assert "known-site.example" not in hosts
    assert "commons.wikimedia.org" not in hosts
    assert "protocol-relative.example" in hosts
    assert cands[0].via == "wikipedia:2"
    conn.close()


def test_wikipedia_channel_survives_api_failure(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)

    def boom(params):
        raise RuntimeError("offline")
    assert autopilot.wikipedia_candidates(conn, queries=["x"], http_get=boom) == []
    conn.close()
