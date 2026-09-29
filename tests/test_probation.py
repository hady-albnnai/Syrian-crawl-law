"""مرحلة الاختبار (probation) والحصاد بضغطة واحدة — دون شبكة."""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import database
import probation
from discovery import Evaluation
from probation import decide_from_metrics, measure_sample, run_probation, sample_urls

sys.path.insert(0, str(Path(__file__).parent))
FIX = Path(__file__).parent / "fixtures"
WP_POST = (FIX / "wp_legal_post.html").read_text(encoding="utf-8")


def _m(**kw):
    base = dict(pages_ok=12, pages_failed=0, law_pages=8, syrian_pages=8,
                foreign_pages=0, compatible_law_pages=8, unknown_pages=4,
                new_pages=9, foreign_countries=[])
    base.update(kw)
    return base


def test_decide_promotes_clean_syrian_sample():
    assert decide_from_metrics(_m())[0] == "promote"


def test_decide_rejects_foreign_leakage_like_shamel():
    d, why = decide_from_metrics(_m(foreign_pages=5, foreign_countries=["الأردن"]))
    assert d == "reject" and "الأردن" in why


def test_decide_holds_on_small_or_weak_samples():
    assert decide_from_metrics(_m(pages_ok=2))[0] == "hold"
    assert decide_from_metrics(_m(law_pages=1, compatible_law_pages=1))[0] == "hold"
    assert decide_from_metrics(_m(compatible_law_pages=3))[0] == "hold"
    assert decide_from_metrics({"error": "blocked_by_robots", "pages_ok": 0})[0] == "hold"


def test_sample_urls_are_same_host_legal_and_spread():
    links = "".join(f'<a href="/law/{i}">قانون {i}</a>' for i in range(40))
    html = (f"<html><body>{links}"
            '<a href="https://other.example/law">قانون خارجي</a>'
            '<a href="/about">من نحن</a></body></html>')
    got = sample_urls(html, "https://s.example/", limit=10)
    assert len(got) == 10 and all("s.example" in u for u in got)
    nums = sorted(int(u.rsplit("/", 1)[1]) for u in got)
    assert nums[-1] > 25  # موزّعة على القائمة لا أول 10 فقط


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "pb.db"))
    database.create_tables()
    return database.get_connection()


def _add_source(conn, n, status="proposed", verdict="recommended", decided_by=None):
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name, engine, status, "
        "evaluation_verdict, evaluation_score, decided_by) VALUES (?,?,?,?,?,?,?,?)",
        (f"k{n}", f"https://s{n}.example/", f"S{n}", "wordpress", status, verdict,
         90 - n, decided_by))
    conn.commit()


def _ev(jur="syrian", verdict="recommended", articles=5, score=85.0):
    return Evaluation(url="u", ok=True, verdict=verdict, legal=True, score=score,
                      source_type="legislation", articles=articles,
                      source_score=score, jurisdiction=jur)


def _status(conn, n):
    return conn.execute("SELECT status, decided_by FROM sources WHERE source_key=?",
                        (f"k{n}",)).fetchone()


