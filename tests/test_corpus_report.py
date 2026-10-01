import argparse
import config, database, cli


def test_corpus_report_groups_and_is_read_only(monkeypatch, tmp_path):
    p = tmp_path / "c.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    docs = [("d1", "active", "instrument", None, 3), ("d2", "active", "travaux", None, 5),
            ("d3", "superseded", "instrument", None, 2), ("d4", "active", "instrument", 1, 1)]
    for i, (did, st, nat, part, n) in enumerate(docs, 1):
        conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,part_of) "
                     "VALUES(?,?,?,?,?,?,?)", (i, did, did, f"https://x.sy/{did}", st, nat, part))
        for j in range(n):
            conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(?,?,?)",
                         (i, str(j + 1), "x"))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_corpus_report(argparse.Namespace()) == 0
    t = "\n".join(lines)
    assert "total docs=4 articles=11" in t
    assert "status=active nature=travaux part=False docs=1 articles=5" in t
    assert "status=superseded nature=instrument part=False docs=1 articles=2" in t
    assert "articles in exportable groups=4" in t           # d1 (3) + الجزء d4 (1) يُطوى تحت رأسه
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 4
