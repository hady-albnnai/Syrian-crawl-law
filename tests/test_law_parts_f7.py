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


def _doc(i, num, text, year=None, dt="المرسوم التشريعي", title="", key=None):
    return {"id": i, "title": title, "doc_type": dt, "number": num, "year": year,
            "identity_key": key, "text": text}


# --- الحالات الحقيقية من parts_explain.txt (قاعدة المالك 2026-09-19) ----------
def test_undated_same_title_parts_cluster_by_title_stem():
    # المرسوم 30 ×4 بلا سنة، مادة واحدة لكل جزء، عنوان متطابق — ورقم 30 نفسه
    # للمحاماة 2010 والمرسوم 2012 (لا يُخلطان)
    T = "المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني"
    docs = [
        _doc(4, 30, "المادة 2 … المادة 42", year=2010, dt="القانون", title="قانون تنظيم مهنة المحاماة لعام 2010", key="القانون:30:2010"),
        _doc(204, 30, "المادة 1 … المادة 146", year=2012, title="المرسوم التشريعي رقم 30 للعام 2012", key="المرسوم التشريعي:30:2012"),
        _doc(277, 30, "المادة/8/ نص", title=T), _doc(278, 30, "المادة /9/ نص", title=T),
        _doc(280, 30, "المادة 1 نص", title=T), _doc(282, 30, "المادة 6 نص", title=T),
    ]
    gs = group_parts(docs)
    parts_groups = [g for g in gs if 277 in g["part_ids"] or g["head_id"] == 277]
    assert len(parts_groups) == 1
    g = parts_groups[0]
    assert set([g["head_id"]] + g["part_ids"]) == {277, 278, 280, 282}
    assert g["year"] is None and g["identity_key"] is None   # لا اختراع
    assert not any({4, 204} & set([x["head_id"]] + x["part_ids"]) for x in parts_groups)


def test_contained_fragments_fold_under_full_text():
    # قانون الجمارك: #96 كامل (1–298) + شذرات (77–188)(196–272)(233–298) بعنوان عام
    full = "قانون الجمارك رقم 38 لعام 2006،الجمهورية العربية السورية"
    docs = [
        _doc(96, 38, " ".join(f"المادة {i} ن" for i in range(1, 299)), year=2006, dt="القانون", title=full, key="القانون:38:2006"),
        _doc(177, 38, "القانون رقم 38 " + " ".join(f"المادة {i} ن" for i in range(77, 189)), dt="القانون", title="وثيقة قانونية سورية"),
        _doc(178, 38, "القانون رقم 38 " + " ".join(f"المادة {i} ن" for i in range(196, 273)), dt="القانون", title="وثيقة قانونية سورية"),
    ]
    gs = group_parts(docs)
    assert len(gs) == 1 and gs[0]["head_id"] == 96
    assert set(gs[0]["part_ids"]) == {177, 178}
    assert set(gs[0]["contained"]) == {177, 178}
    assert gs[0]["year"] == 2006 and gs[0]["identity_key"] == "القانون:38:2006"


def test_undated_joins_dated_only_with_shared_keyword():
    # البينات: #140 (1–159 بلا سنة) ينضم إلى #40 (359/1947) بكلمة «البينات»
    docs = [
        _doc(40, 359, " ".join(f"المادة {i} ن" for i in range(1, 57)), year=1947, dt="القانون", title="قانون البينات رقم 359 في المواد المدنية والتجارية", key="القانون:359:1947"),
        _doc(140, 359, " ".join(f"المادة {i} ن" for i in range(1, 160)), dt="القانون", title="قانون البينات 359 تاريخ 10"),
    ]
    gs = group_parts(docs)
    assert len(gs) == 1 and gs[0]["head_id"] == 140      # الأوسع تغطية هو الرأس
    assert gs[0]["year"] == 1947 and gs[0]["identity_key"] == "القانون:359:1947"


