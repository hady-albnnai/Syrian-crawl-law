import argparse
import config, database, cli


def test_export_audit_counts_identical_and_different_drops(monkeypatch, tmp_path):
    p = tmp_path / "e.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature) "
                 "VALUES(1,'a','قانون أ','https://x.sy/a','active','instrument')")
    for num, text in [("1", "نص ١"), ("2", "نص ٢"), ("2", "نص ٢"), ("3", "نص ٣"), ("3", "نص مختلف")]:
        conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(1,?,?)", (num, text))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_export_audit(argparse.Namespace(top=5)) == 0
    t = "\n".join(lines)
    assert "raw_articles=5 exported=3 dropped=2" in t
    assert "identical_text=1 different_text=1" in t
    assert "doc#1 different=1 identical=1" in t
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 5


def test_export_audit_doc_drilldown_shows_kept_and_dropped(monkeypatch, tmp_path):
    p = tmp_path / "e2.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature) "
                 "VALUES(1,'a','قانون أ','https://x.sy/a','active','instrument')")
    for num, text, path in [("1", "الأصل", "الباب الأول"), ("1", "ملحق", "الملحق")]:
        conn.execute("INSERT INTO articles(doc_id,article_number,text,hierarchy_path) VALUES(1,?,?,?)",
                     (num, text, path))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_export_audit(argparse.Namespace(top=5, doc=1, samples=3))
    t = "\n".join(lines)
    assert "EXDOC| no.1 KEPT" in t and "path=الباب الأول" in t and "الأصل" in t
    assert "EXDOC| no.1 DROP" in t and "path=الملحق" in t and "ملحق" in t
