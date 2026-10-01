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


WP_INDEX = ("<sitemapindex><sitemap><loc>https://arch.example/wp-sitemap-posts-post-1.xml</loc></sitemap>"
            "</sitemapindex>")
WP_MAP = ("<urlset>"
          "<url><loc>https://arch.example/%d9%85%d8%b1%d8%b3%d9%88%d9%85-%d8%aa%d8%b4%d8%b1%d9%8a%d8%b9%d9%8a-1/</loc>"
          "<lastmod>2014-06-10T05:03:37+03:00</lastmod></url>"
          "<url><loc>https://arch.example/%d9%85%d8%b1%d8%b3%d9%88%d9%85-%d8%aa%d8%b4%d8%b1%d9%8a%d8%b9%d9%8a-2/</loc>"
          "<lastmod>2020-01-01T00:00:00+03:00</lastmod></url>"
          "<url><loc>https://arch.example/%d9%83%d8%b1%d8%a9-%d8%a7%d9%84%d9%82%d8%af%d9%85/</loc>"
          "<lastmod>2021-01-01T00:00:00+03:00</lastmod></url></urlset>")


def _wp_get(url):
    if url.endswith("/sitemap_index.xml"):
        return 404, "<html>not found</html>"
    return 200, {"https://arch.example/wp-sitemap.xml": WP_INDEX,
                 "https://arch.example/wp-sitemap-posts-post-1.xml": WP_MAP}[url]


def test_falls_back_to_wp_sitemap_and_filters_by_decoded_slug_newest_first():
    urls = sitemap_seed.collect_urls("https://arch.example/", "/", http_get=_wp_get, url_match="مرسوم|قانون")
    assert len(urls) == 2 and urls[0].endswith("-2/") and urls[1].endswith("-1/")   # بحسب lastmod
    everything = sitemap_seed.collect_urls("https://arch.example/", "/", http_get=_wp_get)
    assert len(everything) == 3                                                     # بلا فلتر


def test_no_index_anywhere_seeds_nothing():
    assert sitemap_seed.collect_urls("https://arch.example/", "/",
                                     http_get=lambda u: (404, "")) == []
