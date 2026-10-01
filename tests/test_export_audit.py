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
    assert "EXDOC| no.1 KEPT" in t and "الأصل" in t and "numbers_distinct=1 of 2" in t
    assert "EXDOC| no.1 DROP" in t and "ملحق" in t and "src=https://x.sy/a" in t


def test_export_audit_raw_snippet(monkeypatch, tmp_path):
    p = tmp_path / "e3.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,clean_content) "
                 "VALUES(1,'a','t','https://x.sy/a','active','instrument','مقدمة طويلة\nالمادة 1 نص المادة الاولى')")
    conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(1,'1','نص')")
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_export_audit(argparse.Namespace(top=5, doc=1, samples=1, raw=20, find="المادة 1", rows=None))
    assert any(l.startswith("EXRAW| chars 12..32") and "المادة 1 نص المادة" in l for l in lines)


def test_export_audit_rows(monkeypatch, tmp_path):
    p = tmp_path / "e4.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,clean_content) "
                 "VALUES(1,'a','t','https://x.sy/a','active','instrument','x')")
    for n, tx in (("1", "اولى"), ("1", "ثانية"), ("3", "ثالثة")):
        conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(1,?,?)", (n, tx))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_export_audit(argparse.Namespace(top=5, doc=1, samples=1, raw=0, find=None, rows="1:2"))
    rows = [l for l in lines if l.startswith("EXROW|")]
    assert len(rows) == 2 and "pos=1" in rows[0] and "ثانية" in rows[0]