def test_run_probation_promotes_rejects_holds_and_respects_user(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    for n in (1, 2, 3, 4, 5):
        _add_source(conn, n)
    _add_source(conn, 6, decided_by="user")          # قرار المالك لا يُمسّ
    evs = {"https://s4.example/": _ev(jur="foreign")}  # لا يجتاز بوابة الدخول
    metrics = {"https://s1.example/": _m(),
               "https://s2.example/": _m(foreign_pages=6, foreign_countries=["مصر"]),
               "https://s3.example/": _m(pages_ok=1),
               "https://s5.example/": _m()}
    stats = run_probation(
        conn, evaluate_fn=lambda url, record_log=True: evs.get(url, _ev()),
        measure_fn=lambda c, url: metrics[url])
    assert (stats["promoted"], stats["rejected"], stats["held"],
            stats["skipped_gate"]) == (2, 1, 1, 1)
    assert tuple(_status(conn, 1)) == ("approved", "auto-probation")
    assert tuple(_status(conn, 2)) == ("rejected", "auto-probation")
    assert _status(conn, 3)["status"] == "proposed"
    assert _status(conn, 4)["status"] == "proposed"
    assert tuple(_status(conn, 6)) == ("proposed", "user")
    note = conn.execute("SELECT evaluation_reasons_json FROM sources "
                        "WHERE source_key='k1'").fetchone()[0]
    assert "اختبار آلي (promote)" in note
    conn.close()


def test_run_probation_dry_run_writes_nothing(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1)
    stats = run_probation(conn, dry_run=True,
                          evaluate_fn=lambda url, record_log=True: _ev(),
                          measure_fn=lambda c, url: _m())
    assert stats["tested"] == 1 and stats["promoted"] == 0
    assert _status(conn, 1)["status"] == "proposed"
    conn.close()


def test_measure_sample_counts_syrian_and_foreign_pages(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    neutral = WP_POST.replace("السوري", "").replace("السورية", "")
    # الإشارات الأجنبية داخل متن الوثيقة نفسه (لا في قالب الموقع)
    foreign = neutral.replace("رئيس الجمهورية", "جمهورية مصر العربية القانون المصري "
                              "محكمة النقض المصرية الوقائع المصرية", 1)
    pages = {"https://s.example/": WP_POST, "https://s.example/a": WP_POST,
             "https://s.example/b": foreign}

    def fake_fetch(url, record_log=True):
        assert record_log is False  # العينة لا تكتب في crawl_log
        html = pages.get(url)
        return ({"ok": True, "html": html, "final_url": url} if html
                else {"ok": False, "error": "404"})
    m = measure_sample(conn, "https://s.example/", fetch_fn=fake_fetch,
                       sample_fn=lambda html, base, limit: [
                           "https://s.example/a", "https://s.example/b",
                           "https://s.example/missing"])
    assert m["pages_ok"] == 3 and m["pages_failed"] == 1
    assert m["syrian_pages"] == 2 and m["foreign_pages"] == 1
    assert "مصر" in m["foreign_countries"]
    assert m["new_pages"] == 3
    conn.close()


def test_refresh_sections_requeues_only_old_successful_section_tasks(tmp_path, monkeypatch):
    import harvest
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1, status="approved")
    old = (datetime.now() - timedelta(days=30)).isoformat()
    new = datetime.now().isoformat()
    conn.execute("INSERT INTO crawl_tasks (url, kind, status, updated_at) VALUES "
                 "('https://s1.example/','section','success',?),"
                 "('https://s1.example/t1','topic','success',?)", (old, old))
    conn.commit()
    assert harvest.refresh_sections(conn, 7) == 1
    rows = dict(conn.execute("SELECT url, status FROM crawl_tasks").fetchall())
    assert rows["https://s1.example/"] == "queued"
    assert rows["https://s1.example/t1"] == "success"
    conn.execute("UPDATE crawl_tasks SET status='success', updated_at=? "
                 "WHERE url='https://s1.example/'", (new,))
    conn.commit()
    assert harvest.refresh_sections(conn, 7) == 0  # حديثة: لا تُعاد
    conn.close()


def test_harvest_dry_run_does_not_enqueue_or_crawl(tmp_path, monkeypatch):
    import autopilot
    import crawler
    import harvest
    _db(tmp_path, monkeypatch).close()
    monkeypatch.setattr(autopilot, "run_discovery",
                        lambda conn, **kw: {"seen": 0, "evaluated": 0, "new": 0})
    monkeypatch.setattr(probation, "run_probation",
                        lambda conn, **kw: {"tested": 0, "promoted": 0})
    called = []
    monkeypatch.setattr(crawler, "start_crawling", lambda **kw: called.append(kw))
    rep = harvest.run_harvest(dry_run=True)
    assert rep["enqueued"] == 0 and called == []


def test_harvest_live_enqueues_then_crawls_and_cli_wiring(tmp_path, monkeypatch):
    import autopilot
    import cli
    import crawler
    import harvest
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1, status="approved")
    conn.close()
    monkeypatch.setattr(autopilot, "run_discovery",
                        lambda conn, **kw: {"seen": 1, "evaluated": 1, "new": 1})
    monkeypatch.setattr(probation, "run_probation",
                        lambda conn, **kw: {"tested": 1, "promoted": 1})
    called = []
    monkeypatch.setattr(crawler, "start_crawling", lambda **kw: called.append(kw))
    args = argparse.Namespace(pages=5, search_via=None, max_evaluate=3,
                              refresh_days=7, no_crawl=False, dry=False)
    assert cli.cmd_harvest(args) == 0
    assert called == [{"max_pages": 5, "dry_run": False, "stop_event": None}]
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks WHERE status='queued'"
                        ).fetchone()[0] == 1
    conn.close()


def test_probation_also_tests_never_evaluated_proposed_sources_and_stores_evaluation(
        tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1, verdict=None)   # مقترح قديم بلا تقييم (حالة مصادر المالك)
    stats = run_probation(conn, evaluate_fn=lambda url, record_log=True: _ev(),
                          measure_fn=lambda c, url: _m())
    assert stats["promoted"] == 1
    row = conn.execute("SELECT evaluation_verdict, evaluated_at FROM sources "
                       "WHERE source_key='k1'").fetchone()
    assert row["evaluation_verdict"] == "recommended" and row["evaluated_at"]
    conn.close()


