# -*- coding: utf-8 -*-
import argparse
import config, database, cli


def test_requeue_only_tasks_of_docs_with_repeated_numbers(monkeypatch, tmp_path):
    p = tmp_path / "rq.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    for i, url in ((1, "https://x.sy/rep"), (2, "https://x.sy/clean")):
        conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status) VALUES(?,?,?,?, 'active')",
                     (i, f"d{i}", "t", url))
        conn.execute("INSERT INTO crawl_tasks(url,status,attempts,created_at,updated_at) VALUES(?,?,?,?,?)",
                     (url, "success", 1, "2026-01-01", "2026-01-01"))
    for _ in range(3):   # الوثيقة 1: الرقم 4 مكرر 3 مرات ⇒ تكرارات = 2
        conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(1,'4','4','x')")
    conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(2,'1','1','x')")
    conn.commit()
    conn.close()
    cli.cmd_requeue(argparse.Namespace(status="success", contains=None, docs_with_repeats=2))
    c2 = database.get_connection()
    st = {r["url"]: r["status"] for r in c2.execute("SELECT url, status FROM crawl_tasks")}
    assert st == {"https://x.sy/rep": "queued", "https://x.sy/clean": "success"}
