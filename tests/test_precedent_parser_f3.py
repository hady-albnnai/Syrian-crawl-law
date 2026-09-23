"""ف٣: محلل الاستشهادات + هجرة 012 — على نصوص حرفية قِيست 2026-09-21."""
import config
import database
import pytest
from precedent_parser import (parse_citation, parse_text, extract_article_refs,
                              extract_overrulings, authority_rank)


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


# ---------------------------------------------------------------- الشكل 2 (سطري)
def test_inline_naqd_with_chamber_and_source():
    c = parse_citation("نقض سوري – الغرفة المدنية الثالثة – قرار 1890- أساس 2914- تاريخ 9/11/1997 – سجلات محكمة النقض")
    assert c.court == "نقض" and c.division == "مدنية" and c.chamber_raw == "المدنية الثالثة"
    assert (c.decision_number, c.basis_number, c.decision_date) == ("1890", "2914", "1997-11-09")
    assert c.publication == "سجلات النقض"
    assert c.identity_key() == "نقض|1890|1997|2914"
    assert c.confidence >= 0.9


def test_inline_general_assembly_with_mohamoun_issue():
    c = parse_citation("نقض سوري هيئة عامة أساس 328 قرار 167 تاريخ 6/11/1994 – المصدر : مجلة المحامون العددان 11 – 12 لعام 1994")
    assert c.court == "هيئة_عامة_نقض"
    assert (c.decision_number, c.basis_number, c.decision_date) == ("167", "328", "1994-11-06")
    assert (c.publication, c.pub_issue, c.pub_year) == ("المحامون", "11-12", 1994)
    assert authority_rank(c) == 1


def test_inline_mukhasama():
    c = parse_citation("نقض سوري مخاصمة أساس 1217 قرار 260 تاريخ 17/6/2008 – المصدر : مجلة المحامون العددان 9 – 10 لعام 2009")
    assert c.court == "نقض" and c.case_kind == "مخاصمة" and c.division == "مدنية"
    assert authority_rank(c) == 5


def test_inline_ordinal_chamber_only():
    c = parse_citation("نقض سوري الغرفة الأولى أساس 771 قرار 689 تاريخ 14/11/ 2007 – المصدر : مجلة المحامون العددان 7 – 8 لعام 2009")
    assert c.chamber_raw == "الأولى" and c.division == "مدنية"
    assert "chamber_ordinal_without_name" in c.warnings
    assert c.decision_date == "2007-11-14"


# ---------------------------------------------------------------- الشكل 3 (موسوعات)
def test_encyclopedia_form_rule_number_is_not_identity():
    c = parse_citation("قرار 1582 / 2002 – أساس 1916 – محكمة النقض – الدوائر المدنية – سورية قاعدة 137 – م. القانون 2002 – القسم الاول –")
    assert (c.decision_number, c.decision_year, c.basis_number) == ("1582", 2002, "1916")
    assert c.court == "نقض" and c.division == "مدنية"
    assert c.rule_number == "137" and c.publication == "القانون" and c.pub_year == 2002
    assert c.identity_key() == "نقض|1582|2002|1916"


def test_encyclopedia_basis_bidoun():
    c = parse_citation("قرار 440 / 1965 – أساس بدون – محاكم النقض – سورية قاعدة 747 – اجتهادات قانون البينات – عطري –")
    assert c.decision_number == "440" and c.decision_year == 1965 and c.basis_number is None
    assert c.publication == "عطري"
    assert c.identity_key() == "نقض|440|1965|"


# ---------------------------------------------------------------- الشكل 6 (إدارية عليا)
def test_supreme_administrative_form():
    c = parse_citation("(القرار رقم 671 في الطعن 1391 لعام 1995 مجموعة المبادئ القانونية التي قررتها المحكمة الإدارية العليا صفحة 57 لعام 1995)")
    assert c.court == "ادارية_عليا"
    assert (c.decision_number, c.appeal_number, c.decision_year) == ("671", "1391", 1995)
    assert c.publication == "مجموعة المبادئ الإدارية" and c.pub_page == "57"
    assert authority_rank(c) == 4


def test_supreme_administrative_slashed_numbers():
    c = parse_citation("(القرار رقم /38/ في الطعن /18/ لعام 1995 مجموعة المبادئ القانونية التي قررتها المحكمة الإدارية العليا صفحة 1 لعام 1995)")
    assert (c.decision_number, c.appeal_number, c.decision_year) == ("38", "18", 1995)


