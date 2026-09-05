# -*- coding: utf-8 -*-
"""اختبارات هجرة 004 — أعمدة/جداول الاكتشاف الذاتي للمصادر.

يحرس اثنين لا يجوز أن يفترقا (قاعدة الهجرات الآمنة في CONSTITUTION.md):
1. قاعدة قديمة (بمخطط ما قبل الهجرة 4) تُرقّى بنجاح idempotent.
2. قاعدة جديدة تُبنى مباشرة بنفس الأعمدة/الجداول — لا مسارين مختلفين.
"""
import sqlite3

import pytest

import database
import migrations


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """قاعدة بمخطط ما بعد الهجرة 3 مباشرة (بلا identity_key/domain_tier/
    الجداول الجديدة التي تضيفها الهجرة 4) — user_version=3 يحاكي قاعدة
    مُهاجَرة فعلياً حتى آخر إصدار سابق، لا قاعدة عذراء تماماً."""
    db = tmp_path / "legacy_004.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE, title TEXT, doc_type TEXT,
            number INTEGER, year INTEGER, branch TEXT,
            branch_confidence REAL, source_url TEXT UNIQUE,
            legal_score REAL, content_hash TEXT,
            scraped_at TEXT, clean_content TEXT,
            content_sha256 TEXT, snapshot_sha256 TEXT
        );
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT UNIQUE, base_url TEXT UNIQUE, name TEXT,
            engine TEXT, credibility REAL DEFAULT 0.6,
            status TEXT DEFAULT 'proposed', discovered_via TEXT,
            discovered_at TEXT, decided_at TEXT, decided_by TEXT
        );
    ''')
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content) "
        "VALUES ('sha256:aaa', 'قانون قديم', 'https://example.com/t1', 'نص')")
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name) VALUES "
        "('src1', 'https://example.com/', 'مصدر تجريبي')")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "backups")
    return db


def test_legacy_db_migrates_to_004_with_new_columns_and_tables(legacy_db):
    report = migrations.migrate(str(legacy_db))
    assert report["end_version"] == migrations.LATEST

    conn = sqlite3.connect(legacy_db)
    conn.row_factory = sqlite3.Row

    doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"identity_key", "identity_confidence", "is_complete_text",
            "source_domain_tier", "quality_score"} <= doc_cols

    src_cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert "domain_tier" in src_cols

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"document_versions", "dedup_decisions",
            "source_performance"} <= tables

    # crawl_runs غير موجود بمخطط الفكستشر القديمة أعلاه — لا يُضاف عمود
    # على جدول غائب؛ هذا سلوك متوقَّع ومختبر بملف آخر (test_migration_export)

    # الصف القديم يبقى كما هو — الهجرة إضافية فقط، لا تفقد بيانات
    row = conn.execute("SELECT title FROM documents WHERE doc_id=?",
                       ("sha256:aaa",)).fetchone()
    assert row["title"] == "قانون قديم"
    conn.close()


def test_migration_is_idempotent_on_rerun(legacy_db):
    migrations.migrate(str(legacy_db))
    # إعادة التشغيل لا تفشل ولا تكرر الأعمدة (ALTER TABLE مزدوج يرمي خطأ
    # لو لم تُحرَس idempotency هنا فعلياً)
    report2 = migrations.migrate(str(legacy_db))
    assert report2["applied"] == []  # لا هجرات معلّقة بعد التطبيق الأول
    assert report2["end_version"] == migrations.LATEST


def test_crawl_runs_gets_branch_breakdown_column_when_table_exists(tmp_path, monkeypatch):
    db = tmp_path / "with_runs.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents (id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE,
                                clean_content TEXT, raw_content TEXT);
        CREATE TABLE sources (id INTEGER PRIMARY KEY, source_key TEXT UNIQUE,
                              base_url TEXT UNIQUE);
        CREATE TABLE crawl_runs (id INTEGER PRIMARY KEY, started_at TEXT,
                                 report TEXT);
    ''')
    conn.commit()
    conn.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "backups2")

    migrations.migrate(str(db))
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(crawl_runs)")}
    assert "branch_breakdown_json" in cols
    conn.close()


def test_fresh_db_has_identical_new_schema(tmp_path, monkeypatch):
    """قاعدة جديدة تماماً (create_tables) يجب أن تحوي نفس أعمدة/جداول
    المسار المُهاجَر — لا يجوز أن يفترق المساران."""
    db_path = tmp_path / "fresh_004.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.create_tables()

    conn = sqlite3.connect(db_path)
    doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"identity_key", "identity_confidence", "is_complete_text",
            "source_domain_tier", "quality_score"} <= doc_cols

    src_cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert "domain_tier" in src_cols

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"document_versions", "dedup_decisions",
            "source_performance"} <= tables

    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(crawl_runs)")}
    assert "branch_breakdown_json" in run_cols
    conn.close()
