# -*- coding: utf-8 -*-
"""اختبارات wayback_source + wayback-crawl — محلية بالكامل بلا شبكة
(§8.8: لا اختبارات على مزود حي؛ الأرشيف كان مطفأ وقت البناء أصلاً)."""
import json

import pytest

import wayback_source as wb

ORIG = "http://parliament.gov.sy/laws/Law/1950/essential_04.htm"


def _http(url):
    """CDX بلقطات + لقطة خام — محقون بالكامل."""
    if wb.CDX_BASE in url:
        rows = [["timestamp", "statuscode"],
                ["20200101120000", "200"],
                ["20230615203000", "200"]]
        return 200, json.dumps(rows)
    if "id_/" in url:
        assert "20230615203000" in url   # أحدث لقطة + لاحقة الخام id_
        return 200, "<html><body>المادة 1 نص قانوني " + "طويل " * 200 + \
               "</body></html>"
    raise AssertionError("طلب غير متوقع: " + url)


# ── المستخرج ──
def test_cdx_snapshots_parses_and_filters():
    snaps = wb.cdx_snapshots(ORIG, http_get=_http)
    assert snaps == [("20200101120000", "200"), ("20230615203000", "200")]
    assert wb.latest_good_snapshot(ORIG, http_get=_http) == "20230615203000"


def test_as_pipeline_result_ok_uses_newest_raw_snapshot():
    r = wb.as_pipeline_result(ORIG, http_get=_http)
    assert r["ok"] is True
    assert r["final_url"] == ORIG    # الأصل نفسه — doc_id مستقر للترقية
    assert "المادة 1" in r["html"]


def test_as_pipeline_result_error_codes():
    # لا لقطات
    r = wb.as_pipeline_result(ORIG, http_get=lambda u: (
        200, json.dumps([["timestamp", "statuscode"]])
        if wb.CDX_BASE in u else (200, "x")))
    assert r == {"ok": False, "error": "wayback_no_snapshot"}
    # حجب robots
    r2 = wb.as_pipeline_result(ORIG, http_get=lambda u: (None, ""))
    assert r2 == {"ok": False, "error": "wayback_blocked_robots"}
    # فشل جلب اللقطة
    def _cdx_ok_snap_fail(url):
        if wb.CDX_BASE in url:
            return 200, json.dumps([["t", "s"], ["20230101000000", "200"]])
        return 504, ""
    r3 = wb.as_pipeline_result(ORIG, http_get=_cdx_ok_snap_fail)
    assert r3 == {"ok": False, "error": "wayback_fetch_504"}


# ── wayback-crawl: الترقية في المكان (جوهر قرار «ج») ──
_LAW_PAGE = ("<html><head><title>قانون أصول المحاكمات الجزائية</title>"
             "</head><body><article><div class='entry-content'>"
             + "".join(f"<p>المادة {i} — تنظر المحاكم الجزائية بالجرائم "
                       f"المعاقب عنها وتفصل فيها وفق أحكام هذا القانون "
                       f"وأحكام قانون العقوبات.</p>" for i in range(1, 9))
             + "</div></article></body></html>")


def test_wayback_crawl_upgrades_adopted_row_in_place(tmp_path, monkeypatch):
    """الصف المتبنّى من HF (تير 3، نفس doc_id للرابط الأصلي) يُرقّى في
    مكانه إلى الأصل المؤرشف (تير 1) — ♻️ استُبدلت بنسخة أفضل + أرشفة."""
    import database
    import hf_syria_laws
    import crawler

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "w.db"))
    database.create_tables()
    conn = database.get_connection()

    monkeypatch.setattr(
        hf_syria_laws, "load_laws_with_articles",
        lambda *a, **k: [({"id": "x", "title": "قانون تجريبي",
                           "source_url": ORIG}, [])])
    monkeypatch.setattr(
        wb, "as_pipeline_result",
        lambda u: {"ok": True, "html": _LAW_PAGE, "final_url": u,
                   "status": 200, "encoding": "utf-8"})

    # الصف المتبنّى الموجود: نفس doc_id (الرابط الأصلي)، تير 3، محتوى أدنى
    doc_id = crawler.make_doc_id(ORIG)
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "content_hash, source_domain_tier, quality_score, status) "
        "VALUES (?, 'متبنى HF', ?, 'نص قديم أدنى', 'oldhash', 3, 0.5, "
        "'active')", (doc_id, ORIG))
    conn.commit()

    from cli import cmd_wayback_crawl

    class _Args:
        limit = None
        dry = False

    assert cmd_wayback_crawl(_Args()) == 0

    rows = conn.execute("SELECT source_domain_tier, status FROM documents"
                        ).fetchall()
    assert len(rows) == 1                    # نفس الصف — ترقية في المكان
    assert rows[0]["source_domain_tier"] == 1  # تير الأصل الرسمي
    assert rows[0]["status"] == "active"
    assert conn.execute("SELECT COUNT(*) c FROM document_versions"
                        ).fetchone()["c"] == 1   # القديم مؤرشف نسخاً
    assert conn.execute("SELECT COUNT(*) c FROM articles"
                        ).fetchone()["c"] >= 5
    conn.close()


def test_wayback_crawl_skips_pdf_and_counts(tmp_path, monkeypatch):
    """روابط PDF مؤجلة، ولا لقطات تُحصى ولا تنفجر الدورة."""
    import database
    import hf_syria_laws

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "w2.db"))
    database.create_tables()
    conn = database.get_connection()
    monkeypatch.setattr(
        hf_syria_laws, "load_laws_with_articles",
        lambda *a, **k: [
            ({"id": "p", "title": "pdf", "source_url":
              "http://jus.moj.gov.sy/sites/default/files/x.pdf"}, []),
            ({"id": "h", "title": "htm", "source_url": ORIG}, [])])
    calls = []

    def _fake(u):
        calls.append(u)
        return {"ok": False, "error": "wayback_no_snapshot"}

    monkeypatch.setattr(wb, "as_pipeline_result", _fake)
    from cli import cmd_wayback_crawl

    class _Args:
        limit = None
        dry = False

    assert cmd_wayback_crawl(_Args()) == 0
    assert calls == [ORIG]                  # الـPDF لم يُطلب أصلاً
    conn.close()


def test_archive_offline_page_detected_honestly():
    """صفحة انقطاع الأرشيف (تعود 200!) تُميَّز برمزها — لا تُجلب
    كأنها أصل ثم تفشل استخراجاً بتشخيص مضلل (قِيس 2026-09-17)."""
    def _offline(url):
        if wb.CDX_BASE in url:
            return 200, json.dumps([["t", "s"], ["20230101000000", "200"]])
        return 200, ("<html><head><title>Internet Archive: Temporarily "
                     "Offline</title></head><body>Temporarily Offline "
                     + "padding " * 100 + "</body></html>")
    r = wb.as_pipeline_result(ORIG, http_get=_offline)
    assert r == {"ok": False, "error": "wayback_temporarily_offline"}
