"""بذر sitemap بمسار محدد — دون شبكة."""
import database
import sitemap_seed

INDEX = ("<sitemapindex><sitemap><loc>https://news.example/post-sitemap1.xml</loc></sitemap>"
         "<sitemap><loc>https://news.example/post-sitemap2.xml</loc></sitemap></sitemapindex>")
MAP1 = ("<urlset><url><loc>https://news.example/presidency/</loc></url>"
        "<url><loc>https://news.example/presidency/100/</loc></url>"
        "<url><loc>https://news.example/economy/101/</loc></url>"
        "<url><loc>https://other.example/presidency/5/</loc></url></urlset>")
MAP2 = ("<urlset><url><loc>https://news.example/presidency/300/</loc></url>"
        "<url><loc>https://news.example/presidency/100/</loc></url></urlset>")


def _get(url):
    return 200, {"https://news.example/sitemap_index.xml": INDEX,
                 "https://news.example/post-sitemap1.xml": MAP1,
                 "https://news.example/post-sitemap2.xml": MAP2}[url]


def test_collect_filters_by_path_dedups_and_sorts_newest_first():
    urls = sitemap_seed.collect_urls("https://news.example/presidency", "/presidency/", http_get=_get)
    assert urls == ["https://news.example/presidency/300/", "https://news.example/presidency/100/"]


def test_seed_enqueues_only_for_approved_source(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "m.db"))
    database.create_tables()
    conn = database.get_connection()
    rep = sitemap_seed.seed_from_sitemap(conn, "https://news.example/presidency", "/presidency/",
                                         "قسم", http_get=_get)
    assert rep["added"] == 0 and rep["unapproved"] == 2     # لا مصدر معتمد
    conn.execute("INSERT INTO sources (source_key, base_url, name, engine, credibility, status,"
                 " discovered_via, discovered_at) VALUES ('k','https://news.example/presidency',"
                 "'n','unknown',0.6,'approved','x','2026-01-01')")
    conn.commit()
    rep = sitemap_seed.seed_from_sitemap(conn, "https://news.example/presidency", "/presidency/",
                                         "قسم", limit=1, http_get=_get)
    assert rep["found"] == 1 and rep["added"] == 1
    assert conn.execute("SELECT url FROM crawl_tasks").fetchone()[0].endswith("/presidency/300")
    dry = sitemap_seed.seed_from_sitemap(conn, "https://news.example/presidency", "/presidency/",
                                         "قسم", dry_run=True, http_get=_get)
    assert dry["added"] == 0


def test_failing_sitemap_does_not_abort_seeding():
    def flaky(url):
        if url.endswith("post-sitemap1.xml"):
            raise RuntimeError("boom")
        return _get(url)
    urls = sitemap_seed.collect_urls("https://news.example/presidency", "/presidency/", http_get=flaky)
    assert urls == ["https://news.example/presidency/300/", "https://news.example/presidency/100/"]
