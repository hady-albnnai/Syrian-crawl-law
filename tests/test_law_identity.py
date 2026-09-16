# -*- coding: utf-8 -*-
"""اختبارات law_identity — محلية بالكامل، لا شبكة.

تحرس القطعة الأولى من خطة الاكتشاف الذاتي للمصادر
(DELIVERY/DESIGN-SELF-DISCOVERY.md §2): استخراج هوية القانون
(نوع+رقم+سنة) من العنوان/الديباجة، ومطابقة الإشارات النصية داخل المتن.
"""
import law_identity as li


# ───────────────────────── استخراج هوية العنوان ─────────────────────────

def test_extracts_decree_law_number_and_year_from_title():
    r = li.extract_law_identity(
        "المرسوم التشريعي رقم 148 لعام 1949 قانون العقوبات", "")
    assert r["doc_type"] == "المرسوم التشريعي"
    assert r["law_number"] == 148
    assert r["law_year"] == 1949
    assert r["identity_confidence"] == "number_year"
    assert r["identity_key"] == "المرسوم التشريعي:148:1949"


def test_extracts_from_preamble_when_title_has_no_id():
    title = "قانون العقوبات السوري"
    text = "صدر بالمرسوم التشريعي رقم 148 لعام 1949 وتعديلاته. المادة 1- ..."
    r = li.extract_law_identity(title, text)
    assert r["law_number"] == 148
    assert r["law_year"] == 1949


def test_no_id_found_returns_none_confidence_not_fake_certainty():
    r = li.extract_law_identity("قانون بلا رقم مذكور", "نص عام بلا أي رقم")
    assert r["identity_key"] is None
    assert r["identity_confidence"] is None
    assert r["law_number"] is None


def test_law_type_preferred_over_generic_decree():
    # "القانون رقم" يجب ألا يُطابَق داخل "المرسوم التشريعي رقم" بالخطأ
    r = li.extract_law_identity("القانون رقم 10 لعام 2015", "")
    assert r["doc_type"] == "القانون"
    assert r["law_number"] == 10
    assert r["law_year"] == 2015


def test_decree_legislative_matched_before_generic_decree():
    r = li.extract_law_identity("المرسوم التشريعي رقم 32 لعام 2021", "")
    assert r["doc_type"] == "المرسوم التشريعي"  # لا "المرسوم" وحده


def test_historical_synonym_normalized_to_modern_name():
    r = li.extract_law_identity("المرسوم الاشتراعي رقم 1 لعام 1950", "")
    assert r["doc_type"] == "المرسوم التشريعي"


def test_eastern_arabic_digits_supported():
    r = li.extract_law_identity("القانون رقم ١٥ لعام ٢٠٢٢", "")
    assert r["law_number"] == 15
    assert r["law_year"] == 2022


def test_year_out_of_plausible_range_is_rejected():
    r = li.extract_law_identity("القانون رقم 5 لعام 12", "")
    assert r["identity_key"] is None


# ───────────────────────── مفتاح الهوية ─────────────────────────

def test_build_identity_key_format():
    assert li.build_identity_key("القانون", 10, 2015) == "القانون:10:2015"


# ───────────────────────── إشارات نصية داخل المتن ─────────────────────────

def test_extracts_multiple_references_from_body_text():
    text = (
        "المادة 6- عدلت بموجب المرسوم رقم 14 لعام 2023. "
        "المادة 7- ألغيت بموجب القانون رقم 20 لعام 2024."
    )
    refs = li.extract_law_references(text)
    keys = {r["identity_key"] for r in refs}
    assert "المرسوم:14:2023" in keys
    assert "القانون:20:2024" in keys
    assert len(refs) == 2


def test_references_deduplicated_within_same_text():
    text = ("عدلت بالمرسوم رقم 14 لعام 2023. وأشير لاحقاً مجدداً "
            "لنفس المرسوم رقم 14 لعام 2023 بموضع آخر.")
    refs = li.extract_law_references(text)
    assert len(refs) == 1


def test_reference_context_captures_surrounding_text():
    text = "المادة 7- ألغيت بموجب القانون رقم 20 لعام 2024 لعدم الحاجة."
    refs = li.extract_law_references(text)
    assert "ألغيت" in refs[0]["context"]


def test_no_references_in_plain_text():
    assert li.extract_law_references("نص عادي بلا أي إشارة قانونية") == []


def test_empty_text_returns_empty_list():
    assert li.extract_law_references("") == []


# ───────────────────────── تحويل إشارة إلى استعلام بحث ─────────────────────────

def test_reference_to_search_query_format():
    ref = {"doc_type": "المرسوم التشريعي", "law_number": 32, "law_year": 2021}
    q = li.reference_to_search_query(ref)
    assert q == "المرسوم التشريعي رقم 32 لعام 2021 سوريا نص كامل"


# ───────────── ف١ (2026-09-16): صيغ العناوين الحقيقية بلا أل التعريف ─────────────
# اكتُشفت على وثائق حقيقية: قانون العمل رقم /17/ لعام 2010 (tss-est)
# وقرار وزارة العدل رقم (349) ل لعام 2026 (moj.gov.sy) — كانت تفقد
# هويتها كاملة لأن الأنماط تطلبت «القانون» بأل التعريف حصراً.

def test_bare_type_without_article_matches():
    r = li.extract_law_identity(
        "قانون العمل رقم /17/ لعام 2010 الجمهورية العربية السورية", "")
    assert r["identity_key"] == "القانون:17:2010"
    assert r["identity_confidence"] == "number_year"


def test_bare_and_definite_forms_share_one_key():
    a = li.extract_law_identity("القانون رقم 17 لعام 2010", "")
    b = li.extract_law_identity("قانون رقم 17 لعام 2010", "")
    assert a["identity_key"] == b["identity_key"] == "القانون:17:2010"


