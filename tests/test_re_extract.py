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


def test_blocks_doc_when_a_real_article_number_would_disappear(monkeypatch, tmp_path):
    """رقم 7 داخل مدى الوثيقة موجود قديماً ومفقود جديداً: يُحجب التغيير."""
    clean = _clean().replace("المادة 7\n" + _body(7) + "\n", "")
    conn = _setup(monkeypatch, tmp_path, clean)
    out = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: out.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=False))
    t = "\n".join(out)
    assert "lost_numbers" in t and "will_change=0" in t
    out.clear()
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=False, allow_number_loss=True))
    assert "will_change=1" in "\n".join(out)


def test_docs_with_stub_articles_but_no_repeats_are_candidates(monkeypatch, tmp_path):
    p = tmp_path / "st.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    clean = ("المادة 1\nتنفيذا لأحكام المادة 5 من القانون رقم 9 يصدر ما يلي وبقية النص الطويل هنا كامل\n"
             + "\n".join(f"المادة {n}\nنص المادة رقم {n} كامل ويتجاوز الحد الأدنى للطول" for n in range(2, 6)))
    conn.execute("INSERT INTO documents(id,doc_id,title,source_url,status,nature,clean_content) "
                 "VALUES(1,'a','قانون','https://x.sy/a','active','instrument',?)", (clean,))
    rows = [(1, "تنفيذا لأحكام"), (5, "من القانون رقم 9 يصدر ما يلي وبقية النص الطويل هنا كامل"),
            (2, "نص المادة رقم 2 كامل ويتجاوز الحد الأدنى للطول"), (3, "نص المادة رقم 3 كامل ويتجاوز الحد الأدنى للطول"),
            (4, "نص المادة رقم 4 كامل ويتجاوز الحد الأدنى للطول")]
    for n, t in rows:
        conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(1,?,?,?)",
                     (str(n), str(n), t))
    conn.commit()
    out = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: out.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=[1], top=5, apply=False))
    t = "\n".join(out)
    assert "short=1->0" in t


def test_numbers_beyond_the_document_range_are_allowed_to_disappear(monkeypatch, tmp_path):
    """مرسوم تعديل: مواده 1..5، والرقم 51 مجرد إحالة إلى مادة في قانون آخر."""
    clean = "\n".join(f"المادة {n}\nنص المادة رقم {n} كامل ويتجاوز الحد الأدنى للطول" for n in range(1, 6))
    conn = _setup(monkeypatch, tmp_path, clean)
    conn.execute("DELETE FROM articles")
    for n, t in [(1, "تنفيذا لأحكام"), (51, "من القانون رقم 9 وبقية النص"), (2, "ن"), (3, "ن"), (4, "ن"), (5, "ن"), (2, "ن")]:
        conn.execute("INSERT INTO articles(doc_id,article_number,article_label,text) VALUES(1,?,?,?)",
                     (str(n), str(n), t))
    conn.commit()
    out = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: out.append(str(m)))
    cli.cmd_re_extract(argparse.Namespace(ids=None, top=5, apply=False))
    t = "\n".join(out)
    assert "will_change=1" in t and "docs_dropping_numbers_beyond_range=1" in t
