# -*- coding: utf-8 -*-
"""اختبارات الطيار الآلي — الزاحف يلاقي مصادره لحالو ويتعامل معها.

محلية بالكامل (بلا شبكة): استخراج روابط حسب المحرك، تنقيب المتن،
قناة الخرائط، بوابة الاعتماد التلقائي، الحلقة الكاملة (تقييم ← اعتماد ←
بذر الطابور)، وزحف قائمة WordPress من طرف لطرف بمسار الزاحف الحقيقي.
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
    def fake_fetch(url, **kw):
        body = ROBOTS if url.endswith("robots.txt") else SITEMAP
        return {"ok": True, "status": 200, "html": body, "ms": 1,
                "final_url": url, "encoding": "utf-8"}
    monkeypatch.setattr(autopilot, "fetch", fake_fetch)
    cands = sitemap_candidates("https://src.example/")
    urls = [c.url for c in cands]
    assert "https://src.example/laws/civil-law" in urls
    assert "https://src.example/qanoon/penal-code" in urls
    assert all("blog/hello" not in u for u in urls)
    assert all(c.via == "sitemap" for c in cands)


# ═════════════════ بوابة الاعتماد التلقائي ═════════════════

def _ev(verdict="recommended", score=80.0, articles=4):
    return Evaluation("https://x.example/", True, "wordpress", True, score,
                      "عنوان", verdict, [], articles)


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


def test_consider_auto_approve_records_decided_by_auto_and_enqueues(
        tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    ev = _ev()
    discovery.register_candidate(conn, ev.url, "test", ev)
    assert consider_auto_approve(conn, ev.url, ev) is True
    row = conn.execute("SELECT status, decided_by FROM sources WHERE "
                       "source_key = ?", (_source_key(ev.url),)).fetchone()
    assert row["status"] == "approved" and row["decided_by"] == "auto"
    assert taskqueue.pending_count(conn) == 1
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
    n = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
    assert n == 1
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
                        lambda c, use_search=True: [
                            Candidate(URL_PASS, "قانون العقوبات", via="corpus"),
                            Candidate(URL_WEAK, "قرار 7", via="corpus"),
                            Candidate(URL_JUNK, "مدونة طبخ", via="search:ddg"),
                        ])
    stats = run_discovery(conn, auto_approve=True, use_search=False)

    assert stats["evaluated"] == 3
    assert stats["approved"] == 1
    assert stats["approved_list"][0]["url"] == URL_PASS
    assert stats["approved_list"][0]["articles"] >= AUTO_APPROVE_MIN_ARTICLES

    strong = conn.execute("SELECT status, decided_by, engine FROM sources "
                          "WHERE base_url = ?", (URL_PASS,)).fetchone()
    assert (strong["status"], strong["decided_by"], strong["engine"]) == \
        ("approved", "auto", "wordpress")

    weak = conn.execute("SELECT status FROM sources WHERE base_url = ?",
                        (URL_WEAK,)).fetchone()
    assert weak["status"] == "proposed"  # اجتاز اليدوي لا الآلي — يبقى مقترحاً

    junk = conn.execute("SELECT status FROM sources WHERE base_url = ?",
                        (URL_JUNK,)).fetchone()
    assert junk["status"] == "rejected"

    # المعتمد وحده بُذر في طابور الزحف (+ المنتدى الأساسي لا يُبذر هنا —
    # البذر في start_crawling):
    queued = [r["url"] for r in conn.execute(
        "SELECT url FROM crawl_tasks WHERE status='queued'")]
    assert URL_PASS in queued and URL_WEAK not in queued
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
