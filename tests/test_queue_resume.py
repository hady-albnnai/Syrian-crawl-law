# -*- coding: utf-8 -*-
"""اختبارات الزحف القابل للاستئناف (التسليم 3) — محلية بلا شبكة."""
from pathlib import Path

import database
import crawl_queue as taskqueue
import crawler
from crawler import (extract_pagination_links, extract_topic_links,
                     save_snapshot)
from fetcher import classify_error
from urls import canonicalize_url

FIX = Path(__file__).parent / "fixtures"
SECTION_HTML = (FIX / "phpbb_section.html").read_text(encoding="utf-8")


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "q.db"))
    database.create_tables()
    return database.get_connection()


# ── تطبيع الروابط ──
def test_canonical_strips_tracking_keeps_start():
    a = canonicalize_url("https://X.org/f3?sid=abc123", keep_params=("start",))
    b = canonicalize_url("https://x.org/f3", keep_params=("start",))
    assert a == b
    c = canonicalize_url("https://x.org/f3?start=25&sid=z", keep_params=("start",))
    assert c == "https://x.org/f3?start=25"
    assert c != b


# ── الطابور ──
def test_enqueue_idempotent(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    assert taskqueue.enqueue(conn, "https://x.org/t1?a=1", "س", "topic") is True
    assert taskqueue.enqueue(conn, "https://x.org/t1", "س", "topic") is False
    n = conn.execute("SELECT COUNT(*) c FROM crawl_tasks").fetchone()["c"]
    assert n == 1
    conn.close()


def test_section_pagination_distinct_tasks(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://x.org/f3", "س", "section")
    taskqueue.enqueue(conn, "https://x.org/f3?start=25", "س", "section")
    n = conn.execute("SELECT COUNT(*) c FROM crawl_tasks").fetchone()["c"]
    assert n == 2
    conn.close()


def test_claim_fifo_and_resume(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    for i in (1, 2, 3):
        taskqueue.enqueue(conn, f"https://x.org/t{i}", "س", "topic")
    t1 = taskqueue.claim_next(conn)
    assert t1["url"].endswith("/t1") and t1 is not None
    taskqueue.mark(conn, t1["id"], "success")

    # «إعادة تشغيل» باتصال جديد على نفس القاعدة — الاستئناف يكمل الباقي فقط
    conn2 = database.get_connection()
    assert taskqueue.pending_count(conn2) == 2
    t2 = taskqueue.claim_next(conn2)
    assert t2["url"].endswith("/t2")
    conn.close(); conn2.close()


def test_requeue_on_transient_error(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://x.org/t9", "س", "topic")
    t = taskqueue.claim_next(conn)
    taskqueue.mark(conn, t["id"], "queued", "max_retries_exceeded",
                   bump_attempts=True)
    row = conn.execute("SELECT status, attempts FROM crawl_tasks "
                       "WHERE id=?", (t["id"],)).fetchone()
    assert row["status"] == "queued" and row["attempts"] == 1
    conn.close()


# ── تصنيف الأخطاء ──
def test_classify_error_mapping():
    assert classify_error("blocked_by_robots") == "block"
    assert classify_error("http_404") == "fail"
    assert classify_error("http_410") == "fail"
    assert classify_error("http_503") == "retry"
    assert classify_error("max_retries_exceeded") == "retry"


# ── pagination + مواضيع ──
def test_pagination_links_extracted():
    links = extract_pagination_links(SECTION_HTML, "https://x.org/")
    assert len(links) == 2
    assert all("start=" in l for l in links)


def test_topic_links_extracted():
    links = extract_topic_links(SECTION_HTML, "https://x.org/")
    assert len(links) == 3


# ── لقطات خارج Git ──
def test_snapshot_written_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "SNAPSHOT_DIR", tmp_path / "snap")
    h = save_snapshot("<html>تجربة</html>")
    assert h.startswith("sha256:")
    assert (tmp_path / "snap" / (h.split(":")[1] + ".html")).exists()
