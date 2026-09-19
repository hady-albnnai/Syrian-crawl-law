"""A-3: حالة النفاذ بسببها، والزمن بالتاريخ الكامل حين يتوفر."""
import config
import database
import pytest
from law_status import compute_legal_statuses


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def _doc(db, i, key, year, issue=None, status="active"):
    t, n, y = key.split(":")
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year,issue_date)"
               " VALUES (?,?,?,?,?,?,?,?,?,?)", (i, f"d{i}", key, "المادة 1", status, "instrument", key, int(n), int(y), issue))


def test_reason_names_repealing_instrument_with_date(db):
    _doc(db, 1, "القانون:37:1966", 1966, "1966-05-16")
    _doc(db, 2, "القانون:3:2013", 2013, "2013-01-20")
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (2,'القانون:37:1966','repeal')")
    db.commit()
    compute_legal_statuses(db)
    r = db.execute("SELECT legal_status, legal_status_reason FROM documents WHERE id=1").fetchone()
    assert r["legal_status"] == "ملغى"
    assert r["legal_status_reason"] == "أُلغي بـ القانون:3:2013 (2013-01-20)"
    r2 = db.execute("SELECT legal_status, legal_status_reason FROM documents WHERE id=2").fetchone()
    assert (r2["legal_status"], r2["legal_status_reason"]) == ("ساري", "لا دليل تعديل أو إلغاء في المتن المحصود")


def test_same_year_but_earlier_full_date_cannot_amend(db):
    # معدِّل مزعوم صدر 2005-01-03، المستهدَف صدر 2005-06-09 — نفس السنة، ترتيب خاطئ
    _doc(db, 1, "المرسوم التشريعي:30:2005", 2005, "2005-06-09")
    _doc(db, 2, "القانون:2:2005", 2005, "2005-01-03")
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (2,'المرسوم التشريعي:30:2005','amend')")
    db.commit()
    compute_legal_statuses(db)
    assert db.execute("SELECT legal_status FROM documents WHERE id=1").fetchone()[0] == "ساري"


def test_excluded_document_is_not_evidence(db):
    _doc(db, 1, "القانون:12:2001", 2001)
    _doc(db, 2, "المرسوم التشريعي:62:2013", 2013, status="excluded")
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (2,'القانون:12:2001','repeal')")
    db.commit()
    compute_legal_statuses(db)
    assert db.execute("SELECT legal_status FROM documents WHERE id=1").fetchone()[0] == "ساري"


def test_repeal_reason_listed_before_amend(db):
    _doc(db, 1, "القانون:1:1990", 1990)
    _doc(db, 2, "القانون:5:2000", 2000)
    _doc(db, 3, "القانون:9:2010", 2010)
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (2,'القانون:1:1990','amend')")
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (3,'القانون:1:1990','repeal')")
    db.commit()
    compute_legal_statuses(db)
    r = db.execute("SELECT legal_status_reason FROM documents WHERE id=1").fetchone()[0]
    assert r.startswith("أُلغي بـ القانون:9:2010 (2010)") and "عُدّل بـ القانون:5:2000 (2000)" in r


def test_partial_repeal_forms_from_bunud_corpus_are_amend():
    # repealed4 (2026-09-19): ثلاث صيغ حقيقية كانت تعلّم الصك كله «ملغى»
    from law_status import classify_reference
    from law_identity import extract_law_references
    for t in ("المادة 1 تلغى نصوص المواد / 7 و 14 و 23 / من المرسوم التشريعي رقم / 81 / المؤرخ في 5/5/1947 وتستبدل",
              "المادة 4 ينهى العمل بأحكام المادتين /1 و 2/ من القانون رقم /4/ تاريخ 7/1/2001 م.",
              "ويلغى كل نص مخالف في المرسوم التشريعي رقم 35 لعام 2001"):
        refs = extract_law_references(t)
        assert refs and classify_reference(refs[0]) == "amend", t
    refs = extract_law_references("المادة 20 يلغى المرسوم التشريعي رقم 59 لعام 2003")
    assert classify_reference(refs[0]) == "repeal"
