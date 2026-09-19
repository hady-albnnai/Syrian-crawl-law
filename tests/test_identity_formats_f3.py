# -*- coding: utf-8 -*-
"""ف٣ (2026-09-19): صيغ هوية رسمية إضافية — الهدف تقليص «بلا هوية»
(291/513 بقاعدة المالك) لأن وثيقة بلا هوية لا يستشهد بها ذكاءٌ اصطناعي
ولا تُحسب لها حالة نفاذ.

كل حالة هنا صيغة تظهر فعلاً في العناوين الرسمية السورية (الجريدة الرسمية،
مجلس الشعب، ويبو ليكس)، لا اختراعاً. والحالات السالبة تحرس من الاختطاف.
"""
import pytest

import law_identity as li


@pytest.mark.parametrize("title,expected", [
    # «لسنة» و«للعام» و«عام»/«سنة» بلا لام
    ("القانون رقم 5 لسنة 2011", "القانون:5:2011"),
    ("قانون رقم (17) للعام 2010", "القانون:17:2010"),
    ("مرسوم تشريعي رقم 3 عام 2001", "المرسوم التشريعي:3:2001"),
    ("قانون رقم ١٥ لسنة ٢٠٢٢", "القانون:15:2022"),
    # «تاريخ يوم/شهر/سنة» و«تاريخ سنة/شهر/يوم» — السنة من التاريخ
    ("المرسوم التشريعي رقم 148 تاريخ 22/6/1949", "المرسوم التشريعي:148:1949"),
    ("المرسوم رقم 20 تاريخ 1949/6/22", "المرسوم:20:1949"),
    ("المرسوم التشريعي رقم /84/ تاريخ 18/5/1949", "المرسوم التشريعي:84:1949"),
    ("قانون أصول المحاكمات المدنية الصادر بالقانون رقم 1 تاريخ 3/1/2016",
     "القانون:1:2016"),
    # عنوان موضوع طويل بين النوع وكلمة «رقم»
    ("القانون الأساسي للعاملين في الدولة رقم 50 لعام 2004",
     "القانون الأساسي:50:2004"),
    # بلا كلمة «رقم» لكن بسنة صريحة (عنوان فقط)
    ("المرسوم التشريعي 148 لعام 1949 (قانون العقوبات)",
     "المرسوم التشريعي:148:1949"),
    ("القانون 10 لعام 2015", "القانون:10:2015"),
    # الصيغ القديمة ما زالت تعمل
    ("قانون العمل رقم /17/ لعام 2010", "القانون:17:2010"),
    ("قانون السلطة القضائية ـ المرسوم 98/1961", "المرسوم:98:1961"),
])
def test_official_formats_recognized(title, expected):
    assert li.extract_law_identity(title, "")["identity_key"] == expected


@pytest.mark.parametrize("title", [
    "قانون العمل",                        # لا رقم ولا سنة
    "القانون رقم 5 لعام 12",              # سنة خارج النطاق
    "المادة 5 من القانون تاريخ 2010",     # لا رقم صك
])
def test_no_hallucinated_identity(title):
    assert li.extract_law_identity(title, "")["identity_key"] is None


def test_no_raqm_fallback_respects_leading_instrument():
    """«قانون العقوبات الصادر بالمرسوم التشريعي 148 لعام 1949»: صكّ العنوان
    «القانون» والمرسوم إحالة إسناد — حارس الصدر (فرع المالك) يمنع منح
    الهوية للمرسوم؛ لا هوية أفضل من هوية مسروقة."""
    r = li.extract_law_identity(
        "قانون العقوبات الصادر بالمرسوم التشريعي 148 لعام 1949", "")
    assert r["identity_key"] is None


def test_nearest_type_wins_not_first():
    """«القانون الجنائي (الصادر بالمرسوم التشريعي رقم 148/1949)»: الصك
    الفعلي هو المرسوم التشريعي (الأقرب لكلمة رقم) لا «القانون» الأول."""
    r = li.extract_law_identity(
        "القانون الجنائي (الصادر بالمرسوم التشريعي رقم 148/1949)", "")
    assert r["identity_key"] == "المرسوم التشريعي:148:1949"


