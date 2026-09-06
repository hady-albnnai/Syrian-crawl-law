# -*- coding: utf-8 -*-
"""اختبارات هجرة 005 — سبب رفض صريح من المراجعة البشرية (طلب المالك
2026-09-06): «حتى يتعلم الزاحف للمرات القادمة».

نفس قاعدة الهجرات الآمنة في CONSTITUTION.md: قاعدة قديمة تُرقّى idempotent،
وقاعدة جديدة تُبنى مباشرة بنفس الجدول/العمود — لا مسارين مختلفين.
"""
import sqlite3

import database
import migrations


def _legacy_004_schema(db_path, monkeypatch, backup_name="backups005"):
    """قاعدة بمخطط ما بعد الهجرة 4 مباشرة (بلا rejection_reasons/
    rejection_count) — user_version=4 يحاكي قاعدة مُهاجَرة فعلياً حتى
    آخر إصدار سابق مباشرة."""
    conn = sqlite3.connect(db_path)
    conn.executescript('''
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE, title TEXT, source_url TEXT UNIQUE,
            clean_content TEXT
        );
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT UNIQUE, base_url TEXT UNIQUE, name TEXT,
            engine TEXT, credibility REAL DEFAULT 0.6,
            status TEXT DEFAULT 'proposed', discovered_via TEXT,
            discovered_at TEXT, decided_at TEXT, decided_by TEXT,
            domain_tier INTEGER DEFAULT 4
        );
    ''')
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content) "
        "VALUES ('sha256:aaa', 'قانون قديم', 'https://example.com/t1', 'نص')")
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name) VALUES "
        "('src1', 'https://example.com/', 'مصدر تجريبي')")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", db_path.parent / backup_name)


def test_legacy_db_migrates_to_005_with_new_table_and_column(tmp_path, monkeypatch):
    db = tmp_path / "legacy_005.db"
    _legacy_004_schema(db, monkeypatch)

    report = migrations.migrate(str(db))
    assert report["end_version"] == migrations.LATEST
    assert migrations.LATEST >= 5

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "rejection_reasons" in tables

    src_cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert "rejection_count" in src_cols

    # البيانات القديمة تبقى كما هي — الهجرة إضافية فقط
    row = conn.execute("SELECT title FROM documents WHERE doc_id=?",
                       ("sha256:aaa",)).fetchone()
    assert row["title"] == "قانون قديم"
    conn.close()


def test_migration_005_is_idempotent_on_rerun(tmp_path, monkeypatch):
    db = tmp_path / "legacy_005_rerun.db"
    _legacy_004_schema(db, monkeypatch, backup_name="backups005b")

    migrations.migrate(str(db))
    report2 = migrations.migrate(str(db))
    assert report2["applied"] == []
    assert report2["end_version"] == migrations.LATEST


def test_fresh_db_has_rejection_table_and_column(tmp_path, monkeypatch):
    """قاعدة جديدة تماماً (create_tables) يجب أن تحوي نفس الجدول/العمود
    الذي تضيفه الهجرة 005 — لا يجوز أن يفترق المساران."""
    db_path = tmp_path / "fresh_005.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.create_tables()

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "rejection_reasons" in tables

    src_cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert "rejection_count" in src_cols

    rr_cols = {r[1] for r in conn.execute("PRAGMA table_info(rejection_reasons)")}
    assert {"doc_id", "source_key", "category", "note",
            "rejected_at"} <= rr_cols
    conn.close()
