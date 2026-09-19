# -*- coding: utf-8 -*-
"""ف٧ — أجزاء الصك الواحد + الياء المقصورة + العنوان العام + حسم التناقض (#19).

النصوص حرفية من unidentified2.txt (قاعدة المالك 2026-09-19).
"""
import config
import database
import pytest

from law_identity import (generic_title_preamble_number,
                          merge_title_preamble_identity, title_only_identity)
from law_parts import article_range, group_parts, link_parts


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


# --- الياء المقصورة (#277) ---------------------------------------------------
def test_egyptian_yaa_in_type_name():
    fb = title_only_identity("المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني")
    assert fb["law_number"] == 30


def test_alif_maqsura_at_word_end_untouched():
    # «إلى» و«على» لا تُمسّ — النمط يشترط حرفاً بعدها
    fb = title_only_identity("قانون يشير إلى رقم 5 لعام 2001")
    assert fb["law_year"] == 2001


# --- عنوان عام + ديباجة (#177) ------------------------------------------------
def test_generic_title_takes_preamble_number_partially():
    g = generic_title_preamble_number(
        "وثيقة قانونية سورية",
        "القانون رقم 38 المادة 77- بعد تسجيل البيانات التفصيلية ، تقوم دائرة الجمارك")
    assert (g["doc_type"], g["law_number"], g["law_year"]) == ("القانون", 38, None)
    assert "identity_key" not in g


def test_generic_title_requires_number_at_very_start():
    assert generic_title_preamble_number(
        "وثيقة قانونية سورية",
        "تُطبَّق أحكام هذا الفصل مع مراعاة القانون رقم 38") is None


def test_non_generic_title_not_touched():
    assert generic_title_preamble_number("قانون الجمارك", "القانون رقم 38") is None


# --- حسم التناقض (#19) --------------------------------------------------------
def test_clash_resolved_to_preamble_when_enacting_head():
    got = merge_title_preamble_identity(
        "المرسوم التشريعي رقم 6: قانون مكافحة الإتجار بالبشر- 2010",
        "المرسوم التشريعي رقم (3) رئيس الجمهورية بناء على أحكام الدستور يرسم ما يلي (الفصل الأول)")
    assert got["identity_key"] == "المرسوم التشريعي:3:2010"
    assert got["identity_confidence"] == "preamble_over_title"
    assert got["title_number_conflict"] == 6


def test_clash_without_enacting_head_stays_unresolved():
    assert merge_title_preamble_identity(
        "المرسوم التشريعي رقم 6: قانون س 2010",
        "المرسوم التشريعي رقم (3) يشير إلى أحكام") is None


# --- تجميع الأجزاء -------------------------------------------------------------
def test_article_range():
    assert article_range("المادة/8/ نص المادة 9 نص المادة 12") == (8, 12)
    assert article_range("لا مواد هنا") is None


def _doc(i, num, text, year=None, dt="المرسوم التشريعي"):
    return {"id": i, "doc_type": dt, "number": num, "year": year,
            "identity_key": None, "text": text}


def test_group_parts_orders_by_first_article_and_links_rest():
    docs = [
        _doc(280, 30, "المادة/20/ … المادة 25"),
        _doc(277, 30, "المادة/8/ 00 تضع الدوائر العقارية … المادة 12"),
        _doc(282, 30, "المادة/30/ … المادة 33", year=1966),
    ]
    g = group_parts(docs)
    assert len(g) == 1
    assert g[0]["head_id"] == 277
    assert g[0]["part_ids"] == [280, 282]
    assert g[0]["year"] == 1966  # ورثها من الجزء الوحيد الذي يحملها


def test_large_overlap_is_duplicate_not_part():
    docs = [_doc(1, 30, "المادة 1 … المادة 40"), _doc(2, 30, "المادة 1 … المادة 40")]
    assert group_parts(docs) == []


def test_different_years_same_number_never_grouped():
    docs = [_doc(1, 30, "المادة 1 … المادة 5", year=1966),
            _doc(2, 30, "المادة 6 … المادة 9", year=2005)]
    assert group_parts(docs) == []


def test_single_member_not_a_group():
    assert group_parts([_doc(1, 30, "المادة 1 … المادة 5")]) == []


def test_link_parts_writes_part_of_and_resets(db):
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key)"
               " VALUES (277,'المرسوم التشريعى رقم/30','المادة/8/ نص المادة 12','active','instrument',30,NULL,NULL)")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key)"
               " VALUES (280,'المرسوم التشريعى رقم/30','المادة/20/ نص المادة 25','active','instrument',30,1966,'المرسوم التشريعي:30:1966')")
    db.commit()
    rep = link_parts(db)
    assert (rep["groups"], rep["parts_linked"]) == (1, 1)
    row = db.execute("SELECT part_of FROM documents WHERE id=280").fetchone()
    assert row["part_of"] == 277
    head = db.execute("SELECT year FROM documents WHERE id=277").fetchone()
    assert head["year"] == 1966
    # إعادة التشغيل تصفّر ثم تعيد — لا روابط يتيمة
    db.execute("UPDATE documents SET status='superseded' WHERE id=280")
    db.commit()
    rep2 = link_parts(db)
    assert rep2["parts_linked"] == 0
    assert db.execute("SELECT part_of FROM documents WHERE id=280").fetchone()["part_of"] is None


def test_exporter_folds_parts_under_head(db, tmp_path):
    from exporter import build_package
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key,part_of)"
               " VALUES (277,'المرسوم التشريعي رقم 30','المادة 1 أ المادة 2 ب','active','instrument',30,1966,'المرسوم التشريعي:30:1966',NULL)")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key,part_of)"
               " VALUES (280,'المرسوم التشريعى رقم/30','المادة 3 ج المادة 4 د','active','instrument',30,1966,NULL,277)")
    for n, d in [("3", 280), ("1", 277), ("4", 280), ("2", 277)]:
        db.execute("INSERT INTO articles(doc_id,article_number,text) VALUES (?,?,?)", (d, n, "نص " + n))
    db.commit()
    db.commit()
    rep = build_package(db_path=str(config.DB_PATH), out_dir=str(tmp_path / "pkg"),
                        min_articles=1, with_manifest=False)
    assert rep["docs"] == 1
    assert rep["folded_parts"] == 1
    md = next((tmp_path / "pkg" / "markdown").glob("*.md")).read_text(encoding="utf-8")
    assert md.index("نص 1") < md.index("نص 2") < md.index("نص 3") < md.index("نص 4")
