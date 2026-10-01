import argparse
import config, database, cli


def test_source_report_counts_per_source_and_is_read_only(monkeypatch, tmp_path):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO sources(id,base_url,source_key,status) VALUES(1,'https://www.a.sy/laws','a','approved')")
    conn.execute("INSERT INTO sources(id,base_url,source_key,status) VALUES(2,'https://b.sy/','b','approved')")
    for i, u in enumerate(["https://a.sy/laws/1", "https://a.sy/laws/2", "https://a.sy/news/3", "https://b.sy/x"]):
        conn.execute("INSERT INTO documents(doc_id,title,source_url,status) VALUES(?,?,?, 'active')",
                     (f"d{i}", f"t{i}", u))
    conn.execute("INSERT INTO crawl_tasks(url,status) VALUES('https://a.sy/laws/9','failed')")
    conn.execute("INSERT INTO crawl_tasks(url,status) VALUES('https://a.sy/other','failed')")
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_source_report(argparse.Namespace(ids=[1, 2, 99], sample=1)) == 0
    text = "\n".join(lines)
    assert "id=1 docs_active=2 docs_total=2" in text      # لا يشمل /news
    assert "'failed': 1" in text                           # طابور المسار فقط
    assert "id=2 docs_active=1" in text and "id=99 not found" in text
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 4
