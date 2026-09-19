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


# --- أنماط حقيقية من issue_dates1.txt (قاعدة المالك) ---------------------------
import pytest


@pytest.mark.parametrize("tail,expect", [
    ("دمشق في 2-8-1429 ه الموافق ل 4-8-2008", "2008-08-04"),
    ("تاريخ صدوره. دمشق في 20/1/1422 ه 26/3/2001", "2001-03-26"),
    ("دمشق في 26/12/81406 ه الموافق 31/8/1986", "1986-08-31"),
    ("لتنفيذ أحكامه. دمشق تاريخ 5/8/1975", "1975-08-05"),
    ("دمشق 4-12-1421 ه الموافق 27-2-2001", "2001-02-27"),
    ("دمشق 3 /5/ 1426 هجرية 9 /6 /2005", "2005-06-09"),
    ("دمشق 20/1/1427/ه الموافق ل /19/2/2006", "2006-02-19"),
    ("دمشق في / /1427 هجري الموافق 6/7/2006", "2006-07-06"),
    ("تاريخ صدوره دمشق في 5/7/1422/و/22/9/2001", "2001-09-22"),
    ("دمشق في: 23/11/ 1425 ه الموافق ل: 3 / 1/ 2005", "2005-01-03"),
    ("دمشق في 22/ 3/ 1426 هجري، الموافق 30/ 4/ 2005", "2005-04-30"),
    ("دمشق في 10/9/1429 ه الموافق في 10/9/2008", "2008-09-10"),
    ("فيعودوا مستنفدين . دمشق في /04/10/2011", "2011-10-04"),
    ("صادر في 15 آذار سنة 1926", "1926-03-15"),
    ("تنفيذها. دمشق في 22/1/1976", "1976-01-22"),
])
def test_real_owner_closings(tail, expect):
    assert extract_issue_date("المادة 1 نص. " + tail)["issue_date"] == expect


def test_hijri_only_owner_style():
    r = extract_issue_date("دمشق في 12/1/1430 ه رئيس الجمهورية")
    assert r["issue_date"] is None and r["issue_date_hijri"] == "12/1/1430"
