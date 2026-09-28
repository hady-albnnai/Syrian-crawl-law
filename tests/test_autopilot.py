# -*- coding: utf-8 -*-
"""اختبارات تقييم المرشحين وفصل الاعتماد والطابور والجلب.

محلية بالكامل (بلا شبكة): استخراج/تنقيب الروابط، تقييمات ثابتة، وسياسات
عدم الاعتماد أو إدراج المهام أو الزحف ضمناً، مع fixtures للزاحف.
"""
from pathlib import Path

import pytest

import autopilot
import crawl_queue as taskqueue
import database
import discovery
import engines
from autopilot import (AUTO_APPROVE_MIN_ARTICLES, AUTO_APPROVE_MIN_SCORE,
                       auto_verdict, bootstrap_primary_source,
                       consider_auto_approve, mine_corpus_links,
                       run_discovery, sitemap_candidates)
from discovery import Candidate, Evaluation, _source_key

FIX = Path(__file__).parent / "fixtures"
WP_LISTING = (FIX / "wp_legal_listing.html").read_text(encoding="utf-8")
WP_POST = (FIX / "wp_legal_post.html").read_text(encoding="utf-8")
WP_SHORT = (FIX / "wp_short_post.html").read_text(encoding="utf-8")
GENERIC_LISTING = (FIX / "generic_legal_listing.html").read_text(encoding="utf-8")
GENERIC_NON_LEGAL = (FIX / "generic_non_legal.html").read_text(encoding="utf-8")
CORPUS_PAGE = (FIX / "corpus_page.html").read_text(encoding="utf-8")
ROBOTS = (FIX / "robots_with_sitemap.txt").read_text(encoding="utf-8")
SITEMAP = (FIX / "sitemap_basic.xml").read_text(encoding="utf-8")


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "ap.db"))
    database.create_tables()
    return database.get_connection()


# ═════════════════ استخراج الروابط حسب المحرك ═════════════════

def test_wp_listing_topics_and_pagination():
    assert engines.detect_engine(WP_LISTING) == "wordpress"
    topics = engines.extract_topic_links(WP_LISTING, "https://laws-blog.example/",
                                         "wordpress")
    assert "https://laws-blog.example/2024/05/syrian-civil-law" in topics
    assert "https://laws-blog.example/?p=12" in topics
    assert "https://laws-blog.example/archives/decree-30" in topics
    # روابط التنقل/التواصل ليست وثائق:
    assert all("/about/" not in t and "facebook" not in t for t in topics)
    pages = engines.extract_pagination_links(WP_LISTING,
                                             "https://laws-blog.example/",
                                             "wordpress")
    assert pages == ["https://laws-blog.example/page/2/"]


def test_generic_listing_uses_legal_anchors_only():
    assert engines.detect_engine(GENERIC_LISTING) == "generic"
    topics = engines.extract_topic_links(GENERIC_LISTING,
                                         "https://portal.example/", "generic")
    assert len(topics) == 3  # المدني + العقوبات + المرسوم فقط
    assert all("twitter" not in t and "/about" not in t for t in topics)
    pages = engines.extract_pagination_links(GENERIC_LISTING,
                                             "https://portal.example/",
                                             "generic")
    assert pages == ["https://portal.example/laws/civil-code?page=2"]


def test_wp_pagination_respects_same_host():
    html = ('<div class="wp-content"><a href="https://evil.example/page/2/">'
            'التالي</a></div>')
    assert engines.extract_pagination_links(
        html, "https://laws-blog.example/", "wordpress") == []


# ═════════════════ القناة 3: تنقيب المتن المخزون ═════════════════

def test_registrable_keeps_independent_sy_government_publishers():
    assert autopilot._registrable("moj.gov.sy") == "moj.gov.sy"
    assert autopilot._registrable("parliament.gov.sy") == "parliament.gov.sy"
    assert autopilot._registrable("law-library.syriaforums.net") == "syriaforums.net"


def test_external_search_provider_must_be_selected(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="search_via"):
        autopilot.generate_candidates(conn, use_search=True)
    conn.close()


def test_cli_autopilot_crawl_is_independent_of_discovery(monkeypatch):
    from types import SimpleNamespace
    import cli
    import crawler
    calls = []
    monkeypatch.setattr(crawler, "start_crawling",
                        lambda **kwargs: calls.append(kwargs))
    args = SimpleNamespace(discover=False, crawl=True, search=False,
                           search_via=None, pages=7, max_evaluate=12)
    assert cli.cmd_autopilot(args) == 0
    assert calls == [{"max_pages": 7, "dry_run": False}]


