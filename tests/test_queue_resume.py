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


# ── إعادة المهام الفاشلة للطابور (requeue_by / cli requeue) ──
def test_requeue_by_revives_failed_and_resets_attempts(tmp_path, monkeypatch):
    """المهمة الفاشلة خارج الطابور للأبد والبذر يتخطى رابطها — الإعادة
    هي سبيلها الوحيد (قِيس ف١-ب: مهمة ويبو فشلت قبل تثبيت pymupdf)."""
    conn = _tmp_db(tmp_path, monkeypatch)
    url = "https://wipo.int/wipolex/ar/legislation/details/10918"
    assert taskqueue.enqueue(conn, url, "ويبو", "topic") is True
    task = taskqueue.claim_next(conn)
    taskqueue.mark(conn, task["id"], "failed",
                   "wipo_pdf_module_missing", bump_attempts=True)
    # فخ الإنتاج: البذر الآن يتخطى الرابط أياً كانت حالة مهمته
    assert taskqueue.enqueue(conn, url, "ويبو", "topic") is False
    assert taskqueue.pending_count(conn) == 0

    revived = taskqueue.requeue_by(conn, ["failed"])
    assert len(revived) == 1 and revived[0]["status"] == "failed"
    row = conn.execute("SELECT status, attempts FROM crawl_tasks").fetchone()
    assert row["status"] == "queued" and row["attempts"] == 0
    assert taskqueue.pending_count(conn) == 1
    conn.close()


def test_requeue_by_status_and_contains_filters(tmp_path, monkeypatch):
    """لا تُلمس إلا الحالات المطلوبة؛ الرشح بالرابط يحصر النطاق."""
    conn = _tmp_db(tmp_path, monkeypatch)
    for url in ("https://x.org/a", "https://x.org/b", "https://moj.gov.sy/c"):
        taskqueue.enqueue(conn, url, "س", "topic")
    t = taskqueue.claim_next(conn)
    taskqueue.mark(conn, t["id"], "failed", "boom")            # a فشلت
    t = taskqueue.claim_next(conn)
    taskqueue.mark(conn, t["id"], "blocked", "robots_disallow")  # b حجبت
    # c تبقى queued

    revived = taskqueue.requeue_by(conn, ["failed"], contains="x.org")
    assert [r["url"] for r in revived] == ["https://x.org/a"]

    rows = {r["url"]: r["status"] for r in
            conn.execute("SELECT url, status FROM crawl_tasks")}
    assert rows["https://x.org/a"] == "queued"        # الفاشلة المستهدفة عادت
    assert rows["https://x.org/b"] == "blocked"       # ليست ضمن الحالة المطلوبة
    assert rows["https://moj.gov.sy/c"] == "queued"   # لم تُلمس أصلاً
    conn.close()


def test_cli_requeue_wiring(tmp_path, monkeypatch):
    """أمر cli يعرض المهام المعادة ويعيد صفراً، ولا شيء عند غياب المطابقات."""
    from cli import cmd_requeue

    class _Args:
        status = "failed"
        contains = "wipo"

    conn = _tmp_db(tmp_path, monkeypatch)
    assert cmd_requeue(_Args()) == 0  # لا مهام — تقرير نظيف بلا انفجار

    url = "https://wipo.int/wipolex/ar/legislation/details/10918"
    taskqueue.enqueue(conn, url, "ويبو", "topic")
    task = taskqueue.claim_next(conn)
    taskqueue.mark(conn, task["id"], "failed", "wipo_pdf_module_missing")
    assert cmd_requeue(_Args()) == 0
    row = conn.execute("SELECT status FROM crawl_tasks").fetchone()
    assert row["status"] == "queued"
    conn.close()


