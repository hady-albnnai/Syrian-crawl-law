import argparse
import config, database, cli


def test_export_audit_counts_only_part_copies_as_dropped(monkeypatch, tmp_path):
    p = tmp_path / "e.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature) "
                 "VALUES(1,'a','قانون أ','https://x.sy/a','active','instrument')")
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,part_of) "
                 "VALUES(2,'b','جزء','https://x.sy/b','active','instrument',1)")
    # الرأس: تكرار الرقم داخل الوثيقة يُحفظ كاملاً (لا يُحسب مُسقطاً)
    for num, text in [("1", "نص ١"), ("2", "نص ٢"), ("2", "نص آخر"), ("3", "نص ٣")]:
        conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(1,?,?)", (num, text))
    # الجزء: نسخة مطابقة (3) ونسخة بنص مختلف (1) تُطويان؛ والمادة 4 فريدة تبقى
    for num, text in [("1", "نص مختلف"), ("3", "نص ٣"), ("4", "نص ٤")]:
        conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(2,?,?)", (num, text))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_export_audit(argparse.Namespace(top=5)) == 0
    t = "\n".join(lines)
    assert "raw_articles=7 exported=5 dropped=2" in t
    assert "identical_text=1 different_text=1" in t
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 7


def test_fold_part_articles_keeps_every_head_article_and_distinguishes_labels():
    from exporter import fold_part_articles
    def row(i, doc, num, lab):
        return {"id": i, "doc_id": doc, "article_number": num, "article_label": lab}
    raw = [row(1, 10, "5", "5"), row(2, 10, "5", "5"), row(3, 10, "5", "5 مكرر"),
           row(4, 11, "5", "5"), row(5, 11, "6", "6"), row(6, 12, "6", "6"),
           row(7, 12, "6", "6")]
    kept = [r["id"] for r in fold_part_articles(raw, 10)]
    # الرأس 1,2,3 كلها؛ الجزء 11: 4 مطوية (موجودة بالرأس) و5 تبقى؛
    # الجزء 12: 6 مطوية (سبقها جزء 11) و7 مطوية معها
    assert kept == [1, 2, 3, 5]


def test_export_audit_doc_drilldown_shows_repeats_and_source(monkeypatch, tmp_path):
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
    assert "EXDOC| no.1 FIRST" in t and "الأصل" in t and "numbers_distinct=1 of 2" in t
    assert "EXDOC| no.1 REPEAT(kept)" in t and "ملحق" in t and "src=https://x.sy/a" in t
    assert "exported=2 dropped=0" in t


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


def test_export_audit_doc_lists_parts_and_folded_samples(monkeypatch, tmp_path):
    p = tmp_path / "e5.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature) "
                 "VALUES(1,'a','رأس','https://x.sy/a','active','instrument')")
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,part_of) "
                 "VALUES(2,'b','جزء','https://x.sy/b','active','instrument',1)")
    conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(1,'1','نص الرأس')")
    conn.execute("INSERT INTO articles(doc_id,article_number,text) VALUES(2,'1','نص الجزء')")
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_export_audit(argparse.Namespace(top=5, doc=1, samples=2))
    t = "\n".join(lines)
    assert "EXPART| head articles=1 range=1..1 parts=1" in t
    assert "EXPART| part#2 status=active articles=1" in t and "src=https://x.sy/b" in t
    assert "EXFOLD| no.1 head(id=1): نص الرأس" in t and "نص الجزء" in t