def test_undated_without_shared_keyword_stays_apart():
    # الأحوال الشخصية 59 (بلا سنة) ≠ المرسوم التشريعي 59/2008
    docs = [
        _doc(121, 59, " ".join(f"المادة {i} ن" for i in range(2, 169)), year=2008, title="المرسوم التشريعي رقم 59 للعام 2008", key="المرسوم التشريعي:59:2008"),
        _doc(147, 59, " ".join(f"المادة {i} ن" for i in range(1, 1121)), title="قانون الأحوال الشخصية الصادر بالمرسوم التشريعي رقم 59"),
    ]
    assert group_parts(docs) == []


def test_law_and_legislative_decree_are_compatible_types():
    # قانون العقوبات 148/1949: «القانون» و«المرسوم التشريعي» تسميتان لصك واحد
    docs = [
        _doc(83, 148, "المادة 1 … المادة 756", year=1949, dt="المرسوم التشريعي", title="القانون الجنائي (الصادر بالمرسوم التشريعي رقم 148/1949)"),
        _doc(104, 148, "المادة 1 … المادة 756", year=1949, dt="القانون", title="قانون العقوبات رقم/ 148/ لعام /1949/"),
    ]
    assert len(group_parts(docs)) == 1


def test_different_years_same_number_never_grouped():
    docs = [_doc(1, 30, "المادة 1 … المادة 5", year=1966),
            _doc(2, 30, "المادة 6 … المادة 9", year=2005)]
    assert group_parts(docs) == []


def test_single_member_not_a_group():
    assert group_parts([_doc(1, 30, "المادة 1 … المادة 5")]) == []


def test_link_parts_writes_part_of_and_resets(db):
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key)"
               " VALUES (277,'المرسوم التشريعى رقم/30 المتعلق بالمصرف الزراعي','المادة/8/ نص المادة 12','active','instrument',30,NULL,NULL)")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key)"
               " VALUES (280,'المرسوم التشريعي رقم 30 لعام 1966 المتعلق بالمصرف الزراعي','المادة/20/ نص المادة 25','active','instrument',30,1966,'المرسوم التشريعي:30:1966')")
    db.commit()
    rep = link_parts(db)
    assert (rep["groups"], rep["parts_linked"]) == (1, 1)
    # الرأس = الأوسع تغطية (280: 20–25 أوسع من 277: 8–12)
    row = db.execute("SELECT part_of FROM documents WHERE id=277").fetchone()
    assert row["part_of"] == 280
    head = db.execute("SELECT year, identity_key FROM documents WHERE id=280").fetchone()
    assert head["year"] == 1966 and head["identity_key"] == "المرسوم التشريعي:30:1966"
    # إعادة التشغيل تصفّر ثم تعيد — لا روابط يتيمة
    db.execute("UPDATE documents SET status='superseded' WHERE id=280")
    db.commit()
    rep2 = link_parts(db)
    assert rep2["parts_linked"] == 0
    assert db.execute("SELECT part_of FROM documents WHERE id=277").fetchone()["part_of"] is None


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


def test_clash_resolved_when_preamble_has_newlines():
    got = merge_title_preamble_identity(
        "المرسوم التشريعي رقم 6: قانون مكافحة الإتجار بالبشر- 2010",
        "المرسوم التشريعي رقم (3)\nرئيس الجمهورية\nبناء على أحكام الدستور\nيرسم ما يلي")
    assert got and got["identity_key"] == "المرسوم التشريعي:3:2010"


def test_explain_parts_reports_overlap(db):
    from law_parts import explain_parts
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number)"
               " VALUES (1,'المرسوم رقم 30 التعاوني','المادة 1 المادة 40','active','instrument',30)")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number)"
               " VALUES (2,'المرسوم رقم 30 التعاوني','المادة 2 المادة 40','active','instrument',30)")
    db.commit()
    txt = "\n".join(explain_parts(db))
    assert "رقم 30: 2 وثيقة" in txt and "مجموعة: رأس #1" in txt and "محتواة=[2]" in txt