def test_cli_autopilot_search_requires_explicit_discovery():
    from types import SimpleNamespace
    import cli
    args = SimpleNamespace(discover=False, crawl=False, search=True,
                           search_via="ddg", pages=10, max_evaluate=12)
    assert cli.cmd_autopilot(args) == 2


def test_run_autopilot_default_is_side_effect_free(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("default autopilot must not evaluate or crawl")
    monkeypatch.setattr(autopilot, "run_discovery", forbidden)
    import crawler
    monkeypatch.setattr(crawler, "start_crawling", forbidden)
    stats = autopilot.run_autopilot()
    assert stats["seen"] == stats["evaluated"] == stats["new"] == 0


def test_run_autopilot_preview_without_database_does_not_create_one(
        tmp_path, monkeypatch):
    db_path = tmp_path / "absent.sqlite"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(autopilot, "generate_candidates",
                        lambda *_a, **_kw: [])
    stats = autopilot.run_autopilot(discover=True, dry_run=True)
    assert stats["seen"] == 0
    assert not db_path.exists()


def test_run_autopilot_preview_opens_existing_database_read_only(
        tmp_path, monkeypatch):
    import sqlite3
    db_path = tmp_path / "existing.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('kept')")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    observed = {}

    def probe(conn, **kwargs):
        observed["value"] = conn.execute("SELECT value FROM marker").fetchone()[0]
        assert kwargs["dry_run"] is True
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE forbidden (id INTEGER)")
        return {"preview": True}

    monkeypatch.setattr(autopilot, "run_discovery", probe)
    assert autopilot.run_autopilot(discover=True, dry_run=True) == {"preview": True}
    assert observed["value"] == "kept"
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "forbidden" not in tables


def test_run_autopilot_crawl_only_skips_discovery(monkeypatch):
    from threading import Event
    calls = []
    def forbidden(*_args, **_kwargs):
        raise AssertionError("crawl-only path must not discover")
    import crawler
    monkeypatch.setattr(autopilot, "run_discovery", forbidden)
    monkeypatch.setattr(crawler, "start_crawling",
                        lambda **kwargs: calls.append(kwargs))
    event = Event()
    autopilot.run_autopilot(pages=4, crawl=True, stop_event=event)
    assert calls == [{"max_pages": 4, "dry_run": False, "stop_event": event}]


def test_mine_corpus_links_picks_external_legal_only(tmp_path, tmp_path_factory,
                                                     monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    snap = tmp_path / "snapshots"
    snap.mkdir()
    (snap / "a.html").write_text(CORPUS_PAGE, encoding="utf-8")
    cands = mine_corpus_links(conn, snapshot_dir=snap)
    urls = [c.url for c in cands]
    assert urls == ["https://qanoon-portal.example/civil-law"]
    assert cands[0].via == "corpus"
    conn.close()


def test_mine_corpus_skips_known_registrable(tmp_path, monkeypatch):
    """رابط لنطاق فرعي من المتن الحالي ليس «مصدراً جديداً»."""
    conn = _tmp_db(tmp_path, monkeypatch)
    conn.execute("INSERT INTO documents (doc_id, title, source_url, branch, "
                 "branch_confidence, legal_score, content_hash, scraped_at, "
                 "clean_content) VALUES ('d1','ت','https://law-library."
                 "syriaforums.net/t1','x',0.9,90,'h','2026','نص')")
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "a.html").write_text(
        '<a href="https://old.syriaforums.net/t5">قانون قديم</a>',
        encoding="utf-8")
    assert mine_corpus_links(conn, snapshot_dir=snap) == []
    conn.close()


# ═════════════════ القناة 4: خرائط المواقع ═════════════════

def test_sitemap_candidates_from_robots_then_sitemap(monkeypatch):
    calls = []

    def fake_fetch(url, **kw):
        calls.append(kw.get("record_log", True))
        body = ROBOTS if url.endswith("robots.txt") else SITEMAP
        return {"ok": True, "status": 200, "html": body, "ms": 1,
                "final_url": url, "encoding": "utf-8"}

    monkeypatch.setattr(autopilot, "fetch", fake_fetch)
    cands = sitemap_candidates("https://src.example/", record_log=False)
    urls = [c.url for c in cands]
    assert "https://src.example/laws/civil-law" in urls
    assert "https://src.example/qanoon/penal-code" in urls
    assert all("blog/hello" not in u for u in urls)
    assert all(c.via == "sitemap" for c in cands)
    assert calls == [False, False]


# ═════════════════ بوابة الاعتماد التلقائي ═════════════════

