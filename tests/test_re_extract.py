# -*- coding: utf-8 -*-
import argparse
import config, database, cli


def _body(n):
    return f"نص المادة رقم {n} وفيه كلام كافٍ ليتجاوز الحد الأدنى للطول."


def _clean():
    parts = []
    for n in range(1, 13):
        parts.append(f"المادة {n}")
        if n == 3:
            parts.append(_body(n) + " ويجري ذلك وفق\nالمادة 9 من هذا القانون وتتمة النص.")
        else:
            parts.append(_body(n))
    return "\n".join(parts)


def _setup(monkeypatch, tmp_path, clean):
    p = tmp_path / "re.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,clean_content) "
                 "VALUES(1,'a','قانون','https://x.sy/a','active','instrument',?)", (clean,))
    # الحال القديمة: 13 مادة والتاسعة مكررة (شظية الإحالة)
    nums = list(range(1, 13)) + [9]
    for n in nums:
        conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(1,?,?,?)",
                     (str(n), str(n), "نص قصير"))
    conn.execute("INSERT INTO chunks(doc_id,article_id,seq,number,label,text) VALUES(1,1,0,'1','1','x')")
    conn.commit()
    return conn


def test_dry_run_changes_nothing(monkeypatch, tmp_path):
    conn = _setup(monkeypatch, tmp_path, _clean())
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=False))
    t = "\n".join(lines)
    assert "will_change=1" in t and "doc#1 articles 13->12 repeats 1->0" in t and "dry-run" in t
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 13
    assert not (tmp_path / "backups").exists()


def test_apply_rebuilds_articles_backs_up_and_clears_chunks(monkeypatch, tmp_path):
    conn = _setup(monkeypatch, tmp_path, _clean())
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=True))
    c2 = database.get_connection()
    nums = [r[0] for r in c2.execute("SELECT article_number FROM articles WHERE doc_id=1 ORDER BY id")]
    assert sorted(map(int, nums)) == list(range(1, 13))
    assert "تتمة النص" in c2.execute("SELECT text FROM articles WHERE article_number='3'").fetchone()[0]
    assert c2.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=1").fetchone()[0] == 0
    assert len(list((tmp_path / "backups").glob("*_before_reextract_*.db"))) == 1


def test_truncated_clean_content_is_skipped(monkeypatch, tmp_path):
    conn = _setup(monkeypatch, tmp_path, "قصير جداً")
    conn.execute("UPDATE articles SET text=?", ("ن" * 500,))
    conn.commit()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=True))
    assert "clean_content_truncated" in "\n".join(lines)
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 13


def test_bunud_declared_anchored_merges_fragments_even_when_count_drops(monkeypatch, tmp_path):
    """بنود: مصنّف على أول السطر؛ 23 صفاً قديماً (7 شظايا إحالات) → 16 مادة، بلا ضياع نص."""
    p = tmp_path / "bu.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    lines, rows = [], []
    for n in range(1, 17):
        lines.append(f"المادة {n}")
        b1 = f"نص المادة رقم {n} من هذا المرسوم التشريعي كامل ويتجاوز الحد الأدنى"
        if n in (2, 3, 5, 6, 9, 10, 12):
            b2 = " وتتمة بعد الإحالة إلى هذا المرسوم ويطبق"
            lines.append(b1 + " وفق أحكام المادة (9)" + b2)
            rows += [(n, b1 + " وفق أحكام"), (n, "(9)" + b2)]
        else:
            lines.append(b1)
            rows.append((n, b1))
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,clean_content) "
                 "VALUES(1,'a','قانون','https://www.bunud.ai/sy/laws/building-violations-law',"
                 "'active','instrument',?)", ("\n".join(lines),))
    for n, t in rows:
        conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(1,?,?,?)",
                     (str(n), str(n), t))
    conn.commit()
    out = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: out.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=True))
    c2 = database.get_connection()
    nums = [int(r[0]) for r in c2.execute("SELECT article_number FROM articles WHERE doc_id=1 ORDER BY id")]
    assert nums == list(range(1, 17)), "\n".join(out)


def test_repeat_diagnose_reports_runs(monkeypatch, tmp_path):
    conn = _setup(monkeypatch, tmp_path, _clean())     # مواد 1..12 ثم 9 مكررة
    out = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: out.append(str(m)))
    assert cli.cmd_repeat_diagnose(argparse.Namespace(ids=[1, 99], runs=8, ctx=3)) == 0
    t = "\n".join(out)
    assert "doc#1" in t and "runs=2" in t and "1..12(12)" in t and "9..9(1)" in t
    assert "doc#99 not found" in t
