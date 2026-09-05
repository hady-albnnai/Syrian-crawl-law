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
