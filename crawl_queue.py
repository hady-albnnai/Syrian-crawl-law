# -*- coding: utf-8 -*-
"""crawl_queue.py — طابور زحف دائم قابل للاستئناف (التسليم 3).
(سُميت كذلك لأن queue.py يظلل المكتبة القياسية — قاعدة التعديل الآمن #2).

الطابور في SQLite لا في الذاكرة: إيقاف الأداة أو انقطاعها لا يضيع العمل،
وإعادة التشغيل تكمل من حيث توقفت بلا تكرار (url UNIQUE + حالات صريحة).
"""
from datetime import datetime

from urls import canonicalize_url

PARAMS_BY_KIND = {"section": ("start",), "topic": ()}


def enqueue(conn, url: str, section: str, kind: str) -> bool:
    """يدرج مهمة إن لم تكن موجودة — يعيد True عند الإنشاء."""
    key = canonicalize_url(url, keep_params=PARAMS_BY_KIND.get(kind, ()))
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM crawl_tasks WHERE url = ?", (key,))
    if cur.fetchone():
        return False
    cur.execute('''INSERT INTO crawl_tasks (url, section, kind, status, created_at)
                   VALUES (?, ?, ?, 'queued', ?)''',
                (key, section, kind, datetime.now().isoformat()))
    conn.commit()
    return True


def claim_next(conn):
    """أقدم مهمة queued → running. يعيد dict أو None."""
    cur = conn.cursor()
    cur.execute("SELECT id, url, section, kind, attempts FROM crawl_tasks "
                "WHERE status = 'queued' ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    cur.execute("UPDATE crawl_tasks SET status='running', updated_at=? WHERE id=?",
                (datetime.now().isoformat(), row["id"]))
    conn.commit()
    return dict(row)


def mark(conn, task_id: int, status: str, error: str = None,
         bump_attempts: bool = False):
    conn.execute('''UPDATE crawl_tasks SET status=?, last_error=?,
                    attempts = attempts + ?, updated_at=? WHERE id=?''',
                 (status, error, 1 if bump_attempts else 0,
                  datetime.now().isoformat(), task_id))
    conn.commit()


def requeue(conn, task_id: int):
    conn.execute("UPDATE crawl_tasks SET status='queued', updated_at=? WHERE id=?",
                 (datetime.now().isoformat(), task_id))
    conn.commit()


def pending_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) c FROM crawl_tasks "
                        "WHERE status IN ('queued','running')").fetchone()["c"]


def counts_by_status(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) c FROM crawl_tasks "
                        "GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
