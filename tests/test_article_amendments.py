# -*- coding: utf-8 -*-
"""ذ19: تعديلات المواد بعينها — استخراج حتمي، تسجيل، تصدير."""
import sqlite3

import article_amendments as aa

AMENDING = """المادة 1- تعدل الفقرة أ من المادة 1 من القانون رقم 6 لعام 2001 لتصبح كما يلي: يخضع لإرادة المتعاقدين.
المادة 2- تلغى المادتان 7 و14 من المرسوم التشريعي رقم 81 لعام 1979.
المادة 3- يضاف إلى المادة 3 من القانون رقم 28 لعام 2001 فقرة جديدة.
المادة 4- تلغى المواد من 5 إلى 8 من القانون رقم 20 لعام 2015 وتعدل المادة الثالثة من المرسوم التشريعي رقم 111 لعام 1952.
المادة 5- تطبق أحكام المادة 148 من القانون المدني رقم 84 لعام 1949 على ما لم يرد فيه نص.
المادة 6- يلغى القانون رقم 464 لعام 1949.
المادة 7- تعدل المادة 2 من هذا القانون.
المادة 8- تعدل المادة /12/ مكرر من قانون العمل رقم ١٧ لعام ٢٠١٠."""


def _rows():
    return aa.extract_article_amendments("القانون رقم 10 لعام 2006", AMENDING)


def _find(ident, art):
    return [r for r in _rows() if r["target_identity"] == ident and r["article"] == art]


def test_amend_single_article_with_paragraph():
    r = _find("القانون:6:2001", 1)
    assert r and r[0]["action"] == "amend"
    assert "تعدل الفقرة أ من المادة 1" in r[0]["context"]


def test_repeal_two_articles_dual():
    assert _find("المرسوم التشريعي:81:1979", 7)[0]["action"] == "repeal"
    assert _find("المرسوم التشريعي:81:1979", 14)[0]["action"] == "repeal"


def test_add_and_range_and_ordinal_and_hindi_digits():
    assert _find("القانون:28:2001", 3)[0]["action"] == "add"
    assert [r["article"] for r in _rows() if r["target_identity"] == "القانون:20:2015"] == [5, 6, 7, 8]
    assert _find("المرسوم التشريعي:111:1952", 3)[0]["action"] == "amend"
    assert _find("القانون:17:2010", 12)[0]["action"] == "amend"


def test_no_row_for_citation_whole_law_or_self():
    idents = {r["target_identity"] for r in _rows()}
    assert "القانون:84:1949" not in idents, "«تطبق أحكام المادة» استشهاد لا تعديل"
    assert "القانون:464:1949" not in idents, "إلغاء الصك كله شأن law_status لا هذه الوحدة"
    assert "القانون:10:2006" not in idents, "لا إحالة ذاتية"


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, clean_content TEXT, identity_key TEXT, year INTEGER, issue_date TEXT, source_url TEXT)")
    c.execute("INSERT INTO documents VALUES (1, 'القانون رقم 10 لعام 2006', ?, 'القانون:10:2006', 2006, '2006-02-26', 'https://x/10')", (AMENDING,))
    c.execute("INSERT INTO documents VALUES (2, 'القانون رقم 6 لعام 2001', 'المادة 1- نص', 'القانون:6:2001', 2001, NULL, 'https://x/6')")
    return c


def test_rebuild_is_idempotent_and_export_has_contract_columns(tmp_path):
    c = _conn()
    r1 = aa.rebuild(c)
    r2 = aa.rebuild(c)
    assert r1 == r2 and r1["rows"] >= 9
    assert aa.record_for_doc(c, 1, "القانون رقم 10 لعام 2006", AMENDING) == 0, "لا تكرار"
    rep = aa.export_csv(c, tmp_path / "article_amendments.csv")
    assert rep["count"] == r1["rows"] and rep["repeal"] >= 6 and rep["add"] == 1
    head = (tmp_path / "article_amendments.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert head.split(",") == aa.CSV_COLUMNS
    rows = aa.export_rows(c)
    six = [r for r in rows if r["target_identity"] == "القانون:6:2001"][0]
    assert (six["target_type"], six["target_number"], six["target_year"]) == ("القانون", "6", "2001")
    assert six["amending_identity"] == "القانون:10:2006" and six["amending_date"] == "2006-02-26"
