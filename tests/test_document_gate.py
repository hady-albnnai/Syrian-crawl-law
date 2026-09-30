"""بوابة الاختصاص على مستوى الوثيقة عند الزحف + تدقيق المتن الحالي — دون شبكة."""
import argparse
from pathlib import Path

import crawl_queue as taskqueue
import crawler
import database

FIX = Path(__file__).parent / "fixtures"
WP_POST = (FIX / "wp_legal_post.html").read_text(encoding="utf-8")


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "gate.db"))
    database.create_tables()
    return database.get_connection()


def _run(conn, monkeypatch, html, url="https://laws-blog.example/2024/05/penal"):
    monkeypatch.setattr(crawler, "SAVE_RAW_HTML", False)
    taskqueue.enqueue(conn, url, "قسم", "topic")
    task = dict(conn.execute("SELECT * FROM crawl_tasks ORDER BY id DESC LIMIT 1").fetchone())
    stats = {"failures": 0, "docs": 0, "articles": 0, "skipped": 0}
    crawler._handle_topic(conn, task, html, False, stats)
    return task, stats


def _foreign(html):
    neutral = html.replace("السوري", "").replace("السورية", "")
    return neutral.replace("رئيس الجمهورية", "جمهورية مصر العربية القانون المصري "
                           "محكمة النقض المصرية الوقائع المصرية مجلس الدولة المصري", 1)


def test_foreign_document_is_quarantined_not_saved(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    task, stats = _run(conn, monkeypatch, _foreign(WP_POST))
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    row = conn.execute("SELECT status, last_error FROM crawl_tasks WHERE id=?",
                       (task["id"],)).fetchone()
    assert row["status"] == "needs_review" and "اختصاص أجنبي" in row["last_error"]
    assert stats["skipped"] == 1
    conn.close()


def test_syrian_document_still_saved(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    _run(conn, monkeypatch, WP_POST)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_neutral_document_without_markers_is_saved(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    _run(conn, monkeypatch, WP_POST.replace("السوري", "").replace("السورية", ""))
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_syrian_decree_ratifying_agreement_with_egypt_is_not_foreign(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    html = WP_POST.replace("رئيس الجمهورية", "الجمهورية العربية السورية رئيس الجمهورية "
                           "بعد الاطلاع على الاتفاقية مع جمهورية مصر العربية", 1)
    _run(conn, monkeypatch, html)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_audit_jurisdiction_is_read_only_and_reports(tmp_path, monkeypatch, capsys):
    import cli
    conn = _db(tmp_path, monkeypatch)
    _run(conn, monkeypatch, WP_POST)
    before = conn.execute("SELECT COUNT(*), MAX(id) FROM documents").fetchone()
    conn.close()
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_audit_jurisdiction(argparse.Namespace(limit=10)) == 0
    assert any(m.startswith("AUDIT| documents=1") and "syrian=1" in m for m in lines), lines
    conn = database.get_connection()
    assert tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM documents").fetchone()) == tuple(before)
    conn.close()


def test_exclude_documents_archives_and_is_reversible(tmp_path, monkeypatch):
    import cli
    conn = _db(tmp_path, monkeypatch)
    _run(conn, monkeypatch, WP_POST)
    did = conn.execute("SELECT id FROM documents").fetchone()[0]
    conn.close()
    monkeypatch.setattr(cli.log, "info", lambda *a, **k: None)
    cli.cmd_exclude_documents(argparse.Namespace(ids=[did, 9999], reason="t", restore=False))
    conn = database.get_connection()
    assert conn.execute("SELECT status FROM documents WHERE id=?", (did,)).fetchone()[0] == "excluded"
    assert conn.execute("SELECT COUNT(*) FROM document_versions WHERE original_doc_id=?",
                        (did,)).fetchone()[0] == 1
    conn.close()
    cli.cmd_exclude_documents(argparse.Namespace(ids=[did], reason="t", restore=True))
    conn = database.get_connection()
    assert conn.execute("SELECT status FROM documents WHERE id=?", (did,)).fetchone()[0] == "active"
    conn.close()


SANA_DECREE = (FIX / "sana_decree_87.html").read_text(encoding="utf-8")
SANA_URL = "https://sana.sy/presidency/2497260/"


def test_short_presidential_decree_with_full_text_is_saved(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    _run(conn, monkeypatch, SANA_DECREE, url=SANA_URL)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_same_page_without_any_text_formula_stays_in_review(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    html = (SANA_DECREE.replace("نص المرسوم", "تفاصيل").replace("يرسم ما يلي", "ما يلي")
            .replace("وفيما يلي", "وفيما"))
    assert "يرسم ما يلي" not in html and "نص المرسوم" not in html
    task, _ = _run(conn, monkeypatch, html, url=SANA_URL)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    row = conn.execute("SELECT status FROM crawl_tasks WHERE id=?", (task["id"],)).fetchone()
    assert row["status"] == "needs_review"
    conn.close()


def test_is_decree_text_post_rules():
    import crawler
    assert crawler.is_decree_text_post("وفيما يلي نص المرسوم رقم (87) لعام 2026", 3)
    assert crawler.is_decree_text_post("وفيما يلي النص الكامل للمرسوم: رئيس الجمهورية", 3)
    assert crawler.is_decree_text_post("نص المرسوم: بناء على مقتضيات المصلحة. يرسم ما يلي", 4)
    assert crawler.is_decree_text_post("يقرر رئيس الجمهورية ما يلي: المادة (1)", 2)
    assert not crawler.is_decree_text_post("وفيما يلي نص المرسوم", 1)            # مادة واحدة
    assert not crawler.is_decree_text_post("أصدر الرئيس المرسوم رقم (87) لعام 2026", 3)  # خبر