# ---------------------------------------------------------------- الشكل 7 (بالمادة)
def test_case_kind_short_basis_year():
    c = parse_citation("(جنحة أساس 2215 / 980 قرار 293 تاريخ 8 / 2 / 1981)")
    assert c.court == "نقض" and c.case_kind == "جنحة" and c.division == "جزائية"
    assert (c.basis_number, c.basis_year, c.decision_number, c.decision_date) == ("2215", 1980, "293", "1981-02-08")


def test_military_chamber_as_case_kind():
    c = parse_citation("(نقض سوري ـ عسكرية أساس 1807 قرار 3 تاريخ 10 / 6 / 1981)")
    assert c.case_kind == "عسكرية" and c.division == "جزائية" and c.decision_number == "3"


def test_economic_security():
    c = parse_citation("(أمن اقتصادي أساس 50 قرار 40 تاريخ 27 / 4 / 1985)")
    assert c.case_kind == "امن اقتصادي" and c.division == "جزائية" and c.decision_date == "1985-04-27"


# ---------------------------------------------------------------- الشكل 1 (المحامون البنيوي)
MOHAMOUN = """الصفحة : 126 محامون العدد /1-2/ لعام 2010

القاعدة: 52

القضية : 2106 أساس لعام 2008

قرار : 1904 لعام 2008

تاريخ : 30/6/2008

المبدأ: بينات – شهادة – أقوال متناقضة .

الأقوال المتناقضة للشاهد يجب أن تخضع إلى المناقشة والتمحيص من لدن المحكمة .

الصفحة : 127 محامون العدد /1-2/ لعام 2010

القاعدة: 53

القضية : 2244 أساس لعام 2008

قرار : 2016 لعام 2008

تاريخ : 21/7/2008

المبدأ: أصول – اختصاص مكاني – نظام عام .

الاختصاص المكاني في القضايا الجزائية من النظام العام .
"""


def test_structured_mohamoun_blocks():
    cs = parse_text(MOHAMOUN)
    assert len(cs) == 2
    a, b = cs
    assert (a.decision_number, a.decision_year, a.basis_number, a.basis_year, a.decision_date) == ("1904", 2008, "2106", 2008, "2008-06-30")
    assert a.rule_number == "52"
    assert a.title_keywords == "بينات – شهادة – أقوال متناقضة"
    assert a.principle_text.startswith("الأقوال المتناقضة للشاهد")
    assert a.is_exportable()
    assert b.decision_number == "2016" and b.title_keywords.startswith("أصول – اختصاص مكاني")
    assert b.principle_text == "الاختصاص المكاني في القضايا الجزائية من النظام العام ."


# ---------------------------------------------------------------- نص مقالي: المبدأ قبل الاستشهاد
ARTICLE = """[ تقدير ما إذا كان الحجز الاحتياطي محقاً أم لا هو أمر موضوعي تستقل به محاكم الأساس و لا رقابة عليها من قبل محكمة النقض ما دام الاستخلاص سائغاً. ]

( نقض سوري – الغرفة المدنية الثالثة – القضية 2054 أساس لعام 1999- قرار 1614 لعام 1999- تاريخ 2/5/1999 – سجلات محكمة النقض . )

[ استقر الاجتهاد على أن القضاء العادي هو المختص للنظر في دعوى قصر الحجز الاحتياطي الذي توقعه وزارة المالية. ]

( نقض سوري – الغرفة المدنية الثالثة – القضية 931 أساس لعام 1996- قرار 764 لعام 1996- تاريخ 23/9/1996– سجلات محكمة النقض . )
"""


def test_article_principle_precedes_citation():
    cs = parse_text(ARTICLE)
    assert [c.decision_number for c in cs] == ["1614", "764"]
    assert cs[0].basis_number == "2054" and cs[0].basis_year == 1999
    assert cs[0].principle_text.startswith("تقدير ما إذا كان الحجز الاحتياطي")
    assert cs[1].principle_text.startswith("استقر الاجتهاد على أن القضاء العادي")
    assert all(c.is_exportable() for c in cs)


def test_dedup_same_decision_two_forms():
    txt = ("نقض سوري هيئة عامة أساس 328 قرار 167 تاريخ 6/11/1994 – المصدر : مجلة المحامون العددان 11 – 12 لعام 1994\n"
           "أحكام الهيئة العامة بمنزلة القانون وعدم إتباعها خطأ مهني جسيم.\n\n"
           "(هيئة عامة أساس 328 قرار 167 تاريخ 6/11/1994)\n")
    cs = parse_text(txt)
    assert len([c for c in cs if c.identity_key() == "هيئة_عامة_نقض|167|1994|328"]) == 1


