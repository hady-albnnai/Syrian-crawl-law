"""B-1: قائمة الفجوات المعلومة."""
import config
import database
import pytest
from missing_targets import missing_targets, missing_target_queries


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "m.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_targets_ranked_by_evidence_and_exclude_known(db):
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year,parent_identity)"
               " VALUES (1,'a','ق','يلغى القانون رقم 91 لعام 1959. تعدل المادة 3 من القانون رقم 7 لعام 1980. وفق القانون رقم 5 لعام 2010.','active','instrument','القانون:1:2020',1,2020,'المرسوم التشريعي:98:1961')")
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year)"
               " VALUES (2,'b','ق','نص','active','instrument','القانون:5:2010',5,2010)")
    db.execute("INSERT INTO law_amendments(amending_doc_id,target_identity,action) VALUES (1,'القانون:91:1959','repeal')")
    db.execute("""CREATE TABLE article_amendments (id INTEGER PRIMARY KEY, amending_doc_id INTEGER, target_identity TEXT,
                  article_number TEXT, action TEXT, context TEXT, created_at TEXT)""")
    db.execute("INSERT INTO article_amendments(amending_doc_id,target_identity,article_number,action) VALUES (1,'القانون:7:1980','3','amend')")
    db.commit()
    t = missing_targets(db)
    keys = [x["identity_key"] for x in t]
    assert "القانون:5:2010" not in keys  # موجود
    assert keys[0] == "القانون:91:1959" and t[0]["score"] == 6  # إلغاء 5 + ذكر 1
    assert keys[1] == "القانون:7:1980" and t[1]["score"] == 5   # مادة 4 + ذكر 1
    assert "المرسوم التشريعي:98:1961" in keys
    assert t[0]["why"][0] == "يُلغيه القانون:1:2020"
    assert missing_target_queries(db)[0] == "القانون رقم 91 لعام 1959 سوريا نص كامل"
