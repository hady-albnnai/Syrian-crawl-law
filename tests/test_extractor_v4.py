# -*- coding: utf-8 -*-
"""اختبارات Extractor v4 — محلية بالكامل على Fixtures عربية."""
from pathlib import Path

import extractor_v4 as v4
from extractor import is_legal_content

FIX = Path(__file__).parent / "fixtures"


def _html(name):
    return (FIX / name).read_text(encoding="utf-8")


# ── 1) التنظيف ──
def test_normalize_removes_zero_width_and_tatweel():
    dirty = "قـانون​ العمل‏ ٢٠١٠"
    out = v4.normalize_unicode(dirty)
    assert "ـ" not in out and "​" not in out and "‏" not in out
    assert "قانون" in out


def test_normalize_fixes_sticky_digits():
    out = v4.normalize_unicode("المادة1-يسري هذا القانون على العمال")
    assert "المادة 1" in out


# ── 3) الأرقام ──
def test_western_digits_all_scripts():
    assert v4.to_western_digits("٢٠") == "20"
    assert v4.to_western_digits("۱۴۹") == "149"
    assert v4.to_western_digits("84") == "84"


def test_verbal_to_int():
    assert v4.verbal_to_int("الأولى") == 1
    assert v4.verbal_to_int("العاشرة") == 10
    assert v4.verbal_to_int("العشرون") == 20
    assert v4.verbal_to_int("الخامسة والعشرون") == 25


# ── 5) الهرمية ──
def test_hierarchy_accumulates():
    arts = v4.extract_main_content(_html("hierarchy_law.html"), "u")["articles"]
    real = [a for a in arts if not a["is_preamble"]]
    assert len(real) == 3
    assert real[0]["hierarchy_path"][:2] == ["الكتاب 1", "الباب 1"]
    assert real[2]["hierarchy_path"][-1] == "المبحث 1"


# ── 3/4) هندي + مقدمة ──
def test_hindi_digits_and_preamble():
    arts = v4.extract_main_content(_html("hierarchy_law.html"), "u")["articles"]
    pres = [a for a in arts if a["is_preamble"]]
    assert pres and "يرسم ما يلي" in pres[0]["text"]
    assert [a["article_number"] for a in arts if not a["is_preamble"]] == [1, 2, 3]


def test_preamble_not_forced_when_absent():
    arts = v4.extract_main_content(_html("duplicate_amended.html"), "u")["articles"]
    assert not [a for a in arts if a["is_preamble"]]  # لا مقدمة قسرية


# ── 3) لفظيات ──
def test_verbal_articles():
    arts = v4.extract_main_content(_html("verbal_law.html"), "u")["articles"]
    nums = [a["article_number"] for a in arts]
    assert nums == [1, 2, 3, 10, 20, 25]


# ── 6) مكررة/معدلة ──
def test_duplicate_and_amended_preserved():
    arts = v4.extract_main_content(_html("duplicate_amended.html"), "u")["articles"]
    by_num = {}
    for a in arts:
        by_num.setdefault(a["article_number"], []).append(a)
    dup = by_num[5]
    assert len(dup) == 2 and any(a["is_duplicate"] for a in dup)
    am6 = by_num[6][0]
    assert am6["amendment_note"] and "عدلت بموجب" in am6["amendment_note"]
    am7 = by_num[7][0]
    assert am7["amendment_note"] and "ألغيت" in am7["amendment_note"]


# ── 7) فقرات ──
def test_paragraphs_split():
    arts = v4.extract_main_content(_html("phpbb_legal_topic.html"), "u")["articles"]
    assert all(a["paragraphs"] for a in arts)


# ── 2) الحاوية + السقوط العام ──
def test_generic_fallback_container():
    html = ("<html><body><div class='weird-wrapper'>"
            "<p>مجلس الشعب — يرسم ما يلي:</p>"
            + "".join(f"<p>المادة {i}- نص قانوني طويل نوعاً ما يفصل حكماً "
                      f"مهماً في العلاقة بين الأطراف وفقاً للأصول.</p>"
                      for i in range(1, 8))
            + "</div></body></html>")
    res = v4.extract_main_content(html, "https://x.example/t1")
    assert res["success"] is True
    assert res["used_selector"].startswith("generic:")
    assert res["article_count"] >= 7


def test_phpbb_fixture_full_pipeline():
    res = v4.extract_main_content(_html("phpbb_legal_topic.html"), "https://x/t9")
    assert res["success"] is True
    assert res["article_count"] >= 4
    assert res["quality_score"] >= 0.5
    assert res["source_locator"]["html_hash"].startswith("sha256:")


def test_non_legal_fixture_low_quality():
    res = v4.extract_main_content(_html("generic_non_legal.html"), "https://x/f")
    assert res["success"] is True  # نص طويل لكنه غير قانوني
    assert res["article_count"] == 0
    assert res["quality_score"] < 0.5
    assert is_legal_content(res["clean_text"], res["title"]) is False


# ── 7) عقد موحد ──
def test_article_key_stable_and_contract_fields():
    arts = v4.extract_main_content(_html("verbal_law.html"), "u")["articles"]
    k1 = v4.article_key("doc:1", arts[0])
    k2 = v4.article_key("doc:1", arts[0])
    assert k1 == k2 and k1.startswith("sha256:")
    a = arts[0]
    for field in ("article_number", "label", "text", "paragraphs",
                  "hierarchy_path", "is_duplicate", "amendment_note",
                  "is_preamble", "char_count"):
        assert field in a