def test_no_raqm_fallback_is_title_only():
    """صيغة «القانون 10 لعام 2015» بلا «رقم» لا تُقبل من متن النص —
    المتن مليء بإحالات صليبية فتكون هوية زائفة."""
    r = li.extract_law_identity("قانون العمل",
                                "استناداً إلى القانون 10 لعام 2015 ...")
    assert r["identity_key"] is None


def test_date_year_in_body_preamble():
    """الديباجة الحقيقية: «المرسوم التشريعي رقم 84 تاريخ 18/5/1949» في أول
    500 حرف — تُقبل من النص لأنها بكلمة «رقم»."""
    body = "الجمهورية العربية السورية\nالمرسوم التشريعي رقم 84 تاريخ 18/5/1949\nرئيس الدولة..."
    r = li.extract_law_identity("قانون العقوبات", body)
    assert r["identity_key"] == "المرسوم التشريعي:84:1949"
    assert r["law_year"] == 1949


def test_references_pick_up_new_year_words():
    refs = li.extract_law_references(
        "يعدل القانون رقم 28 لسنة 2001 ويلغي المرسوم رقم 9 تاريخ 1/2/1990")
    keys = {r["identity_key"] for r in refs}
    assert keys == {"القانون:28:2001", "المرسوم:9:1990"}


# --- ف٤: هوية مركّبة آمنة (سنة العنوان + رقم الديباجة) --------------------
def test_merge_title_year_with_preamble_number_real_case_4():
    """قاعدة المالك #4: «قانون تنظيم مهنة المحاماة لعام 2010» + ديباجة
    «القانون رقم 30» ⇒ القانون:30:2010 (كلٌّ وحده ناقص)."""
    r = li.merge_title_preamble_identity(
        "قانون تنظيم مهنة المحاماة لعام 2010",
        "الجمهورية العربية السورية القانون رقم 30 رئيس الجمهورية بناء على")
    assert r["identity_key"] == "القانون:30:2010"
    assert r["identity_confidence"] == "title_year+preamble_number"


@pytest.mark.parametrize("title,body,why", [
    ("المرسوم التشريعي رقم 6: قانون مكافحة الإتجار بالبشر- 2010",
     "المرسوم التشريعي رقم (3) رئيس الجمهورية",
     "تناقض عنوان/ديباجة (#19) — للمراجعة البشرية لا الحسم الآلي"),
    ("قانون حماية حقوق المؤلف في سورية 2001",
     "قانون حماية حقوق المؤلف يقصد بالتعابير الآتية", "لا رقم بالديباجة"),
    ("قانون العقوبات لعام 1949", "استناداً إلى المرسوم التشريعي رقم 148",
     "نوع الصك بالديباجة يخالف صكّ العنوان"),
    ("قانون التجارة رقم 33, الجمهورية العربية السورية",
     "القانون رقم 33 / / رئيس الجمهورية", "لا سنة بالعنوان"),
    ("مقال عن المحاماة لعام 2010", "القانون رقم 30", "العنوان لا يبدأ بصك"),
])
def test_merge_refuses_when_unsafe(title, body, why):
    assert li.merge_title_preamble_identity(title, body) is None, why


def test_reidentify_uses_merge_only_when_no_identity(tmp_path, monkeypatch):
    import sqlite3
    import config, database
    p = tmp_path / "m.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = sqlite3.connect(p); conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO documents (doc_id, title, source_url, "
                 "clean_content) VALUES ('a', 'قانون تنظيم مهنة المحاماة لعام 2010',"
                 " 'https://x/a', 'الجمهورية العربية السورية القانون رقم 30 رئيس')")
    conn.execute("INSERT INTO documents (doc_id, title, source_url, clean_content,"
                 " identity_key) VALUES ('b', 'قانون العمل لعام 2010', 'https://x/b',"
                 " 'القانون رقم 99', 'القانون:17:2010')")
    conn.commit()
    stats = li.reidentify_documents(conn)
    assert stats["merged"] == 1
    a = conn.execute("SELECT identity_key, number, year FROM documents "
                     "WHERE doc_id='a'").fetchone()
    assert tuple(a) == ("القانون:30:2010", 30, 2010)
    b = conn.execute("SELECT identity_key FROM documents WHERE doc_id='b'"
                     ).fetchone()[0]
    assert b == "القانون:17:2010"  # هوية قائمة لا تُداس بالدمج
