"""اختبارات ربط النواة بالشاشات (التسليم 5): core_data + stop_event.

بلا Qt — الشاشات نفسها تُفحص بوضع --smoke في CI (QT_QPA_PLATFORM=offscreen).
"""
import csv
import sqlite3
import threading

import pytest

from app import core_data
from exporter import build_package
from migrations import migrate


@pytest.fixture
def wired_db(tmp_path, monkeypatch):
    """قاعدة حقيقية مصغرة مربوطة بـ core_data عبر config.DB_PATH."""
    import config
    import database
    db = tmp_path / "ui.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    monkeypatch.setattr(core_data, "PACKAGE_DIR", tmp_path / "pkg")
    database.create_tables()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    from crawler import save_document
    save_document(cur, "sha256:u1", "قانون الواجهة", "https://x/t1", "مدني",
                  0.8, 0.91, "md5", "نص", snapshot_sha256=None)
    conn.execute("INSERT INTO articles (doc_id, article_number, text,"
                 " char_count) VALUES (1, '1', 'نص مادة', 8)")
    import crawl_queue as taskqueue
    taskqueue.enqueue(conn, "https://x/f3", "القانون المدني", "section")
    taskqueue.enqueue(conn, "https://x/t1", "القانون المدني", "topic")
    conn.execute("INSERT INTO crawl_runs (started_at, mode, max_pages)"
                 " VALUES ('2026-09-05T10:00:00', 'live', 4)")
    conn.execute("INSERT INTO crawl_log (url, event_type, message, status,"
                 " timestamp) VALUES ('', 'fetch', 'حدث اختبار', 'ok',"
                 " '2026-09-05T10:00:01')")
    conn.commit()
    conn.close()
    return db


class TestCoreData:
    def test_documents_live(self, wired_db):
        docs = core_data.DOCUMENTS
        assert len(docs) == 1
        d = docs[0]
        assert d.title == "قانون الواجهة" and d.articles == 1
        assert d.status == "auto_extracted" and d.doc_id == 1
        assert d.quality == 0.91

    def test_run_stats(self, wired_db):
        s = core_data.RUN_STATS
        assert s["queue"] == {"queued": 2}
        assert s["docs"] == 1 and s["articles"] == 1
        assert s["last_run"]["mode"] == "live"

    def test_sections_from_queue(self, wired_db):
        assert core_data.SECTIONS == ["القانون المدني"]

    def test_log_events(self, wired_db):
        events = core_data.LOG_EVENTS
        assert events[-1][1] == "fetch" and "حدث اختبار" in events[-1][2]

    def test_sources_fallback(self, wired_db):
        # لا مصادر معتمدة بعد ⇒ المصدر الافتراضي الموثق (لا اختلاق)
        assert core_data.APPROVED_SOURCES == [core_data.DEFAULT_SOURCE]

    def test_values_refresh_not_cached(self, wired_db):
        assert len(core_data.DOCUMENTS) == 1
        conn = sqlite3.connect(wired_db)
        conn.execute("UPDATE documents SET title='بعد التحديث'")
        conn.commit(); conn.close()
        assert core_data.DOCUMENTS[0].title == "بعد التحديث"


class TestPackageGate:
    def test_validate_missing_then_real(self, wired_db, tmp_path):
        # قبل التوليد: بوابة صادقة لا checks وهمية
        checks = core_data.VALIDATION_CHECKS
        assert len(checks) == 1 and checks[0][1] is False
        build_package(wired_db, out_dir=tmp_path / "pkg")
        checks = core_data.VALIDATION_CHECKS
        assert checks and all(ok for _, ok in checks)
        tree = core_data.PACKAGE_TREE
        assert tree[0][1] is True and "laws_decrees_index.csv" in tree[1][0]


class TestStopEvent:
    def test_preset_stop_exits_without_fetch(self, wired_db, monkeypatch):
        """stop_event مضغوط مسبقاً ⇒ لا تُجلب أي صفحة (بلا شبكة)."""
        import crawler

        def _boom(*a, **k):
            raise AssertionError("لا يجوز الجلب مع إيقاف مسبق")
        monkeypatch.setattr(crawler, "fetch", _boom)
        ev = threading.Event(); ev.set()
        crawler.start_crawling(max_pages=5, dry_run=True, stop_event=ev)
        conn = sqlite3.connect(wired_db)
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC"
                           " LIMIT 1").fetchone()
        conn.close()
        assert run["mode"] == "dry"  # الدورة سُجلت وأُغلقت بأمان
