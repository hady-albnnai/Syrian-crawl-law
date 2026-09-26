# -*- coding: utf-8 -*-
"""ذ19: تصدير تعديلات المواد (جدول A-4) لميزان — لا استخراج موازٍ."""
import sqlite3

import article_amendments as aa

AMENDING = """المادة 1- تعدل الفقرة أ من المادة 1 من القانون رقم 6 لعام 2001 لتصبح كما يلي: يخضع لإرادة المتعاقدين.
المادة 2- تلغى المادتان 7 و14 من المرسوم التشريعي رقم 81 لعام 1979.
المادة 3- يلغى القانون رقم 464 لعام 1949."""


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, number INTEGER, year INTEGER, status TEXT, identity_key TEXT, clean_content TEXT, issue_date TEXT, source_url TEXT)")
    c.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, doc_id INTEGER, article_number TEXT, amended_by TEXT, status TEXT)")
    c.execute("INSERT INTO documents VALUES (1, 'القانون رقم 10 لعام 2006', 10, 2006, 'active', 'القانون:10:2006', ?, '2006-02-26', 'https://x/10')", (AMENDING,))
    c.execute("INSERT INTO documents VALUES (2, 'القانون رقم 6 لعام 2001', 6, 2001, 'active', 'القانون:6:2001', 'المادة 1- نص', NULL, 'https://x/6')")
    c.execute("INSERT INTO articles VALUES (1, 2, '1', NULL, 'active')")
    return c


def test_uses_a4_table_and_exports_contract(tmp_path):
    c = _conn()
    st = aa.rebuild(c)
    assert st["links"] == 3 and st["articles_marked"] == 1
    rows = aa.export_rows(c)
    assert {r["target_identity"] for r in rows} == {"القانون:6:2001", "المرسوم التشريعي:81:1979"}
    six = [r for r in rows if r["target_identity"] == "القانون:6:2001"][0]
    assert (six["target_type"], six["target_number"], six["target_year"], six["article"], six["action"]) == ("القانون", "6", "2001", "1", "amend")
    assert six["amending_identity"] == "القانون:10:2006" and six["amending_date"] == "2006-02-26"
    assert "تعدل الفقرة أ من المادة 1" in six["context"]
    rep = aa.export_csv(c, tmp_path / "article_amendments.csv")
    assert rep == {"count": 3, "path": str(tmp_path / "article_amendments.csv"), "repeal": 2, "amend": 1}
    head = (tmp_path / "article_amendments.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert head.split(",") == aa.CSV_COLUMNS


def test_ensure_table_matches_a4_schema_on_fresh_db():
    c = sqlite3.connect(":memory:")
    aa.ensure_table(c)
    cols = [r[1] for r in c.execute("PRAGMA table_info(article_amendments)")]
    assert "article_number" in cols and "article" not in cols
