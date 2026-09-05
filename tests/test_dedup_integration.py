# -*- coding: utf-8 -*-
"""اختبار تكاملي: نفس القانون من مصدرين مختلفي الرسمية عبر دورة زحف كاملة
(crawler.start_crawling) — يتحقق أن منطق dedup/law_identity/source_quality
يعمل فعلياً من طرف لطرف، لا فقط بمعزل بوحدات الاختبار المنفردة.

DELIVERY/DESIGN-SELF-DISCOVERY.md §4: المصدر الرسمي يفوز حتى لو وصل
لاحقاً (لا يعتمد الترتيب الزمني فقط)، والنسخة الخاسرة تُؤرشف لا تُحذف.
"""
import crawl_queue as taskqueue
import crawler
import database


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "dedup_it.db"))
    database.create_tables()
    return database.get_connection()


def _law_html(title, n_articles=5):
    arts = "".join(f"<p>المادة {i}- نص المادة رقم {i} من هذا القانون "
                   f"التجريبي بتفاصيل كافية لاجتياز بوابة الجودة.</p>"
                   for i in range(1, n_articles + 1))
    return (f"<html><body><article><div class='entry-content'>"
            f"<h1>{title}</h1>{arts}</div></article></body></html>")


FORUM_HTML = _law_html("القانون رقم 77 لعام 2019 بشأن اختبار التكرار")
OFFICIAL_HTML = _law_html("القانون رقم 77 لعام 2019 بشأن اختبار التكرار",
                          n_articles=6)  # أشمل قليلاً أيضاً — لا يهم، الفئة تحسم


def _fake_fetch(url, **kw):
    html = OFFICIAL_HTML if "parliament.gov.sy" in url else FORUM_HTML
    return {"ok": True, "status": 200, "html": html, "ms": 1,
            "final_url": url, "encoding": "utf-8"}


def test_forum_then_official_source_official_wins(tmp_path, monkeypatch):
    """المنتدى يصل أولاً (active)، ثم يصل نفس القانون من parliament.gov.sy
    لاحقاً — يجب أن تفوز الرسمية رغم وصولها ثانياً، والمنتدى يُؤرشف."""
    import discovery
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://forum.example/t1", "قسم", "topic")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    monkeypatch.setattr(crawler, "fetch", _fake_fetch)

    crawler.start_crawling(max_pages=1)
    row1 = conn.execute(
        "SELECT id, status, source_domain_tier FROM documents").fetchone()
    assert row1["status"] == "active"
    assert row1["source_domain_tier"] == 4  # منتدى غير مُدرَج بالقائمة

    # الآن يصل نفس القانون من مصدر رسمي
    taskqueue.enqueue(conn, "https://parliament.gov.sy/t1", "قسم", "topic")
    crawler.start_crawling(max_pages=1)

    rows = conn.execute(
        "SELECT source_url, status, source_domain_tier FROM documents "
        "ORDER BY id").fetchall()
    assert len(rows) == 2
    forum_row = next(r for r in rows if "forum.example" in r["source_url"])
    official_row = next(r for r in rows
                        if "parliament.gov.sy" in r["source_url"])
    assert forum_row["status"] == "superseded"
    assert official_row["status"] == "active"
    assert official_row["source_domain_tier"] == 1

    # النسخة القديمة أُرشفت (نسخ لا حذف) — سجل تدقيق موجود فعلياً
    versions = conn.execute("SELECT COUNT(*) c FROM document_versions").fetchone()
    assert versions["c"] == 1
    decisions = conn.execute(
        "SELECT decisive_criterion FROM dedup_decisions").fetchone()
    assert decisions["decisive_criterion"] == "domain_tier"
    conn.close()


def test_official_then_forum_source_forum_saved_as_alternate(tmp_path, monkeypatch):
    """الترتيب المعاكس: الرسمية تصل أولاً — وصول المنتدى لاحقاً لا يُسقط
    بصمت؛ يُحفظ كمصدر بديل موثَّق (status='alternate_source')."""
    import discovery
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://parliament.gov.sy/t1", "قسم", "topic")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    monkeypatch.setattr(crawler, "fetch", _fake_fetch)

    crawler.start_crawling(max_pages=1)
    taskqueue.enqueue(conn, "https://forum.example/t1", "قسم", "topic")
    crawler.start_crawling(max_pages=1)

    rows = conn.execute(
        "SELECT source_url, status FROM documents ORDER BY id").fetchall()
    assert len(rows) == 2
    official_row = next(r for r in rows
                        if "parliament.gov.sy" in r["source_url"])
    forum_row = next(r for r in rows if "forum.example" in r["source_url"])
    assert official_row["status"] == "active"
    assert forum_row["status"] == "alternate_source"
    # لا حذف — كلا الصفين موجود فعلياً بجدول documents
    conn.close()


def test_identity_key_populated_for_both(tmp_path, monkeypatch):
    """يتحقق أن identity_key/number/year تُملأ فعلياً — إصلاح الحقول
    الفارغة تاريخياً (§2 من التصميم)."""
    import discovery
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://forum.example/t1", "قسم", "topic")
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    monkeypatch.setattr(crawler, "fetch", _fake_fetch)

    crawler.start_crawling(max_pages=1)
    row = conn.execute(
        "SELECT identity_key, number, year, identity_confidence "
        "FROM documents").fetchone()
    assert row["identity_key"] == "القانون:77:2019"
    assert row["number"] == 77
    assert row["year"] == 2019
    assert row["identity_confidence"] == "number_year"
    conn.close()
