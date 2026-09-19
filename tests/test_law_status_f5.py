# -*- coding: utf-8 -*-
"""ف٥ — دقة حالة النفاذ. أخطر خطأ على المحامي: قانون نافذ يُعلَّم «ملغى»
(أو العكس). ثلاثة حرّاس مُقاسة:
  1) إلغاء جزئي (مادة/فقرة) = تعديل لا إلغاء.
  2) المعدِّل يجب أن يكون صكاً (لا أعمالاً تحضيرية/مقالاً).
  3) الزمن: الأقدم لا يعدّل الأحدث.
"""
import sqlite3

import pytest

from law_status import classify_context, compute_legal_statuses


@pytest.mark.parametrize("ctx,expected", [
    ("تُلغى المادة 5 من القانون رقم 28 لعام 2001 ويستعاض عنها", "amend"),
    ("تلغى المواد 3 و4 و7 من القانون رقم 33 لعام 2007", "amend"),
    ("تُلغى الفقرة ب من المادة 12 من المرسوم التشريعي رقم 148", "amend"),
    ("يُلغى القانون رقم 28 لعام 2001 وتحل أحكام هذا القانون محله", "repeal"),
    ("يُلغى العمل بأحكام القانون رقم 11 لعام 1990", "repeal"),
    ("تلغى أحكام المرسوم التشريعي رقم 49 لعام 1962", "repeal"),
    ("يلغى كل نص مخالف ولا سيما القانون رقم 5 لعام 1980", "repeal"),
    ("تُضاف إلى القانون رقم 3 لعام 2010 مادة جديدة برقم 15 مكرر", "amend"),
    ("يُعدَّل نص المادة 7 من القانون رقم 17 لعام 2010", "amend"),
    ("استناداً إلى أحكام القانون رقم 10 لعام 2006", "cite"),
    ("مع مراعاة أحكام المرسوم رقم 9 لعام 1990", "cite"),
])
def test_partial_repeal_is_amendment_and_tashkeel_ignored(ctx, expected):
    assert classify_context(ctx) == expected


@pytest.fixture
def db(tmp_path, monkeypatch):
    import config, database
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = sqlite3.connect(p); conn.row_factory = sqlite3.Row

    def doc(doc_id, title, year, key, nature="instrument"):
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_url, year, "
            "identity_key, nature) VALUES (?,?,?,?,?,?)",
            (doc_id, title, f"https://x/{doc_id}", year, key, nature))
        return conn.execute("SELECT id FROM documents WHERE doc_id=?",
                            (doc_id,)).fetchone()[0]

    def link(src_id, target, action):
        conn.execute("INSERT INTO law_amendments (amending_doc_id, "
                     "target_identity, action) VALUES (?,?,?)",
                     (src_id, target, action))

    return conn, doc, link


def test_amender_must_be_instrument(db):
    conn, doc, link = db
    doc("t", "قانون العمل", 2010, "القانون:17:2010")
    tr = doc("tr", "الأعمال التحضيرية …", 2015, None, nature="travaux")
    link(tr, "القانون:17:2010", "repeal")
    compute_legal_statuses(conn)
    st = conn.execute("SELECT legal_status FROM documents WHERE doc_id='t'"
                      ).fetchone()[0]
    assert st == "ساري", "أعمال تحضيرية تذكر «يلغى» لا تُلغي قانوناً"


def test_older_instrument_cannot_amend_newer(db):
    conn, doc, link = db
    doc("t", "قانون العمل", 2010, "القانون:17:2010")
    old = doc("o", "قانون قديم", 1959, "القانون:91:1959")
    link(old, "القانون:17:2010", "repeal")
    compute_legal_statuses(conn)
    st = conn.execute("SELECT legal_status FROM documents WHERE doc_id='t'"
                      ).fetchone()[0]
    assert st == "ساري", "صكّ 1959 لا يلغي صكّ 2010"


def test_unknown_year_amender_is_still_counted(db):
    """الجهل بالسنة لا يُسقط الدليل — يُبقى ويُبرز للمراجعة."""
    conn, doc, link = db
    doc("t", "قانون العمل", 2010, "القانون:17:2010")
    ny = doc("n", "مرسوم بلا سنة", None, "المرسوم:5:2020")
    link(ny, "القانون:17:2010", "amend")
    compute_legal_statuses(conn)
    st = conn.execute("SELECT legal_status FROM documents WHERE doc_id='t'"
                      ).fetchone()[0]
    assert st == "معدَّل"


def test_real_repeal_by_newer_instrument(db):
    conn, doc, link = db
    doc("t", "قانون قديم", 2001, "القانون:28:2001")
    new = doc("n", "قانون جديد", 2011, "القانون:5:2011")
    link(new, "القانون:28:2001", "repeal")
    counts = compute_legal_statuses(conn)
    st = conn.execute("SELECT legal_status FROM documents WHERE doc_id='t'"
                      ).fetchone()[0]
    assert st == "ملغى" and counts["ملغى"] == 1
