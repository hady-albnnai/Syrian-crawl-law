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


# --- الحالات الحقيقية من repealed.txt (قاعدة المالك 2026-09-19) -----------
from law_status import extract_amendments


def _acts(title, text):
    return sorted((a["action"], a["target_identity"])
                  for a in extract_amendments(title, text))


def test_penal_code_not_repealed_by_range_reference_plus_generic_clause():
    """الخطأ الأخطر المقيس: قانون العقوبات 148/1949 عُلِّم «ملغى» لأن قانون
    حق المؤلف أحال إلى مواده 708–715 ثم ختم بـ«تلغى جميع الأحكام المخالفة»."""
    acts = _acts(
        "قانون حماية حق المؤلف (الصادر بالمرسوم التشريعي رقم 62/2013)",
        "يعاقب بالمواد من /708/ الى /715/ من قانون العقوبات العام الصادر "
        "بالمرسوم التشريعي ذي الرقم /148/ لعام 1949. المادة 104 تلغى جميع "
        "الاحكام المخالفة لهذا القانون كما يلغى كل نص آخر")
    assert ("repeal", "المرسوم التشريعي:148:1949") not in acts
    assert acts == []


def test_labour_law_repeals_both_predecessors():
    acts = _acts("القانون رقم 17 لعام 2010",
                 "المادة (279): أ- يلغى القانون رقم 91 لعام 1959 وتعديلاته "
                 "والمرسوم التشريعي رقم 49 لعام 1962 وتعديلاته. ب- يصدر الوزير")
    assert set(acts) == {("repeal", "المرسوم التشريعي:49:1962"),
                         ("repeal", "القانون:91:1959")}


def test_media_law_repeals_press_decree_and_keeps_own_identity():
    """عنوان «قانون الإعلام (الصادر بالمرسوم التشريعي رقم 108 لعام 2011)»:
    المرسوم هويته لا إحالة — وإلا سرق هوية القانون الذي يلغيه من متنه
    فسقط الإلغاء كإشارة ذاتية."""
    import law_identity as li
    t = "قانون الإعلام (الصادر بالمرسوم التشريعي رقم 108 لعام 2011)،الجمهورية العربية السورية"
    assert li.extract_law_identity(t, "")["identity_key"] == "المرسوم التشريعي:108:2011"
    acts = _acts(t, "ويلغى أيضا: 1- قانون المطبوعات الصادر بالمرسوم التشريعي "
                    "رقم 50 لعام 2001. 2- قانون التواصل مع العموم")
    assert acts == [("repeal", "المرسوم التشريعي:50:2001")]


def test_amending_decree_in_title_still_not_identity():
    """حارس الفرع يبقى: «المعدَّل بالمرسوم» إحالة لا هوية."""
    import law_identity as li
    assert li.extract_law_identity(
        "قانون العقوبات العامة السوري المعدل بالمرسوم رقم 12 لعام 2001", ""
    )["identity_key"] is None


def test_repeal_verb_after_reference_does_not_apply_backwards():
    acts = _acts("القانون رقم 1 لعام 2020",
                 "استناداً إلى القانون رقم 10 لعام 2006 يلغى المرسوم رقم 9 لعام 1990")
    assert acts == [("repeal", "المرسوم:9:1990")]


def test_media_law_real_text_numbered_list_and_partial_clause():
    """النص الحقيقي لقانون الإعلام (#94 بقاعدة المالك، 2026-09-19):
    - «تلغى الأحكام المخالفة … الواردة في القانون 68/1951» = تعديل جزئي.
    - «ويلغى أيضا:\\n1- … 50/2001.\\n2- … 26/2011.» = الفعل قبل النقطتين
      يسري على كل بنود القائمة رغم السطر الجديد ونقطة البند السابق."""
    body = ('حكام الدستور،\nيرسم ما يلي:\nالمادة الأولى\nتطبق أحكام قانون '
            'الإعلام المرفق.\nالمادة الثانية\nتلغى الأحكام المخالفة لهذا '
            'القانون الواردة في القانون رقم 68 لعام 1951 الخاص بالنظام '
            'الأساسي للإذاعة ويلغى أيضا:\n1- قانون المطبوعات الصادر بالمرسوم '
            'التشريعي رقم 50 لعام 2001.\n2- قانون التواصل مع العموم على '
            'الشبكة الصادر بالمرسوم التشريعي رقم 26 لعام 2011.\nالمادة الثالثة')
    acts = _acts("قانون الإعلام (الصادر بالمرسوم التشريعي رقم 108 لعام 2011)"
                 "،الجمهورية العربية السورية", body)
    assert set(acts) == {("amend", "القانون:68:1951"),
                         ("repeal", "المرسوم التشريعي:50:2001"),
                         ("repeal", "المرسوم التشريعي:26:2011")}
