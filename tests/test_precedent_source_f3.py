"""ف٣: محرك mohamah.net — بلا شبكة (خرائط مزيفة + صفحة حقيقية محفوظة)."""
from pathlib import Path

import config
import database
import pytest
import precedent_source as ps

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


PAGE_URL = ("https://www.mohamah.net/law/%D8%A7%D8%AC%D8%AA%D9%87%D8%A7%D8%AF%D8%A7%D8%AA-%D9%82%D8%B6%D8%A7%D8%A6%D9%8A%D8%A9-"
            "%D9%84%D9%85%D8%AD%D9%83%D9%85%D8%A9-%D8%A7%D9%84%D9%86%D9%82%D8%B6-%D8%A7%D9%84%D8%B3%D9%88%D8%B1%D9%8A%D8%A9/")
IDX = '<sitemapindex><sitemap><loc>https://www.mohamah.net/law/post-sitemap1.xml</loc></sitemap><sitemap><loc>https://www.mohamah.net/law/page-sitemap.xml</loc></sitemap></sitemapindex>'
SM1 = ('<urlset><url><loc>' + PAGE_URL + '</loc></url>'
       '<url><loc>https://www.mohamah.net/law/نصوص-و-مواد-قانون-العقوبات-السوري/</loc></url>'
       '<url><loc>https://www.mohamah.net/law/اجتهادات-محكمة-النقض-المصرية-حول-الشيك/</loc></url>'
       '<url><loc>https://www.mohamah.net/law/بحث-في-عقد-البيع/</loc></url></urlset>')
PAGE_HTML = (FIX / "mohamah_mohamoun_2010.html").read_text(encoding="utf-8")


def fake_get(url):
    return {ps.MOHAMAH_SITEMAP_INDEX: IDX,
            "https://www.mohamah.net/law/post-sitemap1.xml": SM1,
            PAGE_URL: PAGE_HTML}.get(url)


def test_url_filter_syrian_precedent_only():
    urls = ps.sitemap_precedent_urls(IDX, fake_get)
    assert urls == [PAGE_URL]          # الأخرى: تشريع / مصري / بحث


def test_article_text_keeps_line_structure():
    t = ps.article_text(PAGE_HTML)
    assert "القاعدة: 52" in t and "المبدأ: بينات" in t
    assert "شارك المقالة" not in t


def test_ingest_real_page_writes_pending_rows(db):
    st = ps.ingest_page(db, PAGE_URL, PAGE_HTML)
    assert st["citations"] >= 19 and st["new_decisions"] >= 19 and st["new_principles"] >= 19
    row = db.execute("SELECT court, decision_number, decision_year, basis_number, basis_year, decision_date, review_status, authority_rank"
                     " FROM decisions WHERE identity_key='نقض|1904|2008|2106'").fetchone()
    assert tuple(row) == ("نقض", "1904", 2008, "2106", 2008, "2008-06-30", "pending", 3)
    p = db.execute("SELECT title_keywords, text FROM principles p JOIN decisions d ON d.id=p.decision_id WHERE d.identity_key='نقض|1904|2008|2106'").fetchone()
    assert p[0].startswith("بينات – شهادة") and p[1].startswith("الأقوال المتناقضة")
    c = db.execute("SELECT publication, pub_year, pub_issue, rule_number, source_site FROM citations WHERE decision_id=(SELECT id FROM decisions WHERE identity_key='نقض|1904|2008|2106')").fetchone()
    assert tuple(c) == ("المحامون", 2010, "1-2", "52", "mohamah.net")


def test_reingest_same_page_is_idempotent(db):
    a = ps.ingest_page(db, PAGE_URL, PAGE_HTML)
    b = ps.ingest_page(db, PAGE_URL, PAGE_HTML)
    assert b["new_decisions"] == 0 and b["new_principles"] == 0
    s = ps.stats(db)
    assert s["decisions"] == a["new_decisions"] and s["citations"] == a["written"]
    assert s["pending"] == s["decisions"] and s["approved"] == 0


def test_second_source_same_decision_adds_citation_not_decision(db):
    ps.ingest_page(db, PAGE_URL, PAGE_HTML)
    other = "https://example.org/x"
    html = "<article><p>الأقوال المتناقضة للشاهد يجب أن تخضع إلى المناقشة والتمحيص من لدن المحكمة .</p>" \
           "<p>(نقض سوري – الغرفة الجنحية – قرار 1904 – أساس 2106 – تاريخ 30/6/2008 – سجلات محكمة النقض)</p></article>"
    st = ps.ingest_page(db, other, html, source_site="example.org")
    assert st["new_decisions"] == 0 and st["new_principles"] == 0 and st["written"] == 1
    s = ps.stats(db)
    assert s["multi_source"] == 1
    # الغرفة أُكملت من المصدر الثاني (كانت فارغة في المحامون)
    r = db.execute("SELECT chamber_raw, division FROM decisions WHERE identity_key='نقض|1904|2008|2106'").fetchone()
    assert tuple(r) == ("الجنحية", "جزائية")


def test_unsourced_is_counted_not_written(db):
    html = "<article><p>مبدأ منقول بلا رقم: الشك يفسر لمصلحة المتهم كما استقر عليه الاجتهاد.</p><p>(نقض سوري – الغرفة الجنحية – سجلات محكمة النقض)</p></article>"
    st = ps.ingest_page(db, "https://example.org/u", html)
    assert st["written"] == 0 and ps.stats(db)["decisions"] == 0


def test_harvest_end_to_end_dry_then_write(db):
    rep = ps.harvest_mohamah(db, fake_get, dry_run=True)
    assert rep["candidate_urls"] == 1 and rep["fetched"] == 1 and rep["citations"] >= 19
    assert ps.stats(db)["decisions"] == 0
    rep = ps.harvest_mohamah(db, fake_get)
    assert rep["new_decisions"] >= 19
    rep2 = ps.harvest_mohamah(db, fake_get)
    assert rep2["skipped_done"] == 1 and rep2["fetched"] == 0