def _ev(verdict="recommended", score=80.0, articles=4):
    return Evaluation("https://x.example/", True, "wordpress", True, score,
                      "عنوان", verdict, [], articles)


def test_discovery_dry_run_does_not_register_primary_or_candidates(
        tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    candidate = Candidate("https://new.example/law", "قانون", via="fixture")
    seen = {}

    def fake_generate(_conn, **kwargs):
        seen["generation_record_log"] = kwargs["record_log"]
        return [candidate]

    def fake_evaluate(_url, **kwargs):
        seen["evaluation_record_log"] = kwargs["record_log"]
        return _ev()

    monkeypatch.setattr(autopilot, "generate_candidates", fake_generate)
    monkeypatch.setattr(autopilot, "evaluate_candidate", fake_evaluate)
    stats = run_discovery(conn, dry_run=True, max_evaluate=1)
    assert stats["evaluated"] == 1 and stats["proposed"] == 1
    assert seen == {"generation_record_log": False,
                    "evaluation_record_log": False}
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert taskqueue.pending_count(conn) == 0
    conn.close()


def test_auto_gate_passes_strong_source():

    ok, why = auto_verdict(_ev())
    assert ok and "محرك wordpress" in why


def test_auto_gate_rejects_low_score():
    ok, _ = auto_verdict(_ev(score=AUTO_APPROVE_MIN_SCORE - 1))
    assert not ok


def test_auto_gate_rejects_few_articles():
    ok, _ = auto_verdict(_ev(articles=AUTO_APPROVE_MIN_ARTICLES - 1))
    assert not ok


def test_auto_gate_rejects_non_recommended():
    ok, _ = auto_verdict(_ev(verdict="rejected", score=99, articles=9))
    assert not ok


def test_auto_approval_is_disabled_without_trusted_host_and_never_queues(
        tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    ev = _ev()
    discovery.register_candidate(conn, ev.url, "test", ev)
    monkeypatch.setattr(autopilot, "AUTO_APPROVE_TRUSTED_HOSTS",
                        frozenset({"x.example"}))
    # النطاق وحده لا يكفي؛ الدور/الدولة/المجموعة/فئة الرسمية مجهولة.
    assert consider_auto_approve(conn, ev.url, ev) is False
    row = conn.execute("SELECT status, decided_by FROM sources WHERE "
                       "source_key = ?", (_source_key(ev.url),)).fetchone()
    assert row["status"] == "proposed" and row["decided_by"] is None
    assert taskqueue.pending_count(conn) == 0
    conn.close()


def test_allowlisted_auto_approval_still_does_not_enqueue(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    ev = _ev()
    discovery.register_candidate(conn, ev.url, "test", ev)
    conn.execute("UPDATE sources SET source_role='official_publisher', "
                 "publisher_country='SY', collection_scope='legislation', "
                 "domain_tier=0 WHERE source_key=?", (_source_key(ev.url),))
    conn.commit()
    monkeypatch.setattr(autopilot, "AUTO_APPROVE_TRUSTED_HOSTS",
                        frozenset({"x.example"}))
    assert consider_auto_approve(conn, ev.url, ev) is True
    row = conn.execute("SELECT status, decided_by FROM sources WHERE "
                       "source_key = ?", (_source_key(ev.url),)).fetchone()
    assert row["status"] == "approved" and row["decided_by"] == "auto"
    assert taskqueue.pending_count(conn) == 0
    conn.close()


def test_consider_auto_approve_keeps_weak_source_proposed(tmp_path,
                                                          monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    ev = _ev(articles=1)
    discovery.register_candidate(conn, ev.url, "test", ev)
    assert consider_auto_approve(conn, ev.url, ev) is False
    row = conn.execute("SELECT status, decided_by FROM sources WHERE "
                       "source_key = ?", (_source_key(ev.url),)).fetchone()
    assert row["status"] == "proposed" and row["decided_by"] is None
    conn.close()


def test_bootstrap_primary_source_idempotent(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    assert bootstrap_primary_source(conn) is True
    assert bootstrap_primary_source(conn) is False
    row = conn.execute("SELECT status, decided_by FROM sources").fetchone()
    assert row["status"] == "proposed" and row["decided_by"] is None
    assert taskqueue.pending_count(conn) == 0
    conn.close()


# ═════════════════ الحلقة الكاملة (بلا شبكة) ═════════════════

URL_PASS = "https://laws-blog.example/2024/05/penal"
URL_WEAK = "https://laws-blog.example/2024/04/decision-7"
URL_JUNK = "https://junk.example/page"


def _patched_fetch(url, **kw):
    html = {URL_PASS: WP_POST, URL_WEAK: WP_SHORT,
            URL_JUNK: GENERIC_NON_LEGAL}[url]
    return {"ok": True, "status": 200, "html": html, "ms": 1,
            "final_url": url, "encoding": "utf-8"}


def test_run_discovery_full_loop_offline(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(discovery, "fetch", _patched_fetch)
    monkeypatch.setattr(autopilot, "generate_candidates",
                        lambda c, use_search=False, search_via=None, **_kw: [
                            Candidate(URL_PASS, "قانون العقوبات", via="corpus"),
                            Candidate(URL_WEAK, "قرار 7", via="corpus"),
                            Candidate(URL_JUNK, "مدونة طبخ", via="search:ddg"),
                        ])
    stats = run_discovery(conn, auto_approve=True, use_search=False)

    assert stats["evaluated"] == 3
    assert stats["approved"] == 0  # لا allowlist موثوقة افتراضياً
    assert stats["proposed"] == 3
    assert stats["rejected"] == 1  # الصفحة الضعيفة ما زالت مرشحاً لا قرار رفض
    assert stats["approved_list"] == []

    strong = conn.execute("SELECT status, decided_by, engine, evaluation_verdict "
                          "FROM sources WHERE base_url = ?", (URL_PASS,)).fetchone()
    assert (strong["status"], strong["decided_by"], strong["engine"],
            strong["evaluation_verdict"]) == ("proposed", None, "wordpress", "recommended")

    weak = conn.execute("SELECT status, evaluation_verdict FROM sources WHERE base_url = ?",
                        (URL_WEAK,)).fetchone()
    assert (weak["status"], weak["evaluation_verdict"]) == ("proposed", "recommended")

    junk = conn.execute("SELECT status, evaluation_verdict FROM sources WHERE base_url = ?",
                        (URL_JUNK,)).fetchone()
    assert (junk["status"], junk["evaluation_verdict"]) == ("proposed", "rejected")

    # التقييم والاعتماد لا يُدرجان أي URL تلقائياً.
    assert taskqueue.pending_count(conn) == 0
    conn.close()


# ═════════════════ الزاحف يتعامل مع مصدر مكتشف ═════════════════

def test_crawler_handles_discovered_wordpress_source(tmp_path, monkeypatch):
    """قائمة WordPress معتمدة ← الزاحف يكشف المحرك ويستخرج وثائقها.

    الطابور يُبذر بالقائمة أولاً (فلا يُبذر المنتدى)، وبذر المصادر المعتمدة
    idempotent — ثم دورة واحدة تعالج القائمة بمسار الزاحف الحقيقي.
    """
    import crawler
    conn = _tmp_db(tmp_path, monkeypatch)
    listing_url = "https://laws-blog.example/"
    taskqueue.enqueue(conn, listing_url, "مدونة التشريعات", "section")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources",
                        lambda c: [{"base_url": listing_url,
                                    "name": "مدونة التشريعات",
                                    "credibility": 0.8}])
    monkeypatch.setattr(crawler, "fetch",
                        lambda url, **kw: {"ok": True, "status": 200,
                                           "html": WP_LISTING, "ms": 1,
                                           "final_url": url,
                                           "encoding": "utf-8"})
    crawler.start_crawling(max_pages=1)

    queued = [r["url"] for r in conn.execute(
        "SELECT url FROM crawl_tasks WHERE status='queued'")]
    assert "https://laws-blog.example/2024/05/syrian-civil-law" in queued
    assert "https://laws-blog.example/archives/decree-30" in queued
    # الترقيم أيضاً — بمفتاح الطابور المطبَّع (بلا شرطة ختامية)
    assert "https://laws-blog.example/page/2" in queued
    listing = conn.execute("SELECT status FROM crawl_tasks WHERE url = ?",
                           (listing_url,)).fetchone()
    assert listing["status"] == "success"
    conn.close()


def test_section_page_that_is_full_document_saved(tmp_path, monkeypatch):
    """مصدر أحادي الصفحة (ويكي مصدر مثلاً): الصفحة نفسها وثيقة كاملة —
    تُحفظ بموادها ولا تضيع باعتبارها قائمة."""
    import crawler
    conn = _tmp_db(tmp_path, monkeypatch)
    doc_url = "https://laws-blog.example/2024/05/penal"
    taskqueue.enqueue(conn, doc_url, "مدونة التشريعات", "section")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    monkeypatch.setattr(crawler, "fetch",
                        lambda url, **kw: {"ok": True, "status": 200,
                                           "html": WP_POST, "ms": 1,
                                           "final_url": url,
                                           "encoding": "utf-8"})
    crawler.start_crawling(max_pages=1)

    n_docs = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    n_arts = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    assert n_docs == 1
    assert n_arts >= AUTO_APPROVE_MIN_ARTICLES
    row = conn.execute("SELECT status FROM crawl_tasks WHERE url = ?",
                       (doc_url,)).fetchone()
    assert row["status"] == "success"
    conn.close()


def test_handle_topic_rejects_page_without_articles(tmp_path, monkeypatch):
    """بوابة الجودة الدنيا: صفحة «قانونية» بلا مواد مستخرجة ← needs_review."""
    import crawler
    conn = _tmp_db(tmp_path, monkeypatch)
    # نص قانوني المظهر (عبارة قوية) بلا أي «المادة N» — كالمدونات المتسللة.
    html = ('<html><body><article><div class="entry-content">'
            '<p>القانون رقم 9 لعام 2025 — نص استشاري طويل يتحدث عن '
            'الجرائم المعلوماتية وعقوباتها في التشريعات المقارنة، ويشمل '
            'شرحاً موسعاً لأحكام القضاء وأراء الفقهاء في هذا المجال، مع '
            'أمثلة تطبيقية من الواقع العملي للمحاكم والدوائر القضائية '
            'المختلفة في عدة دول عربية وأجنبية خلال السنوات الماضية.</p>'
            '<p>فقرة إضافية تستكمل الشرح النظري بلا أي بنية مواد تشريعية، '
            'كي يبقى النص فوق حدود الطول الدنيا للمستخرج دون أن يحوي '
            'إشارة مادة واحدة — وهذا هو نمط صفحات المدونات التي تتحدث '
            'عن القانون دون أن تكون نصوصاً تشريعية.</p>'
            '</div></article></body></html>')
    taskqueue.enqueue(conn, "https://blog.example/post1", "مدونة", "topic")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(crawler, "fetch",
                        lambda url, **kw: {"ok": True, "status": 200,
                                           "html": html, "ms": 1,
                                           "final_url": url,
                                           "encoding": "utf-8"})
    crawler.start_crawling(max_pages=1)
    row = conn.execute("SELECT status FROM crawl_tasks WHERE url = ?",
                       ("https://blog.example/post1",)).fetchone()
    assert row["status"] == "needs_review"
    assert conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 0
    conn.close()


def test_prune_corpus_removes_zero_article_and_duplicates(tmp_path,
                                                          monkeypatch):
    from database import prune_corpus
    conn = _tmp_db(tmp_path, monkeypatch)
    cur = conn.cursor()
    # وثيقة سليمة + بلا مواد + تكرار بصمة + تشريع غير سوري متسلل
    docs = [("d1", "shaA", "قانون سوري سليم"),
            ("d2", "shaB", "صفحة بلا مواد"),
            ("d3", "shaA", "تكرار القانون السليم"),
            ("d4", "shaC", "القانون المصري رقم 5 لسنة 2020")]
    for i, (did, sha, title) in enumerate(docs):
        cur.execute("INSERT INTO documents (doc_id, title, source_url, branch,"
                    " branch_confidence, legal_score, content_hash, "
                    "scraped_at, clean_content, content_sha256) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?)",
                    (did, title, f"https://x.example/{i}", "x", 0.9, 90,
                     "h", "2026", "نص", sha))
        rid = cur.lastrowid
        if did != "d2":  # d2 بلا مواد
            cur.execute("INSERT INTO articles (doc_id, article_number, "
                        "article_label, text, paragraphs_json, "
                        "hierarchy_path, char_count) VALUES "
                        f"({rid}, '1', 'م1', 'نص', '[]', '[]', 2)")
    conn.commit()
    stats = prune_corpus(conn)
    assert stats == {"zero_article": 1, "duplicates": 1, "foreign": 1}
    left = [r["doc_id"] for r in conn.execute(
        "SELECT doc_id FROM documents ORDER BY id")]
    assert left == ["d1"]
    conn.close()


def test_migration_adds_decided_by_to_old_schema(tmp_path):
    """قاعدة بمخطط قديم (بلا sources) ← الهجرة 3 تبني الجدول بالعمود."""
    import sqlite3
    from migrations import migrate
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents (id INTEGER PRIMARY KEY, clean_content TEXT,
                                raw_content TEXT);
        CREATE TABLE crawl_log (id INTEGER PRIMARY KEY);
    ''')
    conn.commit()
    conn.close()
    import migrations as _migrations_mod
    report = migrate(str(db))
    assert report["end_version"] == _migrations_mod.LATEST
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sources)")]
    assert "decided_by" in cols
    conn.close()
