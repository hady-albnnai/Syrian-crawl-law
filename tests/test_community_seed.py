# -*- coding: utf-8 -*-
"""اختبارات community_seed — بذّار syria-law.com (ف٢-ج). محلية بلا شبكة."""
import database
import community_seed as cs


_INDEX = """<?xml version="1.0"?>
<sitemapindex>
  <loc>https://syria-law.com/laws-sitemap1.xml</loc>
  <loc>https://syria-law.com/laws-sitemap2.xml</loc>
  <loc>https://syria-law.com/splaws-sitemap1.xml</loc>
  <loc>https://syria-law.com/ijtihadat-sitemap1.xml</loc>
  <loc>https://syria-law.com/page-sitemap.xml</loc>
</sitemapindex>
"""
_LAWS1 = """<?xml version="1.0"?>
<urlset>
  <loc>https://syria-law.com/laws/%d9%85%d8%b1%d8%b3%d9%88%d9%85-1992/</loc>
  <loc>https://syria-law.com/laws/another-law/</loc>
  <loc>https://syria-law.com/author/admin/</loc>
  <loc>https://syria-law.com/laws/%d9%85%d8%a7%d8%af%d8%a9-166-%d9%85%d9%86-%d9%82%d8%a7%d9%86%d9%88%d9%86/</loc>
  <loc>https://syria-law.com/laws/مادة-12-من-قانون-العقوبات/</loc>
  <loc>https://syria-law.com/laws/%d8%a7%d9%84%d9%85%d8%a7%d8%af%d8%a9-5-%d9%85%d9%86/</loc>
</urlset>
"""
_LAWS2 = """<?xml version="1.0"?>
<urlset>
  <loc>https://syria-law.com/laws/second-map-law/</loc>
</urlset>
"""
_SPLAWS1 = """<?xml version="1.0"?>
<urlset>
  <loc>https://syria-law.com/splaws/some-law/</loc>
</urlset>
"""
_IJ = """<?xml version="1.0"?>
<urlset>
  <loc>https://syria-law.com/ijtihadat/encyc-entry-1/</loc>
  <loc>https://syria-law.com/ijtihadat/encyc-entry-2/</loc>
</urlset>
"""


def _http(url):
    if url.endswith("sitemap_index.xml"):
        return 200, _INDEX
    if "splaws-sitemap" in url:      # قبل laws — سلسلة splaws تحويها
        return 200, _SPLAWS1
    if url.endswith("laws-sitemap2.xml"):
        return 200, _LAWS2
    if "laws-sitemap" in url:
        return 200, _LAWS1
    if "ijtihadat-sitemap" in url:
        return 200, _IJ
    return 404, ""


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "c.db"))
    database.create_tables()
    return database.get_connection()


def test_fetch_law_urls_only_law_sitemaps_and_pages():
    """خرائط القوانين وحدها تُقرأ، وصفحاتها فقط تُلتقط — الموسوعة
    (ijtihadat) والصفحات العامة ومؤلفو ووردبريس تُهمل أدباً."""
    pairs = cs.fetch_law_urls(http_get=_http)
    urls = [u for u, _ in pairs]
    # مقتطفات «مادة-…» (م Encoded وعادي) تُرشَّح من البذر ذاته — أدباً
    assert urls == ["https://syria-law.com/laws/%d9%85%d8%b1%d8%b3%d9%88%d9%85-1992/",
                    "https://syria-law.com/laws/another-law/",
                    "https://syria-law.com/laws/second-map-law/",
                    "https://syria-law.com/splaws/some-law/"]
    assert all(s == cs.SECTION for _, s in pairs)


def test_seed_syria_law_enqueues_idempotent(tmp_path, monkeypatch):
    import crawl_queue as taskqueue
    conn = _db(tmp_path, monkeypatch)
    rep = cs.seed_syria_law(conn, http_get=_http)
    assert rep["found"] == 4 and rep["added"] == 4
    rows = conn.execute("SELECT url, kind FROM crawl_tasks").fetchall()
    assert len(rows) == 4 and all(r["kind"] == "topic" for r in rows)
    rep2 = cs.seed_syria_law(conn, http_get=_http)
    assert rep2["added"] == 0 and rep2["skipped"] == 4
    n = conn.execute("SELECT COUNT(*) c FROM crawl_tasks").fetchone()["c"]
    assert n == 4
    conn.close()


def test_seed_dry_run_and_unreachable(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    rep = cs.seed_syria_law(conn, http_get=_http, dry_run=True)
    n = conn.execute("SELECT COUNT(*) c FROM crawl_tasks").fetchone()["c"]
    assert n == 0 and rep["added"] == 0
    # فهرس ميت — خلاصة فارغة بلا انفجار
    rep2 = cs.seed_syria_law(conn, http_get=lambda u: (503, ""))
    assert rep2["found"] == 0
    conn.close()
