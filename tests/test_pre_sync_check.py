# -*- coding: utf-8 -*-
import argparse
import config, database, cli
from test_export_collisions import _mk_db


def _run(monkeypatch, pkg):
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    cli.cmd_pre_sync_check(argparse.Namespace(pkg=str(pkg), top=5))
    return "\n".join(lines)


def test_missing_package_is_not_ready(monkeypatch, tmp_path):
    _mk_db(tmp_path, monkeypatch, [("قانون العقوبات", 148, 1949, "نص " * 400)])
    t = _run(monkeypatch, tmp_path / "nope")
    assert "gate=FAIL" in t and "verdict=REVIEW" in t and "read-only" in t


def test_exported_package_matches_db_and_flags_repeats(monkeypatch, tmp_path):
    import exporter
    db = _mk_db(tmp_path, monkeypatch, [("قانون العقوبات", 148, 1949, "نص المصدر الأول. " * 40)])
    conn = database.get_connection()
    doc = conn.execute("SELECT id FROM documents").fetchone()[0]
    for _ in range(6):   # ستة تكرارات للرقم 5 ⇒ تُرصد
        conn.execute("INSERT INTO articles (doc_id, article_number, article_label, text, char_count)"
                     " VALUES (?,?,?,?,?)", (doc, "5", "5", "نص مادة مختلفة " + str(_), 20))
    conn.commit()
    conn.close()
    out = tmp_path / "pkg"
    exporter.build_package(db_path=db, out_dir=out)
    t = _run(monkeypatch, out)
    assert "gate=PASS" in t
    assert "MATCH" in t and "MISMATCH" not in t
    assert "docs_with_5plus_repeated_numbers=1" in t
    assert "docs_with_5plus_repeated_numbers=1" in t and "repeats=5 doc#" in t
    assert "verdict=REVIEW" in t