# ── إنقاذ المهام العالقة + فحص الطابور (requeue_stale_running / tasks) ──
def test_requeue_stale_running_revives_only_old(tmp_path, monkeypatch):
    """المهمة العالقة running من دورة منكسرة تعود للطابور؛ النشطة
    حديثاً (دورية حية موازية) لا تُلمس."""
    from datetime import datetime, timedelta
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://x.org/old", "س", "topic")
    taskqueue.enqueue(conn, "https://x.org/fresh", "س", "topic")
    t_old = taskqueue.claim_next(conn)
    t_fresh = taskqueue.claim_next(conn)
    stale = (datetime.now() - timedelta(minutes=30)).isoformat()
    conn.execute("UPDATE crawl_tasks SET updated_at=? WHERE id=?",
                 (stale, t_old["id"]))
    conn.commit()

    assert taskqueue.requeue_stale_running(conn) == 1
    rows = {r["url"]: r["status"] for r in
            conn.execute("SELECT url, status FROM crawl_tasks")}
    assert rows["https://x.org/old"] == "queued"      # العالقة أُنقذت
    assert rows["https://x.org/fresh"] == "running"   # الحية لم تُلمس
    conn.close()


def test_list_tasks_filters_and_limit(tmp_path, monkeypatch):
    """عين التشغيل: تصفية بالحالة وبالرابط وسقف عدد — بلا كتابة أبداً."""
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://wipo.int/details/1", "ويبو", "topic")
    taskqueue.enqueue(conn, "https://moj.gov.sy/a", "وزارة", "topic")
    taskqueue.enqueue(conn, "https://moj.gov.sy/b", "وزارة", "topic")
    t = taskqueue.claim_next(conn)                     # wipo → running
    assert taskqueue.list_tasks(conn, contains="wipo")[0]["id"] == t["id"]
    t = taskqueue.claim_next(conn)                     # moj/a → running
    taskqueue.mark(conn, t["id"], "failed", "boom")    # → failed
    failed = taskqueue.list_tasks(conn, statuses=["failed"])
    assert [r["url"] for r in failed] == ["https://moj.gov.sy/a"]
    assert failed[0]["last_error"] == "boom"
    assert len(taskqueue.list_tasks(conn, limit=2)) == 2
    conn.close()


def test_cli_tasks_wiring(tmp_path, monkeypatch):
    from cli import cmd_tasks

    class _Args:
        status = None
        contains = "wipo"
        limit = 50

    conn = _tmp_db(tmp_path, monkeypatch)
    assert cmd_tasks(_Args()) == 0  # لا مهام — تقرير نظيف
    taskqueue.enqueue(conn, "https://wipo.int/details/9", "ويبو", "topic")
    assert cmd_tasks(_Args()) == 0
    rows = taskqueue.list_tasks(conn, contains="wipo")
    assert len(rows) == 1 and rows[0]["status"] == "queued"
    conn.close()


# ── أدب الفشل + قاطع الدورة (حادثة ليلة syria-law 2026-09-17) ──
def test_polite_sleep_applies_to_failed_fetches(tmp_path, monkeypatch):
    """الفاشل ينتظر التأخير المهذب كالناجح — لا طرْق بلا حد بعد فشل."""
    sleeps = []
    monkeypatch.setattr(crawler.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(crawler, "fetch",
                        lambda url: {"ok": False, "error": "http_404"})
    conn = _tmp_db(tmp_path, monkeypatch)
    taskqueue.enqueue(conn, "https://x.org/f1", "س", "topic")
    taskqueue.enqueue(conn, "https://x.org/f2", "س", "topic")
    crawler.start_crawling(max_pages=5)
    rows = conn.execute("SELECT status FROM crawl_tasks").fetchall()
    assert [r["status"] for r in rows] == ["failed", "failed"]
    assert sleeps == [1.6, 1.6]      # كل صفحة انتظرت — حتى الفاشلة
    conn.close()


def test_circuit_breaker_stops_cycle_and_keeps_queue(tmp_path, monkeypatch):
    """موجة إخفاقات متتالية توقف الدورة (الطابور محفوظ لاستئناف لاحق)
    بدل استهلاك آلاف الصفحات ضد مصدر يحجب."""
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    monkeypatch.setattr(crawler, "fetch",
                        lambda url: {"ok": False, "error": "http_404"})
    conn = _tmp_db(tmp_path, monkeypatch)
    for i in range(15):
        taskqueue.enqueue(conn, f"https://x.org/p{i}", "س", "topic")
    crawler.start_crawling(max_pages=50)
    by = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM crawl_tasks GROUP BY status")}
    assert by.get("failed") == 12    # قاطع الدورة عند 12
    assert by.get("queued") == 3     # الباقي محفوظ بالطابور
    conn.close()
