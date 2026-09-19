"""A-2: تاريخ الإصدار — على عبارات حقيقية من الصكوك المقروءة في الجلسة."""
from issue_date import extract_issue_date


def test_closing_hijri_then_gregorian_takes_gregorian():
    t = "... ينشر هذا المرسوم التشريعي. دمشق في 19/7/1427 هجري الموافق 13/8/2006 ميلادي رئيس الجمهورية"
    r = extract_issue_date(t, 2006)
    assert (r["issue_date"], r["issue_date_hijri"], r["issue_date_confidence"]) == ("2006-08-13", "19/7/1427", "closing")


def test_closing_with_lam_prefix_and_ha():
    t = "المادة(159) ينشر هذا القانون. دمشق في 22/2/1428هـ الموافق لـ12/3/2007م"
    assert extract_issue_date(t, 2007)["issue_date"] == "2007-03-12"


def test_sadar_fi_with_spaces_and_eastern_digits():
    t = "المادة 39 صدر في ١٦ /٥ /١٩٦٦ رئيس الجمهورية"
    assert extract_issue_date(t, 1966)["issue_date"] == "1966-05-16"


def test_heading_number_then_date():
    t = "القرار بالقانون رقم 92 تاريخ 6 ـ 4 ـ 1959 بإصدار قانون التأمينات الاجتماعية باسم الأمة"
    r = extract_issue_date(t, 1959)
    assert (r["issue_date"], r["issue_date_confidence"]) == ("1959-04-06", "heading")


def test_heading_slashes_and_trailing_meem():
    t = "المرسوم: المرسوم التشريعي ذو الرقم/ 55 / تاريخ 2/9/2004م. التعليمات:"
    assert extract_issue_date(t)["issue_date"] == "2004-09-02"


def test_hijri_only_is_stored_as_text_not_converted():
    t = "دمشق في 12/1/1430 هـ رئيس الجمهورية"
    r = extract_issue_date(t)
    assert r["issue_date"] is None and r["issue_date_hijri"] == "12/1/1430"


def test_conflict_with_identity_year_is_refused():
    t = "دمشق في 13/8/2006 رئيس الجمهورية"
    r = extract_issue_date(t, 1949)
    assert r["issue_date"] is None and r["conflict"] is True


def test_reference_date_in_body_is_ignored():
    # «تاريخ» في وسط المتن لصك محال إليه — لا رأس ولا ختام
    t = "المادة 1 " + "نص " * 300 + "وفق المرسوم رقم 84 تاريخ 28/9/1953 " + "نص " * 600
    assert extract_issue_date(t)["issue_date"] is None


def test_invalid_calendar_date_is_dropped():
    assert extract_issue_date("دمشق في 31/2/2006")["issue_date"] is None
