"""الرقم 13 مرّ بمعنيين تاريخياً (تقييم المصادر / مراجعات ونماذج).

الهجرة الآن: 13 = تقييم المصادر، 14 = المراجعات والنماذج. هذه الاختبارات
تبني قاعدتين على المسارين التاريخيين وتتحقق أن كلاً منهما تصل إلى 14 سليمة.
"""
import sqlite3

import pytest

import database
import migrations

ASSESS_ONLY = ("source_type", "evaluation_details_json", "evaluated_at",
               "evaluation_sample_count")
REVIEW_ONLY_SOURCES = ("source_role", "publisher_country", "collection_scope")
TEMPLATE_NEW = ("jurisdiction", "template_status", "review_status",
                "source_role", "rights_status", "rights_evidence_url",
                "discovered_via", "is_complete_text", "content_sha256",
                "retrieved_at", "reviewed_by", "reviewed_at",
                "version_label", "superseded_by")


def _fresh(tmp_path, monkeypatch, name):
    path = tmp_path / name
    monkeypatch.setattr(database, "DB_PATH", str(path))
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "backups")
    database.create_tables()
    return path


def _drop_cols(conn, table, cols):
    for col in cols:
        conn.execute("DROP INDEX IF EXISTS idx_templates_review_type")
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


def test_db_from_assessment_branch_reaches_14(tmp_path, monkeypatch):
    path = _fresh(tmp_path, monkeypatch, "assess.db")
    conn = sqlite3.connect(path)
    for t in ("document_reviews", "template_reviews", "template_versions"):
        conn.execute(f"DROP TABLE {t}")
    _drop_cols(conn, "templates", TEMPLATE_NEW)
    _drop_cols(conn, "sources", REVIEW_ONLY_SOURCES)
    conn.execute("PRAGMA user_version = 13")
    conn.commit(); conn.close()

    rep = migrations.migrate(str(path))
    assert (rep["start_version"], rep["end_version"]) == (13, 14)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"document_reviews", "template_reviews", "template_versions"} <= tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(templates)")}
    assert "review_status" in cols
    conn.close()
    database.create_tables()  # كان ينهار: no such column: review_status


def test_db_from_review_branch_keeps_human_seed_decision(tmp_path, monkeypatch):
    path = _fresh(tmp_path, monkeypatch, "review.db")
    conn = sqlite3.connect(path)
    _drop_cols(conn, "sources", ASSESS_ONLY)
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name, status, "
        "discovered_via, decided_at, decided_by) VALUES "
        "('seed', 'https://seed.example/', 'seed', 'approved', "
        "'seed-primary', '2026-09-29', 'user')")
    conn.execute("PRAGMA user_version = 13")
    conn.commit(); conn.close()

    rep = migrations.migrate(str(path))
    assert rep["end_version"] == 14
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert set(ASSESS_ONLY) <= cols
    status, by = conn.execute(
        "SELECT status, decided_by FROM sources WHERE source_key='seed'").fetchone()
    assert (status, by) == ("approved", "user")  # قرار المالك لا يُمحى
    conn.close()
    database.create_tables()