def test_moj_decision_title_with_minister_name():
    r = li.extract_law_identity(
        "قرار وزارة العدل رقم (349) ل لعام 2026 بشأن التنقلات القضائية", "")
    assert r["identity_key"] == "القرار:349:2026"


def test_circular_type_supported():
    r = li.extract_law_identity(
        "تعميم رقم 3 لعام 2026 بشأن صلاحيات المحامين المتمرنين", "")
    assert r["doc_type"] == "التعميم"
    assert r["identity_key"] == "التعميم:3:2026"


def test_bare_legislative_decree_full_type():
    r = li.extract_law_identity("مرسوم تشريعي رقم 55 لعام 1959 قانون مجلس الدولة", "")
    assert r["doc_type"] == "المرسوم التشريعي"
    assert r["identity_key"] == "المرسوم التشريعي:55:1959"


def test_bare_references_in_body_extracted():
    refs = li.extract_law_references(
        "المادة 1- تعدل المواد 12 و45 من القانون رقم 28 لعام 2001 المتعلق "
        "بعمل المصارف المرخصة في سورية.")
    assert any(r["identity_key"] == "القانون:28:2001" for r in refs)


# ───────────── ف١: إعادة تحديد هوية الوثائق المخزَّنة ─────────────

def _tmp_db(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "reid.db"))
    database.create_tables()
    return database.get_connection()


def _insert(conn, title, content, identity=None, doc_type="law"):
    cur = conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "identity_key, doc_type) VALUES (?, ?, ?, ?, ?, ?)",
        (f"d{title[:8]}", title, f"https://t/{title[:8]}", content,
         identity, doc_type))
    return cur.lastrowid


def test_reidentify_gains_identity_for_old_code_victim(tmp_path, monkeypatch):
    # وثيقة حُفظت بالكود القديم (قبل قبول أل التعريف الاختيارية):
    # عنوانها سليم لكن هويتها NULL
    conn = _tmp_db(tmp_path, monkeypatch)
    doc_id = _insert(conn, "قانون العمل رقم /17/ لعام 2010",
                     "نص القانون بمواده الكاملة هنا.")
    stats = li.reidentify_documents(conn)
    assert stats["gained"] == 1
    row = conn.execute("SELECT identity_key, number, year, doc_type "
                       "FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["identity_key"] == "القانون:17:2010"
    assert (row["number"], row["year"]) == (17, 2010)
    assert row["doc_type"] == "law"  # عمود تصنيف الوثائق لا يُمس


def test_reidentify_keeps_existing_identity_when_no_new_match(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert(conn, "وثيقة موسومة سابقاً", "نص بلا هوية.",
            identity="القانون:5:1999")
    stats = li.reidentify_documents(conn)
    assert stats["no_match"] == 1 and stats["gained"] == 0
    row = conn.execute("SELECT identity_key FROM documents").fetchone()
    assert row["identity_key"] == "القانون:5:1999"  # لا تُمحى هوية قائمة


def test_reidentify_unchanged_when_same_key(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert(conn, "القانون رقم 17 لعام 2010", "نص.",
            identity="القانون:17:2010")
    stats = li.reidentify_documents(conn)
    assert stats["unchanged"] == 1


# ───────────── ف١-ب: صيغة الإسناد المائلة «رقم 148/1949» (ويبو ليكس) ────────

def test_slash_year_citation_in_title():
    r = li.extract_law_identity(
        "القانون الجنائي (الصادر بالمرسوم التشريعي رقم 148/1949), "
        "الجمهورية العربية السورية", "")
    assert r["identity_key"] == "المرسوم التشريعي:148:1949"


def test_slash_year_and_full_year_share_key():
    a = li.extract_law_identity("المرسوم التشريعي رقم 148/1949", "")
    b = li.extract_law_identity("المرسوم التشريعي رقم 148 لعام 1949", "")
    assert a["identity_key"] == b["identity_key"]


def test_slash_year_reference_extracted_from_body():
    refs = li.extract_law_references(
        "المادة 1- تعدل المواد 12 و45 من المرسوم التشريعي رقم 148/1949.")
    assert any(r["identity_key"] == "المرسوم التشريعي:148:1949" for r in refs)


from law_identity import extract_law_identity  # ف٢: اختبارات الصيغ المقيسة


# ── ف٢: صيغ أرشيف مجلس الشعب المقيسة (شرطة السنة / صيغة مائلة بلا رقم) ──
def test_slash_before_year_full():
    """«رقم/ 148/ لعام /1949/» — شرطة تسبق السنة (عنوان HF للعقوبات)."""
    r = extract_law_identity("قانون العقوبات رقم/ 148/ لعام /1949/", "")
    assert r["identity_key"] == "القانون:148:1949"


def test_slash_form_without_raqm_title_fallback():
    """«المرسوم 98/1961» بلا كلمة رقم — احتياط العنوان فقط."""
    r = extract_law_identity("قانون السلطة القضائية ـ المرسوم 98/1961", "")
    assert r["identity_key"] == "المرسوم:98:1961"
    r2 = extract_law_identity("قانون مخالفات الأبنية 1/2003", "")
    assert r2["identity_key"] == "القانون:1:2003"


def test_slash_fallback_not_applied_to_text():
    """النص لا يُفحص بصيغة بلا رقم — إحالة صليبية ليست هوية الوثيقة."""
    r = extract_law_identity(
        "نظام مزعوم بلا رقم",
        "يستبدل النص المشار إليه في القانون 10/2014 بما يلي")
    assert r["identity_key"] is None
