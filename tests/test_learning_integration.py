# -*- coding: utf-8 -*-
"""اختبار تكاملي: دورة زحف فعلية عبر crawler.start_crawling تُحدّث فعلاً
جدول source_performance — لا فقط بمعزل عبر استدعاء learning مباشرة.
"""
import crawl_queue as taskqueue
import crawler
import database


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "learn_it.db"))
    database.create_tables()
    return database.get_connection()


def _law_html(number, year):
    arts = "".join(
        f"<p>المادة {i}- نص المادة رقم {i} من هذا القانون التجريبي بتفاصيل "
        f"كافية لاجتياز بوابة الجودة وطول النص الأدنى المطلوب للاستخراج.</p>"
        for i in range(1, 4))
    return (f"<html><body><article><div class='entry-content'>"
            f"<h1>القانون رقم {number} لعام {year}</h1>{arts}"
            f"</div></article></body></html>")


def test_crawl_run_records_branch_breakdown(tmp_path, monkeypatch):
    """§7.2: تقرير الدورة يحوي فرزاً فعلياً للوثائق الجديدة حسب الفرع —
    لا رقماً إجمالياً مبهماً فقط."""
    import json
    import discovery
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://forum.example/t1", "قسم", "topic")

    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    # نص فيه إشارات قوية لكلمات الفرع الجزائي (عقوبات) لضمان تصنيف واضح
    html = ("<html><body><article><div class='entry-content'>"
           "<h1>قانون العقوبات رقم 60 لعام 2017</h1>"
           "<p>المادة 1- كل من ارتكب جريمة يعاقب بعقوبة جزائية رادعة "
           "وفق نصوص هذا القانون الجزائي، وتُراعى في تقدير العقوبة "
           "ظروف الجريمة المشددة أو المخففة حسب الأصول المرعية.</p>"
           "<p>المادة 2- تُطبَّق العقوبات الجزائية على كل جناية أو جنحة "
           "منصوص عليها في هذا القانون، ولا عقوبة إلا بنص صريح يحدد "
           "أركان الجريمة وعقوبتها المقررة قانوناً.</p>"
           "<p>المادة 3- تحدد المحكمة المختصة العقوبة الجزائية المناسبة "
           "لكل جريمة أو جناية تُرتكب، مع مراعاة سوابق المحكوم عليه "
           "وظروف ارتكاب الجريمة الجزائية موضوع الدعوى.</p>"
           "</div></article></body></html>")
    monkeypatch.setattr(
        crawler, "fetch",
        lambda url, **kw: {"ok": True, "status": 200, "html": html,
                           "ms": 1, "final_url": url, "encoding": "utf-8"})

    crawler.start_crawling(max_pages=1)

    row = conn.execute(
        "SELECT branch_breakdown_json FROM crawl_runs ORDER BY id DESC "
        "LIMIT 1").fetchone()
    assert row["branch_breakdown_json"] is not None
    breakdown = json.loads(row["branch_breakdown_json"])
    assert breakdown  # غير فارغ — وثيقة واحدة على الأقل صُنِّفت
    assert sum(breakdown.values()) == 1
    conn.close()


def test_crawl_run_updates_source_performance(tmp_path, monkeypatch):
    import discovery
    conn = _tmp_db(tmp_path, monkeypatch)
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name, status) "
        "VALUES ('sk1', 'https://forum.example/', 'منتدى تجريبي', 'approved')")
    conn.commit()
    taskqueue.enqueue(conn, "https://forum.example/t1", "قسم", "topic")

    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(discovery, "approved_sources", lambda c: [])
    monkeypatch.setattr(
        crawler, "fetch",
        lambda url, **kw: {"ok": True, "status": 200,
                           "html": _law_html(55, 2018), "ms": 1,
                           "final_url": url, "encoding": "utf-8"})

    crawler.start_crawling(max_pages=1)

    row = conn.execute(
        "SELECT new_identities_total, learned_status FROM source_performance "
        "WHERE source_key = 'sk1'").fetchone()
    assert row is not None
    assert row["new_identities_total"] == 1
    assert row["learned_status"] == "active"
    conn.close()
