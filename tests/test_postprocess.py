"""التنقيح الختامي داخل الزاحف (قرار المالك 2026-09-19)."""
import sqlite3

import config
import database
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_refine_all_runs_every_stage_in_order(db):
    import postprocess
    T = "المرسوم التشريعي رقم/44 المتعلق بالمؤسسة العامة للأعلاف"
    db.execute("INSERT INTO documents(id,title,clean_content,status) VALUES (1,?, 'المادة 1 نص','active')", (T,))
    db.execute("INSERT INTO documents(id,title,clean_content,status) VALUES (2,?, 'المادة 6 نص','active')", (T,))
    db.commit()
    s = postprocess.refine_all(db)
    assert set(s) == {"excluded", "nature", "identity", "issue_date", "regulations", "dedup", "parts", "amendment_links", "article_links", "status"}
    assert s["excluded"] == 0 and s["parts"]["groups"] == 1 and s["parts"]["parts_linked"] == 1
    assert db.execute("SELECT COUNT(*) FROM documents WHERE part_of IS NOT NULL").fetchone()[0] == 1


def test_crawler_calls_refine_after_live_run(monkeypatch):
    import crawler
    src = open(crawler.__file__, encoding="utf-8").read()
    assert "postprocess.refine_all(conn)" in src
    assert "if not dry_run" in src
