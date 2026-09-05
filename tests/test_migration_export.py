"""اختبارات التسليم 4: هجرات sha256 + Exporter حزمة المحتوى (ADR-001)."""
import csv
import hashlib
import json
import sqlite3

import pytest

import migrations
import exporter
from crawler import save_document
from database import create_tables


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """قاعدة بمخطط ما قبل التسليم 4 (بلا أعمدة sha256) ووثيقتين."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE, title TEXT, doc_type TEXT,
            number INTEGER, year INTEGER, branch TEXT,
            branch_confidence REAL, source_url TEXT UNIQUE,
            source_credibility REAL DEFAULT 0.6,
            status TEXT DEFAULT 'active',
            review_status TEXT DEFAULT 'auto_accepted',
            legal_score REAL, content_hash TEXT,
            scraped_at TEXT, updated_at TEXT,
            raw_content TEXT, clean_content TEXT
        );
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER, article_number TEXT, article_label TEXT,
            hierarchy_path TEXT, text TEXT, paragraphs_json TEXT,
            related_articles_json TEXT, amended_by TEXT,
            status TEXT DEFAULT 'active', char_count INTEGER
        );
    ''')
    conn.execute(
        "INSERT INTO documents (doc_id, title, doc_type, number, year,"
        " branch, source_url, content_hash, clean_content) VALUES"
        " ('sha256:aaa', 'قانون الاختبار', 'law', 42, 2020, 'مدني',"
        " 'https://example.com/t1', 'md5legacy', 'نص نظيف قديم')")
    conn.execute(
        "INSERT INTO documents (doc_id, title, doc_type, number, year,"
        " branch, source_url, clean_content) VALUES"
        " ('sha256:bbb', 'وثيقة بلا مواد', 'law', 7, 2021, 'جزائي',"
        " 'https://example.com/t2', 'نص ثان')")
    conn.execute(
        "INSERT INTO articles (doc_id, article_number, article_label, text,"
        " char_count) VALUES (1, '1', 'المادة 1', 'نص المادة الأولى', 18)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "backups")
    return db


class TestMigrations:
    def test_backfill_and_version(self, legacy_db):
        rep = migrations.migrate(legacy_db)
        assert rep["start_version"] == 0 and rep["end_version"] == 2
        assert rep["applied"][0]["backfilled"] == 2
        assert rep["applied"][1]["version"] == 2  # chunks+FTS5
        conn = sqlite3.connect(legacy_db)
        row = conn.execute("SELECT content_sha256, content_hash FROM"
                           " documents WHERE doc_id='sha256:aaa'").fetchone()
        expect = hashlib.sha256("نص نظيف قديم".encode("utf-8")).hexdigest()
        assert row[0] == expect
        assert row[1] == "md5legacy"  # البصمة التاريخية لا تُمس
        conn.close()

    def test_idempotent(self, legacy_db):
        migrations.migrate(legacy_db)
        rep2 = migrations.migrate(legacy_db)
        assert rep2["applied"] == [] and rep2["end_version"] == 2

    def test_backup_created(self, legacy_db, tmp_path):
        rep = migrations.migrate(legacy_db)
        assert len(rep["backups"]) == 1
        import pathlib
        assert pathlib.Path(rep["backups"][0]).exists()


class TestExporter:
    @pytest.fixture
    def package(self, legacy_db, tmp_path):
        migrations.migrate(legacy_db)
        out = tmp_path / "pkg"
        rep = exporter.build_package(legacy_db, out_dir=out)
        return rep, out, legacy_db

    def test_csv_header_exact(self, package):
        _, out, _ = package
        raw = (out / "laws_decrees_index.csv").read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # BOM كحزمة ميزان
        header = raw.decode("utf-8-sig").splitlines()[0]
        assert header == ",".join(exporter.COLUMNS)

    def test_rows_and_md_json(self, package):
        rep, out, _ = package
        assert rep["docs"] == 2
        rows = list(csv.DictReader(
            open(out / "laws_decrees_index.csv", encoding="utf-8-sig")))
        r = next(r for r in rows if r["id"] == "law_2020_42")
        assert r["type"] == "قانون" and r["category"] == "مدني"
        assert r["date"] == ""  # لا يُختلق تاريخ إصدار
        md = (out / r["local_path"].split("laws_decrees/")[1])
        assert md.exists()
        text = md.read_text(encoding="utf-8")
        assert "# قانون الاختبار" in text and "## المادة 1" in text
        js = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
        assert js["articles"][0]["number"] == "1"
        assert js["content_sha256"]  # ربط بالبصمة المعتمدة

    def test_sha256_semantics_md_fallback(self, package):
        """بلا لقطة خام ⇒ البصمة لملف md نفسه (موثق في التقرير)."""
        _, out, _ = package
        rows = list(csv.DictReader(
            open(out / "laws_decrees_index.csv", encoding="utf-8-sig")))
        for r in rows:
            f = out / "markdown" / r["local_path"].split("/")[-1]
            assert r["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
            assert int(r["size_bytes"]) == f.stat().st_size

    def test_snapshot_hash_preferred(self, package, tmp_path, monkeypatch):
        """مع لقطة خام ⇒ البصمة للملف المصدري (دلالة حزمة ميزان)."""
        _, out, db = package
        snap = tmp_path / "snaps"
        snap.mkdir()
        (snap / "deadbeef.html").write_bytes(b"<html>raw</html>")
        monkeypatch.setattr(exporter, "SNAPSHOT_DIR", snap)
        conn = sqlite3.connect(db)
        conn.execute("UPDATE documents SET snapshot_sha256='sha256:deadbeef'"
                     " WHERE doc_id='sha256:bbb'")
        conn.commit()
        conn.close()
        exporter.build_package(db, out_dir=out)
        rows = list(csv.DictReader(
            open(out / "laws_decrees_index.csv", encoding="utf-8-sig")))
        r = next(r for r in rows if r["id"] == "law_2021_7")
        expect = hashlib.sha256(b"<html>raw</html>").hexdigest()
        assert r["sha256"] == expect

    def test_min_articles_filter(self, legacy_db, tmp_path):
        migrations.migrate(legacy_db)
        rep = exporter.build_package(legacy_db,
                                     out_dir=tmp_path / "pkg2",
                                     min_articles=1)
        assert rep["docs"] == 1 and rep["skipped"] == 1


def test_sanitize_filename():
    # المحارف غير الآمنة على Windows تُحذف؛ «؟» العربية آمنة وتبقى
    assert exporter.sanitize_filename('قانون: أ/ب <ج>؟*') == "قانون_أب_ج؟"
    assert exporter.sanitize_filename("") == "بدون_عنوان"


def test_new_docs_get_sha256(tmp_path, monkeypatch):
    """الحفظ الجديد يكتب content_sha256 مباشرة (مخطط بعد الهجرة)."""
    import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "new.db")
    create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    save_document(cur, "sha256:zzz", "وثيقة", "https://x/t", "مدني",
                  0.8, 0.9, "md5x", "نص حديث", snapshot_sha256=None)
    conn.commit()
    row = conn.execute(
        "SELECT content_sha256 FROM documents").fetchone()
    expect = hashlib.sha256("نص حديث".encode("utf-8")).hexdigest()
    assert row[0] == expect
    conn.close()
