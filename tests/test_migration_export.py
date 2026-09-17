"""اختبارات التسليم 4: هجرات sha256 + Exporter حزمة المحتوى (ADR-001)."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

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
        assert rep["start_version"] == 0
        assert rep["end_version"] == migrations.LATEST
        assert rep["applied"][0]["backfilled"] == 2
        assert rep["applied"][1]["version"] == 2  # chunks+FTS5
        assert rep["applied"][2]["version"] == 3  # sources.decided_by
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
        assert rep2["applied"] == []
        assert rep2["end_version"] == migrations.LATEST

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

    def test_snapshot_present_still_hashes_exported_file(self, package,
                                                          tmp_path,
                                                          monkeypatch):
        """مع لقطة خام موجودة ⇒ البصمة **تبقى** لملف md المُصدَّر.

        عطل مقاس 2026-09-17: كانت البصمة تُؤخذ من اللقطة، فترفض بوابة
        السلامة في ميزان (csv_legal_library_importer) كل وثيقة مزحوفة
        بصفتها «بصمة غير مطابقة» — لأن التطبيق يحمّص local_path لا اللقطة.
        اللقطة تبقى موثقة في JSON الجانبي (snapshot_sha256) للاستهلاك الآلي.
        """
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
        md = out / r["local_path"].split("laws_decrees/")[1]
        assert r["sha256"] == hashlib.sha256(md.read_bytes()).hexdigest()
        assert r["sha256"] != hashlib.sha256(b"<html>raw</html>").hexdigest()
        js = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
        assert js["snapshot_sha256"] == "sha256:deadbeef"  # الإسناد لم يُفقد


def test_app_integrity_gate_would_admit_every_row(tmp_path, monkeypatch):
    """حارس الحدّ مع ميزان: بصمة كل صَفْر = بصمة الملف الذي يفتحه التطبيق.

    يُحاكي منطق planCsvImport في csv_legal_library_importer.dart:
      file = '$root/${local_path}' ، ثم sha256(bytes) == بصمة الفهرس
      (مع سماح التطبيع CRLF→LF الذي يعمل به التطبيق). أي تغيير في exporter
      يجعل الحزمة غير قابلة للاستيراد يُسقط هذا الاختبار فوراً.
    """
    db = tmp_path / "gate.db"
    conn = sqlite3.connect(db)
    conn.executescript('''
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT UNIQUE,
            title TEXT, doc_type TEXT, number INTEGER, year INTEGER,
            branch TEXT, source_url TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            review_status TEXT DEFAULT 'auto_accepted',
            content_sha256 TEXT, snapshot_sha256 TEXT, legal_status TEXT);
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER,
            article_number TEXT, article_label TEXT, text TEXT,
            paragraphs_json TEXT, hierarchy_path TEXT, char_count INTEGER);
    ''')
    # (أ) وثيقة بلقطة خام على القرص — نفس الحادثة الأصلية
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "aabb.html").write_bytes(b"<html>raw</html>")
    conn.execute("INSERT INTO documents (id, doc_id, title, doc_type, number,"
                 " year, branch, source_url, status, snapshot_sha256)"
                 " VALUES (1,'sha256:g1','قانون البوابة','law',11,2024,'مدني',"
                 " 'https://x/t1','active','sha256:aabb')")
    conn.execute("INSERT INTO documents (id, doc_id, title, doc_type, number,"
                 " year, branch, source_url, status)"
                 " VALUES (2,'sha256:g2','بلا لقطة','law',12,2024,'جزائي',"
                 " 'https://x/t2','active')")
    conn.execute("INSERT INTO articles (doc_id, article_number, article_label,"
                 " text, char_count) VALUES (1,'1','المادة 1','نص',3)")
    conn.commit()
    conn.close()
    out = tmp_path / "pkg"
    monkeypatch.setattr(exporter, "SNAPSHOT_DIR", snap_dir)
    exporter.build_package(db, out_dir=out)
    rows = list(csv.DictReader(open(out / "laws_decrees_index.csv",
                                     encoding="utf-8-sig")))
    assert len(rows) == 2, "الحزمة يجب أن تحمل الوثيقتين"
    for r in rows:
        # التطبيق: File('$root/${local_path}') بجذر الحزمة — والنسق عندنا
        # أن markdown/ يقع مباشرة تحت جذر الحزمة
        f = out / "markdown" / Path(r["local_path"]).name
        assert f.exists(), f"ميزان كان سيتخطى الصَفْر ملفقوداً: {r['id']}"
        b = f.read_bytes()
        ok = {hashlib.sha256(b).hexdigest(),
              hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()}
        assert r["sha256"].lower() in ok, (
            f"بوابة السلامة في ميزان كانت ستتخطى '{r['id']}' "
            f"بصفتها بصمة غير مطابقة — local_path لا تطابقه البصمة")
        assert int(r["size_bytes"]) == len(b)
