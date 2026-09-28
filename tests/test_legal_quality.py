"""بوابة الصكوك النافذة: تحقق بشري مرتبط ببصمة المحتوى الحالية."""
import csv
import hashlib
import json

import database
import exporter
from crawler import save_document
from legal_quality import assess_current_law, record_document_review


def _db(tmp_path, monkeypatch):
    import config
    db = tmp_path / "legal-quality.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    return db, database.get_connection()


def _insert_law(conn, url="https://laws.example/law-1"):
    cur = conn.cursor()
    stable_id = "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    doc_id, created = save_document(
        cur, stable_id, "قانون اختباري", url, "civil_law", 0.9,
        90.0, "legacy-md5", "نص تشريعي كامل للاختبار",
        identity_key="القانون:1:2020", identity_confidence="number_year",
        law_number=1, law_year=2020, is_complete_text=1, nature="instrument")
    conn.commit()
    conn.execute("UPDATE documents SET legal_status='ساري', nature='instrument', "
                 "is_complete_text=1 WHERE id=?", (doc_id,))
    conn.execute("INSERT INTO articles (doc_id, article_number, article_label, "
                 "text, char_count) VALUES (?, '1', 'المادة 1', 'حكم اختباري', 12)",
                 (doc_id,))
    conn.commit()
    return doc_id


def _pass_all_reviews(conn, doc_id):
    for kind in ("full_text", "legal_status", "rights"):
        record_document_review(
            conn, doc_id, kind, "pass", "مراجع قانوني",
            evidence_url=f"https://official.example/evidence/{kind}")


def test_current_law_requires_three_human_reviews_and_evidence(tmp_path, monkeypatch):
    _db_path, conn = _db(tmp_path, monkeypatch)
    doc_id = _insert_law(conn)
    assessment = assess_current_law(
        conn, conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
    assert assessment["eligible"] is False
    assert {"human_review_missing:full_text", "human_review_missing:legal_status",
            "human_review_missing:rights"}.issubset(set(assessment["reasons"]))

    try:
        record_document_review(conn, doc_id, "rights", "pass", "reviewer")
    except ValueError as exc:
        assert "الدليل المرجعي" in str(exc)
    else:
        raise AssertionError("pass without evidence must be rejected")
    try:
        record_document_review(conn, doc_id, "rights", "pass", "reviewer",
                               evidence_url="javascript:alert(1)")
    except ValueError as exc:
        assert "http/https" in str(exc)
    else:
        raise AssertionError("non-HTTP evidence must be rejected")

    _pass_all_reviews(conn, doc_id)
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert assess_current_law(conn, row)["eligible"] is True
    conn.close()


def test_empty_text_cannot_receive_content_bound_review(tmp_path, monkeypatch):
    _db_path, conn = _db(tmp_path, monkeypatch)
    digest = hashlib.sha256(b"").hexdigest()
    cur = conn.execute(
        "INSERT INTO documents (doc_id, title, clean_content, content_sha256) "
        "VALUES ('empty-law', 'نص فارغ', '', ?)", (digest,))
    conn.commit()
    try:
        record_document_review(conn, cur.lastrowid, "full_text", "pass",
                              "مراجع", evidence_url="https://evidence.example/empty")
    except ValueError as exc:
        assert "بصمة النص" in str(exc)
    else:
        raise AssertionError("empty document must not be reviewable")
    conn.close()


def test_content_change_invalidates_prior_reviews(tmp_path, monkeypatch):
    _db_path, conn = _db(tmp_path, monkeypatch)
    doc_id = _insert_law(conn)
    _pass_all_reviews(conn, doc_id)
    new_text = "نسخة معدلة من النص القانوني"
    from legal_quality import text_sha256
    conn.execute("UPDATE documents SET clean_content=?, content_sha256=? WHERE id=?",
                 (new_text, text_sha256(new_text), doc_id))
    conn.commit()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assessment = assess_current_law(conn, row)
    assert assessment["eligible"] is False
    assert "human_review_missing:full_text" in assessment["reasons"]
    conn.close()


def test_current_only_export_keeps_mizan_fourteen_columns(tmp_path, monkeypatch):
    db, conn = _db(tmp_path, monkeypatch)
    eligible_id = _insert_law(conn, "https://laws.example/eligible")
    _pass_all_reviews(conn, eligible_id)
    _insert_law(conn, "https://laws.example/unreviewed")
    conn.close()

    out = tmp_path / "current-package"
    report = exporter.build_package(db, out_dir=out, current_only=True,
                                    with_manifest=False)
    assert report["current_only"] is True
    assert report["docs"] == 1
    assert report["current_excluded"] == 1
    header = (out / "laws_decrees_index.csv").read_bytes().decode("utf-8-sig").splitlines()[0]
    assert header == ",".join(exporter.COLUMNS)
    assert len(exporter.COLUMNS) == 14
    rows = list(csv.DictReader(open(out / "laws_decrees_index.csv",
                                   encoding="utf-8-sig")))
    assert len(rows) == 1 and rows[0]["url"].endswith("/eligible")
    sidecars = list((out / "markdown").glob("*.json"))
    assert len(sidecars) == 1
    data = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert data["current_law_eligibility"]["eligible"] is True
    assert data["current_law_eligibility"]["human_reviewed_types"] == [
        "full_text", "legal_status", "rights"]