# --- جولة parts_explain2.txt (2026-09-19، بعد d99558e) --------------------------
def test_same_number_year_different_subjects_not_grouped():
    # 15/2008: #44 إحداث مؤسسة عامة (2–14) و#100 التطوير العقاري (1–92) صكّان
    docs = [
        _doc(44, 15, " ".join(f"المادة {i} ن" for i in range(2, 15)), year=2008,
             title="المرسوم التشريعي 15 لعام 2008 إحداث المؤسسة العامة للإسكان", key="المرسوم التشريعي:15:2008"),
        _doc(100, 15, " ".join(f"المادة {i} ن" for i in range(1, 93)), year=2008, dt="القانون",
             title="القانون رقم 15 لعام 2008 بشأن التطوير والاستثمار العقاري", key="القانون:15:2008"),
    ]
    assert group_parts(docs) == []


def test_executive_regulation_never_heads_its_law():
    # 24/2003: التعليمات التنفيذية (#101، 12–921) لا ترأس قانون ضريبة الدخل (#102)
    docs = [
        _doc(101, 24, " ".join(f"المادة {i} ن" for i in range(12, 922)), year=2003, dt="القانون",
             title="التعليمات التنفيذية لقانون الضريبة على الدخل رقم /24/ لعام 2003"),
        _doc(102, 24, " ".join(f"المادة {i} ن" for i in range(1, 566)), year=2003, dt="القانون",
             title="القانون رقم 24 لعام 2003 بشأن ضريبة الدخل", key="القانون:24:2003"),
    ]
    assert group_parts(docs) == []


def test_two_copies_same_title_same_year_still_grouped():
    # التبغ 16/1935: #22 (1–31) و#103 (1–95) عنوان واحد → نسختان لصك واحد
    T = "نظام احتكار التبغ والتنباك الصادر بالقرار رقم 16 لعام 1935"
    docs = [_doc(22, 16, " ".join(f"المادة {i} ن" for i in range(1, 32)), year=1935, title=T),
            _doc(103, 16, " ".join(f"المادة {i} ن" for i in range(1, 96)), title=T)]
    gs = group_parts(docs)
    assert len(gs) == 1 and gs[0]["head_id"] == 103 and gs[0]["contained"] == [22]


def test_reidentify_clears_key_contradicting_explicit_title_number(db):
    # #281: عنوان «رقم/30 … المصرف الزراعي» ومفتاح مخزَّن 23/2002 من إحالة
    from law_identity import reidentify_documents
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,number,year,identity_key,identity_confidence)"
               " VALUES (281,'المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني',"
               "'المادة 3 وفق القانون رقم 23 لعام 2002 المادة 100','active','instrument',23,2002,'القانون:23:2002','body')")
    st = reidentify_documents(db)
    r = db.execute("SELECT number, year, identity_key FROM documents WHERE id=281").fetchone()
    assert st.get("corrected_key") == 1
    assert (r["number"], r["year"], r["identity_key"]) == (30, None, None)


# --- جولة parts_explain3.txt -----------------------------------------------------
def test_sparse_wide_range_is_not_containment_evidence():
    # #281: مادتان فقط (3 و100) بلا سنة، عنوان المصرف الزراعي — لا ينطوي تحت 30/2012 (1–146)
    T = "المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني"
    docs = [
        _doc(204, 30, " ".join(f"المادة {i} ن" for i in range(1, 147)), year=2012,
             title="المرسوم التشريعي رقم 30 للعام 2012", key="المرسوم التشريعي:30:2012"),
        _doc(281, 30, "المادة 3 نص المادة 100 نص", title=T),
        _doc(282, 30, "المادة 6 نص يشير إلى المرسوم التشريعي 30 للعام 2012 القاضي بالتنظيم", title=T),
        _doc(280, 30, "المادة 1 نص", title=T),
    ]
    gs = group_parts(docs)
    assert len(gs) == 1
    assert set([gs[0]["head_id"]] + gs[0]["part_ids"]) == {280, 281, 282}
    assert gs[0]["year"] is None
