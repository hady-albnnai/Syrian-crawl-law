# -*- coding: utf-8 -*-
"""هجرة 013: حفظ تقييم المصدر آلياً دون تحويله إلى قرار اعتماد/رفض."""
import sqlite3

import database
import migrations


def test_migration_013_adds_evaluation_columns_and_preserves_sources(
        tmp_path, monkeypatch):
    db = tmp_path / "legacy_012.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents (id INTEGER PRIMARY KEY, clean_content TEXT);
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT UNIQUE, base_url TEXT UNIQUE, name TEXT,
            engine TEXT, credibility REAL DEFAULT 0.6,
            status TEXT DEFAULT 'proposed', discovered_via TEXT,
            discovered_at TEXT, decided_at TEXT, decided_by TEXT,
            domain_tier INTEGER DEFAULT 4, rejection_count INTEGER DEFAULT 0
        );
        INSERT INTO sources (source_key, base_url, name, status)
        VALUES ('s1', 'https://example.org/', 'مصدر قائم', 'proposed');
        PRAGMA user_version = 12;
    ''')
    conn.commit()
    conn.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "backups")

    report = migrations.migrate(str(db))
    assert report["end_version"] == 13

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    expected = {"evaluation_score", "evaluation_verdict", "source_type",
                "evaluation_reasons_json", "evaluation_details_json",
                "evaluated_at", "evaluation_sample_count"}
    assert expected <= cols
    row = conn.execute("SELECT name, status FROM sources WHERE source_key='s1'").fetchone()
    assert row == ("مصدر قائم", "proposed")
    conn.close()

    assert migrations.migrate(str(db))["applied"] == []


def test_fresh_database_has_assessment_columns(tmp_path, monkeypatch):
    db = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db))
    database.create_tables()
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    assert {"evaluation_score", "evaluation_verdict", "source_type",
            "evaluation_reasons_json", "evaluation_details_json",
            "evaluated_at", "evaluation_sample_count"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST
    conn.close()
