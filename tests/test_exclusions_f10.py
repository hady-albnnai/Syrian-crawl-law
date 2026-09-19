"""ف١٠: استبعادات المالك — وسم لا حذف، ولا عودة عند إعادة الزحف."""
import config
import database
import pytest
from exclusions import EXCLUSIONS, apply_exclusions, exclusion_reason


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_every_exclusion_has_reason():
    assert all(e["reason"] for e in EXCLUSIONS)


def test_reason_matches_owner_titles_not_others():
    assert exclusion_reason("دستور الجمهورية العربية السورية،الجمهورية العربية السورية")
    assert exclusion_reason("المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني")
    assert exclusion_reason("قانون العقوبات رقم/ 148/ لعام /1949/") is None
    assert exclusion_reason("المرسوم التشريعي رقم 30 لعام 2005 المصرف الزراعي التعاوني") is None


def test_apply_marks_excluded_and_archives_copy(db):
    T = "المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني"
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status) VALUES (281,'a',?,'المادة 3','active')", (T,))
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,part_of) VALUES (277,'b',?,'المادة 8','active',281)", (T,))
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status) VALUES (1,'c','قانون العقوبات رقم 148 لعام 1949','المادة 1','active')")
    db.commit()
    rep = apply_exclusions(db)
    st = {r[0]: r[1] for r in db.execute("SELECT id, status FROM documents")}
    assert st == {281: "excluded", 277: "excluded", 1: "active"}
    assert db.execute("SELECT COUNT(*) FROM document_versions WHERE superseded_reason LIKE 'excluded:%'").fetchone()[0] >= 1
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3   # لا حذف
    assert apply_exclusions(db)["excluded"] == 0   # idempotent


def test_crawler_checks_exclusions_before_save():
    import crawler
    src = open(crawler.__file__, encoding="utf-8").read()
    assert "exclusion_reason(title)" in src
