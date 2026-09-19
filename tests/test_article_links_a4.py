"""A-4: تعديل/إلغاء على مستوى المادة."""
import json
import config
import database
import pytest
from article_links import extract_article_amendments, rebuild_article_links


def test_single_article_amend():
    r = extract_article_amendments("تعدل المادة 15 من القانون رقم 148 لعام 1949 وتصبح")
    assert r == [{"target_identity": "القانون:148:1949", "article_number": "15",
                  "action": "amend", "context": "تعدل المادة 15 من القانون رقم 148 لعام 1949"}]


def test_dual_repeal_and_range():
    r = extract_article_amendments("تلغى المادتان 3 و4 من المرسوم التشريعي رقم 61 لعام 1950.")
    assert [(x["article_number"], x["action"]) for x in r] == [("3", "repeal"), ("4", "repeal")]
    r = extract_article_amendments("يستعاض عن نص المواد 10 إلى 13 من القانون رقم 84 لعام 1949 بما يلي")
    assert [x["article_number"] for x in r] == ["10", "11", "12", "13"]


def test_bis_and_named_law_bridge():
    r = extract_article_amendments(
        "يعدل نص المادة /5/ مكرر من قانون العقوبات الصادر بالمرسوم التشريعي رقم 148 لعام 1949")
    assert r[0]["article_number"] == "5 مكرر" and r[0]["target_identity"] == "المرسوم التشريعي:148:1949"


def test_self_and_cross_sentence_ignored():
    t = "تعدل المادة 2 من هذا القانون. ويلغى القانون رقم 3 لعام 2000"
    assert extract_article_amendments(t, "القانون:1:2001") == []
    assert extract_article_amendments("تعدل المادة 2 من القانون رقم 1 لعام 2001", "القانون:1:2001") == []


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "a.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_rebuild_marks_target_articles(db):
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year)"
               " VALUES (1,'a','قانون العقوبات','المادة 1 نص. المادة 15 نص قديم.','active','instrument','المرسوم التشريعي:148:1949',148,1949)")
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year)"
               " VALUES (2,'b','قانون 15/2022','المادة 1 تعدل المادة 15 من المرسوم التشريعي رقم 148 لعام 1949 وتلغى المادة 1 من المرسوم التشريعي رقم 148 لعام 1949','active','instrument','القانون:15:2022',15,2022)")
    for n in ("1", "15"):
        db.execute("INSERT INTO articles(doc_id,article_number,text) VALUES (1,?,?)", (n, "نص"))
    db.commit()
    s = rebuild_article_links(db)
    assert s == {"links": 2, "articles_marked": 2, "articles_repealed": 1}
    a15 = db.execute("SELECT amended_by,status FROM articles WHERE doc_id=1 AND article_number='15'").fetchone()
    assert a15["status"] == "amended"
    assert json.loads(a15["amended_by"]) == [{"by": "القانون:15:2022", "action": "amend"}]
    assert db.execute("SELECT status FROM articles WHERE doc_id=1 AND article_number='1'").fetchone()[0] == "repealed"
    # إعادة البناء لا تراكم
    assert rebuild_article_links(db)["links"] == 2


def test_older_instrument_cannot_amend_article(db):
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year)"
               " VALUES (1,'a','ق','المادة 3 نص','active','instrument','القانون:5:2010',5,2010)")
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year)"
               " VALUES (2,'b','ق','تعدل المادة 3 من القانون رقم 5 لعام 2010','active','instrument','القانون:9:1990',9,1990)")
    db.execute("INSERT INTO articles(doc_id,article_number,text) VALUES (1,'3','نص')")
    db.commit()
    assert rebuild_article_links(db)["articles_marked"] == 0


def test_owner_alif_maqsura_type_and_mirrored_year():
    # article_links1 (قاعدة المالك): «التشريعى» بألف مقصورة، و«لعام 6491» = 1946 مقلوبة
    r = extract_article_amendments("تعديل نص الفقرة / أ / من المادة /5/ من المرسوم التشريعى رقم /13/ للعام /1974/")
    assert r[0]["target_identity"] == "المرسوم التشريعي:13:1974"
    r = extract_article_amendments("تلغى المادة 87 من المرسوم التشريعي رقم 74 لعام 6491")
    assert r[0]["target_identity"] == "المرسوم التشريعي:74:1946"
