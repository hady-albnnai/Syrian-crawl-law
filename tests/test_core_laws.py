# -*- coding: utf-8 -*-
import config
import database
import pytest
from core_laws import CORE_LAWS, check_core, format_core_report


def test_core_list_has_sources_and_unique_identity():
    keys = set()
    for law in CORE_LAWS:
        assert law["ref"], law["name"]
        assert (law["number"], law["year"]) not in keys, law["name"]
        keys.add((law["number"], law["year"]))


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_check_core_verdicts(db):
    conn = db
    conn.execute("INSERT INTO documents(doc_id,title,doc_type,number,year,status,identity_key) VALUES('a','القانون المدني','المرسوم التشريعي',84,1949,'active','المرسوم التشريعي:84:1949')")
    did = conn.execute("SELECT id FROM documents WHERE number=84").fetchone()[0]
    conn.executemany("INSERT INTO articles(doc_id,article_number,text) VALUES(?,?,?)", [(did, str(i), 'نص') for i in range(1, 11)])
    conn.execute("INSERT INTO documents(doc_id,title,doc_type,number,year,status) VALUES('b','قانون العمل','القانون',17,2010,'superseded')")
    conn.commit()
    res = {r["law"]["name"]: r for r in check_core(conn)}
    assert res["القانون المدني"]["verdict"].startswith("ناقص المواد")
    assert res["قانون العمل"]["verdict"].startswith("موجود لكن غير نشط")
    assert res["قانون البينات"]["verdict"] == "مفقود"
    assert format_core_report(list(res.values())).startswith("القائمة الأساسية: 0/")