# ---------------------------------------------------------------- الروابط والعدول
def test_article_refs():
    r = extract_article_refs("مخالفة أحكام المادة 262 من قانون الأصول المدنية … وفقاً لأحكام المادة /162/ من القانون المدني … (المادة 250 مكرر أصول مدنية)")
    got = {(x["article_number"], x["law_alias"]) for x in r}
    assert ("162", "القانون المدني") in got
    assert ("250", "أصول المحاكمات") in got
    assert any(a == "262" for a, _ in got)


def test_overruling_extraction_two_targets():
    t = ("لذلك تقرر بالاجماع الحكم بما يلي: 1 ـ العدول عن الاجتهاد الوارد في القرار 773 / 512 جناية تاريخ 8 / 7 / 1965 "
         "والقرار رقم 2197 / 1881 جنحة تاريخ 30 تموز 1977 على الوجه المبين في الأسباب. 2 ـ تعميم هذا القرار")
    ts = extract_overrulings(t)
    assert len(ts) == 2
    assert (ts[0].decision_number, ts[0].basis_number, ts[0].case_kind, ts[0].decision_date) == ("773", "512", "جناية", "1965-07-08")
    assert (ts[1].decision_number, ts[1].basis_number, ts[1].case_kind) == ("2197", "1881", "جنحة")


def test_overruling_by_date_only():
    ts = extract_overrulings("حكمت الهيئة العامة بالاجماع: 1 ـ العدول عن اجتهاد هذه المحكمة المؤرخ في 2 / 5 / 1965 وإقرار المبدأ القائل")
    assert ts and ts[0].decision_date == "1965-05-02"


# ---------------------------------------------------------------- الهجرة 012
def test_migration_012_tables_exist(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"decisions", "principles", "citations", "decision_relations", "principle_articles"} <= names
    assert db.execute("PRAGMA user_version").fetchone()[0] >= 12
    db.execute("INSERT INTO decisions(court,decision_number,decision_year,identity_key) VALUES('نقض','1','1999','نقض|1|1999|')")
    with pytest.raises(Exception):
        db.execute("INSERT INTO decisions(court,decision_number,decision_year,identity_key) VALUES('نقض','1','1999','نقض|1|1999|')")


def test_no_hallucination_on_plain_text():
    c = parse_citation("هذا نص عادي لا يحتوي على أي استشهاد قضائي ولا أرقام.")
    assert c.court is None and c.decision_number is None and c.confidence < 0.4
    assert parse_text("فقرة عادية.\n\nفقرة ثانية بلا اجتهاد.") == []


# ------------------------------------------------- صيغة «القضية/قرار/تاريخ» (ف٥)
# مجموعات الهيئة العامة القديمة (القزاز ونحوها) بلا كلمة «أساس» ولا لفظ جهة:
# «(القضية 368 قرار 462 تاريخ 3/6/2002 المنشور في مجلة المحامون العدد 7 2004)»
QAD = "(القضية 368 قرار 462 تاريخ 3/6/2002 المنشور في مجلة المحامون العدد السابع 2004)"


def test_qadiya_dialect_inferred_court_with_flag():
    c = parse_citation(QAD)
    assert c.court == "نقض"                      # الجهة مستدلة من الصيغة القياسية
    assert "court_inferred_collection" in c.warnings
    assert c.decision_number == "462" and c.basis_number == "368"
    assert c.decision_date == "2002-06-03" and c.publication == "المحامون"
    assert c.identity_key() == "نقض|462|2002|368"


def test_qadiya_dialect_with_arabic_indic_digits():
    c = parse_citation("(القضية ٣٦٨ قرار ٤٦٢ تاريخ ٣/٦/٢٠٠٢)")
    assert c.decision_number == "462" and c.basis_number == "368"
    assert c.decision_date == "2002-06-03"


def test_qadiya_inline_principle_exportable():
    text = ("إن دعوى المخاصمة ذات طبيعة خاصة ليست من طرق الطعن ولا امتداداً للخصومة، "
            "وعلى هذا الأساس فإن من واجب مدعي المخاصمة أن يرفق استدعاءه بالوثائق.\n"
            + QAD)
    cs = [c for c in parse_text(text) if c.is_exportable()]
    assert len(cs) == 1
    assert cs[0].identity_key() == "نقض|462|2002|368"
    assert cs[0].principle_text and len(cs[0].principle_text) >= 40
