"""ف٣: حزمة الاجتهادات لميزان + الاعتماد الجماعي — بلا شبكة."""
import csv
import json
from pathlib import Path

import config
import database
import pytest
import precedent_export as pe
import precedent_source as ps

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "mohamah_mohamoun_2010.html").read_text(encoding="utf-8")
GA = ("<article><p>نقض سوري هيئة عامة أساس 328 قرار 167 تاريخ 6/11/1994 – المصدر : مجلة المحامون العددان 11 – 12 لعام 1994</p>"
      "<p>إن توقيف المدعى عليه بجرم الشيك بدون رصيد لا يحول دون ملاحقته بالجرم ذاته إذا ثبت تعدد الشيكات .</p>"
      "<p>لذلك تقرر بالاجماع: 1 ـ العدول عن الاجتهاد الوارد في القرار 1904 / 2106 جنحة تاريخ 30 / 6 / 2008 على الوجه المبين في الأسباب.</p></article>")


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    ps.ingest_page(conn, "https://www.mohamah.net/law/x/", PAGE)
    ps.ingest_page(conn, "https://example.org/ga", GA, source_site="example.org")
    yield conn
    conn.close()


def test_default_export_is_approved_only(db, tmp_path):
    m = pe.build_package(db, out_dir=tmp_path / "out")
    assert m["count"] == 0 and (tmp_path / "out" / "manifest.json").exists()


def test_approve_bulk_then_export(db, tmp_path):
    dry = pe.approve_bulk(db, min_confidence=0.85, dry_run=True)
    assert dry["matched"] >= 19 and dry["approved"] == 0
    assert db.execute("SELECT count(*) FROM decisions WHERE review_status='approved'").fetchone()[0] == 0
    r = pe.approve_bulk(db, min_confidence=0.85)
    assert r["approved"] == dry["matched"]
    m = pe.build_package(db, out_dir=tmp_path / "out")
    assert m["count"] == m["approved"] >= 19 and m["pending"] == 0
    data = json.loads((tmp_path / "out" / "precedents.json").read_text(encoding="utf-8"))
    item = next(i for i in data["items"] if i["identity_key"] == "نقض|1904|2008|2106")
    assert item["court_display"] == "محكمة النقض — الغرفة الجنحية" or item["court_display"] == "محكمة النقض"
    assert item["reference"] == "قرار 1904 أساس 2106 تاريخ 30/6/2008"
    assert item["source_line"] == "مجلة المحامون 2010 العدد 1-2 القاعدة 52"
    assert item["overruled"] is True and item["relations"][0]["relation"] == "عدول"
    with open(tmp_path / "out" / "precedents.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows and set(rows[0]) == set(pe.CSV_COLUMNS)
    row = next(r for r in rows if r["identity_key"] == "نقض|1904|2008|2106")
    assert row["overruled"] == "1" and row["principle"].startswith("الأقوال المتناقضة")
    # الهيئة العامة أولاً (مرتبة الإلزام 1)
    assert data["items"][0]["court"] == "هيئة_عامة_نقض"
    assert m["files"]["precedents.csv"] and m["by_court"]["نقض"] >= 18


def test_multi_source_filter_and_include_pending(db, tmp_path):
    r = pe.approve_bulk(db, min_confidence=0.5, multi_source_only=True)
    assert r["approved"] == 0                      # لا قرار ورد في مصدرين هنا
    m = pe.build_package(db, out_dir=tmp_path / "out", include_pending=True)
    assert m["pending"] == m["count"] >= 20 and m["approved"] == 0
    row = json.loads((tmp_path / "out" / "precedents.json").read_text(encoding="utf-8"))["items"][0]
    assert row["review_status"] == "pending"
