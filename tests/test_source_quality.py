# -*- coding: utf-8 -*-
"""اختبارات source_quality — فئة رسمية المصدر + اكتمال النص (محلية، لا شبكة).

تحرس معياري المقارنة اللذين حددهما المالك صراحة (DESIGN-SELF-DISCOVERY.md
§4.2): المصدر الرسمي أولاً، ثم اكتمال النص الكامل.
"""
import source_quality as sq


# ───────────────────────── domain_tier_for_url ─────────────────────────

def test_parliament_gov_sy_is_tier_1():
    assert sq.domain_tier_for_url("https://parliament.gov.sy/arabic/x") == 1


def test_ministry_of_justice_is_tier_2():
    assert sq.domain_tier_for_url("https://moj.gov.sy/law") == 2


def test_wikisource_is_tier_3():
    assert sq.domain_tier_for_url("https://ar.wikisource.org/wiki/x") == 3


def test_unknown_forum_is_default_tier_4():
    assert sq.domain_tier_for_url(
        "https://law-library.syriaforums.net/t1") == 4


def test_unrelated_gov_sy_subdomain_not_auto_promoted():
    # لا نمنح رسمية تلقائية لكل نطاق ينتهي بـgov.sy — يجب إدراجه صراحة
    assert sq.domain_tier_for_url("https://random.gov.sy/x") == 4


def test_www_prefix_stripped_before_lookup():
    assert sq.domain_tier_for_url("https://www.parliament.gov.sy/x") == 1


def test_empty_url_returns_default_tier():
    assert sq.domain_tier_for_url("") == 4


# ───────────────────────── is_complete_text ─────────────────────────

def _arts(*numbers):
    return [{"article_number": n, "is_preamble": False} for n in numbers]


def test_gapless_sequence_without_truncation_is_complete():
    text = "نص كامل بلا أي اقتطاع ينتهي بشكل طبيعي بلا عبارات قص."
    assert sq.is_complete_text(text, _arts(1, 2, 3, 4)) is True


def test_gap_in_article_numbers_marks_incomplete():
    text = "نص ينتهي بشكل طبيعي."
    assert sq.is_complete_text(text, _arts(1, 2, 3, 7)) is False


def test_truncation_marker_near_end_marks_incomplete():
    text = "نص المادة الأولى وبعض التفاصيل... اقرأ المزيد"
    assert sq.is_complete_text(text, _arts(1, 2)) is False


def test_single_article_not_penalized_for_lack_of_sequence():
    text = "نص قصير ينتهي طبيعياً."
    assert sq.is_complete_text(text, _arts(1)) is True


def test_preamble_excluded_from_gap_check():
    articles = [{"article_number": 0, "is_preamble": True}] + _arts(1, 2, 3)
    text = "نص طبيعي."
    assert sq.is_complete_text(text, articles) is True
