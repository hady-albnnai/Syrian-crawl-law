# -*- coding: utf-8 -*-
"""اختبارات official_seed — بذّار المصدر الرسمي (ف١). محلية بلا شبكة:
فهرس sitemap زائف يُحقن مكان الجلب الحقيقي."""
import official_seed as oseed


_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<loc>https://moj.gov.sy/wp-sitemap-posts-decision-1.xml</loc>
<loc>https://moj.gov.sy/wp-sitemap-posts-circular-1.xml</loc>
<loc>https://moj.gov.sy/wp-sitemap-posts-post-1.xml</loc>
<loc>https://moj.gov.sy/wp-sitemap-pages-1.xml</loc>
</sitemapindex>"""

_DECISIONS = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<loc>https://moj.gov.sy/decision/349/</loc>
<loc>https://moj.gov.sy/decision/2639/</loc>
</urlset>"""

_CIRCULARS = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<loc>https://moj.gov.sy/circular/no3/</loc>
</urlset>"""


def _fake_get(url):
    if url.endswith("wp-sitemap.xml"):
        return 200, _INDEX
    if "posts-decision-1" in url:
        return 200, _DECISIONS
    if "posts-circular-1" in url:
        return 200, _CIRCULARS
    return 404, ""


def test_fetch_post_urls_only_legal_types():
    pairs = oseed.fetch_post_urls(
        base_url="https://moj.gov.sy/",
        post_types={"decision": "قرارات", "circular": "تعاميم"},
        http_get=_fake_get)
    urls = {u for u, _ in pairs}
    # أنواع غير قانونية (post/page) تُتجاهل
    assert urls == {"https://moj.gov.sy/decision/349/",
                    "https://moj.gov.sy/decision/2639/",
                    "https://moj.gov.sy/circular/no3/"}
    sections = {s for _, s in pairs}
    assert sections == {"قرارات", "تعاميم"}


def test_sitemap_unreachable_returns_empty():
    assert oseed.fetch_post_urls(
        http_get=lambda url: (500, "")) == []


def test_seed_moj_enqueues_idempotent(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH",
                        str(tmp_path / "seed.db"))
    database.create_tables()
    conn = database.get_connection()

    first = oseed.seed_moj(conn, http_get=_fake_get,
                           post_types={"decision": "قرارات", "circular": "تعاميم"})
    assert first["found"] == 3
    assert first["added"] == 3 and first["skipped"] == 0

    second = oseed.seed_moj(conn, http_get=_fake_get,
                            post_types={"decision": "قرارات", "circular": "تعاميم"})
    assert second["added"] == 0 and second["skipped"] == 3

    kind = conn.execute(
        "SELECT kind, section FROM crawl_tasks LIMIT 1").fetchone()
    assert kind["kind"] == "topic"
    assert kind["section"] in ("قرارات", "تعاميم")


def test_seed_moj_dry_run_does_not_enqueue(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH",
                        str(tmp_path / "seed_dry.db"))
    database.create_tables()
    conn = database.get_connection()
    stats = oseed.seed_moj(conn, http_get=_fake_get, dry_run=True)
    assert stats["found"] == 3 and stats["added"] == 0
    n = conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0]
    assert n == 0


# ── بذر ويبو: فهرس عضوية سوريا الحي + مثبتات الاحتياط (ف٢) ──
_WIPO_PROFILE_HTML = """
<a href="/wipolex/ar/legislation/details/10918">القانون الجنائي</a>
<a href="/wipolex/ar/legislation/details/10917">القانون المدني</a>
<a href="/wipolex/ar/main/legislation">تصفح</a>
"""


def _wipo_db(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "w.db"))
    database.create_tables()
    return database.get_connection()


def test_seed_wipo_index_enqueues_pins_and_links(tmp_path, monkeypatch):
    """الفهرس الحي يُقرأ وروابطه تُبذر topic — المثبت أولاً ثم الفهرس،
    والتكرار (10918 بالمثبت وبالفهرس) يُتخطى."""
    import crawl_queue as taskqueue
    from official_seed import seed_wipo
    conn = _wipo_db(tmp_path, monkeypatch)
    stats = seed_wipo(conn, http_get=lambda u: (200, _WIPO_PROFILE_HTML))
    assert stats["pins"] == 1 and stats["index_found"] == 2
    assert stats["added"] == 2 and stats["skipped"] == 1  # 10918 مكررة
    rows = conn.execute(
        "SELECT url, kind, status FROM crawl_tasks ORDER BY id").fetchall()
    assert len(rows) == 2 and all(r["kind"] == "topic" for r in rows)
    # idempotent: بذر ثانٍ لا يضيف شيئاً
    stats2 = seed_wipo(conn, http_get=lambda u: (200, _WIPO_PROFILE_HTML))
    assert stats2["added"] == 0 and stats2["skipped"] == 3
    conn.close()


def test_seed_wipo_index_unreachable_falls_back_to_pins(tmp_path,
                                                          monkeypatch):
    """تعذّر الفهرس ← المثبتات وحدها — البذر لا يفشل كلياً."""
    from official_seed import seed_wipo
    conn = _wipo_db(tmp_path, monkeypatch)
    stats = seed_wipo(conn, http_get=lambda u: (503, ""))
    assert stats["index_found"] == 0
    assert stats["added"] == 1  # مثبت العقوبات وحده
    conn.close()


def test_seed_wipo_dry_run_does_not_enqueue(tmp_path, monkeypatch):
    from official_seed import seed_wipo
    conn = _wipo_db(tmp_path, monkeypatch)
    stats = seed_wipo(conn, http_get=lambda u: (200, _WIPO_PROFILE_HTML),
                      dry_run=True)
    n = conn.execute("SELECT COUNT(*) c FROM crawl_tasks").fetchone()["c"]
    assert n == 0 and stats["added"] == 0
    conn.close()
