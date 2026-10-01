import argparse
import config, database, cli


def test_queue_report_is_read_only_and_groups(monkeypatch, tmp_path):
    p = tmp_path / "q.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    for i, (u, e) in enumerate([("https://a.sy/1", "http_404"), ("https://a.sy/2", "http_404"),
                                ("https://b.sy/3", None)]):
        conn.execute("INSERT INTO crawl_tasks(url,kind,status,attempts,last_error,created_at) "
                     "VALUES(?,?,?,?,?,?)", (u, "topic", "failed", 1, e, "2026-09-01T00:00:00"))
    conn.commit()
    before = conn.execute("SELECT COUNT(*), SUM(attempts) FROM crawl_tasks").fetchone()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    rc = cli.cmd_queue_report(argparse.Namespace(status="failed", top=5))
    assert rc == 0
    text = "\n".join(lines)
    assert "total=3" in text and "host 2 a.sy" in text and "error 2 http_404" in text
    assert "combo 2 a.sy | http_404" in text
    assert tuple(conn.execute("SELECT COUNT(*), SUM(attempts) FROM crawl_tasks").fetchone()) == tuple(before)