def test_harvest_no_crawl_approves_but_does_not_enqueue(tmp_path, monkeypatch):
    import autopilot
    import crawler
    import harvest
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1, status="approved")
    conn.close()
    monkeypatch.setattr(autopilot, "run_discovery",
                        lambda conn, **kw: {"seen": 0, "evaluated": 0, "new": 0})
    monkeypatch.setattr(probation, "run_probation",
                        lambda conn, **kw: {"tested": 0, "promoted": 0})
    called = []
    monkeypatch.setattr(crawler, "start_crawling", lambda **kw: called.append(kw))
    rep = harvest.run_harvest(crawl=False)
    assert rep["enqueued"] == 0 and called == []
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0
    conn.close()


def test_unproven_jurisdiction_needs_syrian_evidence_in_sample():
    weak = _m(syrian_pages=1, unknown_pages=11)
    assert decide_from_metrics(weak, "unknown")[0] == "hold"
    assert decide_from_metrics(weak, "syrian")[0] == "promote"
    strong = _m(syrian_pages=6)
    assert decide_from_metrics(strong, "unknown")[0] == "promote"
    assert decide_from_metrics(_m(foreign_pages=4), "mixed")[0] == "reject"


def test_entry_gate_accepts_index_portals_without_articles_but_not_foreign():
    from probation import entry_gate
    assert entry_gate(_ev(jur="unknown", verdict="needs_review", articles=0,
                          score=74.0))[0]
    assert not entry_gate(_ev(jur="foreign"))[0]
    assert not entry_gate(_ev(score=40.0))[0]
    ev = _ev()
    ev.source_type = "nonlegal"
    assert not entry_gate(ev)[0]


def test_jurisdiction_uses_main_text_not_site_template(tmp_path, monkeypatch):
    """قالب موقع يسرد قوانين دول أخرى في كل صفحة لا يجعل الصفحة السورية أجنبية."""
    conn = _db(tmp_path, monkeypatch)
    nav = ("<div class=\"sidebar\">قسم القانون المصري جمهورية مصر العربية محكمة النقض "
           "المصرية الوقائع المصرية القانون السعودي نظام المرافعات الشرعية المملكة "
           "العربية السعودية ديوان المظالم السعودي</div>")
    page = WP_POST.replace("<body>", "<body>" + nav, 1) if "<body>" in WP_POST else nav + WP_POST
    pages = {"https://s.example/": page, "https://s.example/a": page,
             "https://s.example/b": page.replace("رقم 148", "رقم 149")}

    def fake_fetch(url, record_log=True):
        html = pages.get(url)
        return ({"ok": True, "html": html, "final_url": url} if html
                else {"ok": False, "error": "404"})
    m = measure_sample(conn, "https://s.example/", fetch_fn=fake_fetch,
                       sample_fn=lambda h, b, l: ["https://s.example/a",
                                                  "https://s.example/b"])
    assert m["foreign_pages"] == 0, m
    assert m["syrian_pages"] >= 2
    conn.close()


def test_duplicate_url_variants_count_as_one_law_page(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    pages = {"https://s.example/": WP_POST, "https://s.example/a": WP_POST,
             "https://s.example/ar/a": WP_POST}

    def fake_fetch(url, record_log=True):
        html = pages.get(url)
        return ({"ok": True, "html": html, "final_url": url} if html
                else {"ok": False, "error": "404"})
    m = measure_sample(conn, "https://s.example/", fetch_fn=fake_fetch,
                       sample_fn=lambda h, b, l: ["https://s.example/a",
                                                  "https://s.example/ar/a"])
    assert m["pages_ok"] == 3 and m["law_pages"] == 1
    conn.close()


def test_cli_sources_reset_returns_source_to_proposed(tmp_path, monkeypatch):
    import cli
    conn = _db(tmp_path, monkeypatch)
    _add_source(conn, 1, status="rejected", decided_by="auto-probation")
    sid = conn.execute("SELECT id FROM sources").fetchone()[0]
    conn.close()
    assert cli.cmd_sources(argparse.Namespace(action="reset", id=str(sid))) == 0
    conn = database.get_connection()
    row = conn.execute("SELECT status, decided_by FROM sources").fetchone()
    assert (row["status"], row["decided_by"]) == ("proposed", None)
    conn.close()


def test_single_foreign_page_in_small_sample_is_hold_not_reject():
    d, why = decide_from_metrics(_m(pages_ok=9, foreign_pages=1, law_pages=5,
                                    compatible_law_pages=5, foreign_countries=["مصر"]))
    assert d == "hold" and "مصر" in why
    assert decide_from_metrics(_m(pages_ok=9, foreign_pages=2))[0] == "reject"


def test_sample_prefers_topic_like_links_over_section_indexes():
    sections = "".join(f'<a href="/f{i}-section">قوانين قسم {i}</a>' for i in range(30))
    topics = "".join(f'<a href="/t{100 + i}-topic">قانون رقم {i}</a>' for i in range(30))
    got = sample_urls(f"<html><body>{sections}{topics}</body></html>",
                      "https://s.example/", limit=12)
    assert sum("/t" in u for u in got) >= 8
