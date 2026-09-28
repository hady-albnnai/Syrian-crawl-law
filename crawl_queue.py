# -*- coding: utf-8 -*-
"""crawl_queue.py — طابور زحف دائم قابل للاستئناف (التسليم 3).
(سُميت كذلك لأن queue.py يظلل المكتبة القياسية — قاعدة التعديل الآمن #2).

الطابور في SQLite لا في الذاكرة: إيقاف الأداة أو انقطاعها لا يضيع العمل،
وإعادة التشغيل تكمل من حيث توقفت بلا تكرار (url UNIQUE + حالات صريحة).
"""
from datetime import datetime, timedelta
from urllib.parse import urlparse

from urls import canonicalize_url


def _valid_http_url(url: str):
    try:
        parsed = urlparse((url or "").strip())
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                parsed.username or parsed.password):
            return None
        # الوصول إلى .port يكشف رقم منفذ مشوهاً.
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            return None
        return parsed, port
    except (AttributeError, ValueError):
        return None


def approved_source_for_url(conn, url: str):
    """يعيد سجل المصدر approved الذي يغطي origin والمسار، وإلا None.

    مطابقة www اختيارية؛ أما المخطط والمنفذ وحدود المسار فمطابقة صريحة،
    لتجنب أن يغطي اعتماد HTTPS خدمة HTTP أو منفذاً/مجلداً آخر بالخطأ.
    """
    parsed_result = _valid_http_url(url)
    if parsed_result is None:
        return None
    target, target_port = parsed_result
    target_host = (target.hostname or "").lower().rstrip(".").removeprefix("www.")
    target_path = (target.path or "/").rstrip("/") or "/"
    rows = conn.execute(
        "SELECT id, base_url, name, source_role, status FROM sources "
        "WHERE status='approved' AND base_url IS NOT NULL ORDER BY id").fetchall()
    for row in rows:
        parsed_result = _valid_http_url(row["base_url"] or "")
        if parsed_result is None:
            continue
        base, base_port = parsed_result
        base_host = (base.hostname or "").lower().rstrip(".").removeprefix("www.")
        if (base.scheme != target.scheme or base_port != target_port or
                not base_host or base_host != target_host):
            continue
        base_path = (base.path or "/").rstrip("/") or "/"
        if base_path != "/" and not (
                target_path == base_path or target_path.startswith(base_path + "/")):
            continue
        return dict(row)
    return None


def enqueue_approved_url(conn, url: str, section: str, kind: str):
    """يدرج رابطاً واحداً فقط إذا كان ضمن source approved.

    يعيد ``(enqueued, source_id)``؛ ``source_id=None`` يعني أن الاعتماد أو
    نطاقه لا يغطي الرابط، بينما False مع ID يعني أن المهمة موجودة مسبقاً.
    """
    source = approved_source_for_url(conn, url)
    if source is None:
        return False, None
    return enqueue(conn, url, section, kind), source["id"]

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


def enqueue_approved_sources(conn, source_ids=None) -> list[dict]:
    """إدراج صريح لمصادر معتمدة في الطابور؛ الاعتماد وحده لا يدرج مهاماً.

    إذا أُعطيت IDs، يجب أن يكون كل مصدر منها approved؛ وإلا يُرفض الطلب
    كاملاً قبل أي إدراج لتجنب طابور جزئي ناتج عن خطأ في الاختيار.
    """
    requested = None if source_ids is None else [int(x) for x in source_ids]
    if requested is not None and not requested:
        return []
    if requested is None:
        rows = conn.execute(
            "SELECT id, base_url, name FROM sources WHERE status='approved' "
            "AND base_url IS NOT NULL ORDER BY id").fetchall()
    else:
        placeholders = ",".join("?" for _ in requested)
        rows = conn.execute(
            f"SELECT id, base_url, name, status FROM sources WHERE id IN "
            f"({placeholders}) ORDER BY id", requested).fetchall()
        by_id = {row["id"]: row for row in rows}
        missing = [sid for sid in requested if sid not in by_id]
        unapproved = [sid for sid in requested
                      if sid in by_id and by_id[sid]["status"] != "approved"]
        if missing or unapproved:
            raise ValueError(f"مصادر غير قابلة للإدراج؛ مفقود={missing} "
                             f"غير معتمد={unapproved}")

    invalid_urls = [row["id"] for row in rows
                    if _valid_http_url(row["base_url"] or "") is None]
    if invalid_urls:
        raise ValueError(f"مصادر approved ذات base_url غير صالح: {invalid_urls}")

    added = []
    for row in rows:
        name = row["name"] or row["base_url"]
        created = enqueue(conn, row["base_url"], name, "section")
        added.append({"source_id": row["id"], "url": row["base_url"],
                      "section": name, "enqueued": created})
    return added


def claim_next(conn, domain: str | None = None):
    """أقدم مهمة queued → running. يعيد dict أو None.

    domain: عامل متوازٍ يأخذ مهام نطاقه فقط (ف٤). الحجز ذرّي: UPDATE مشروط
    بـstatus='queued' فلا يأخذ عاملان المهمة نفسها ولو تزامنا."""
    cur = conn.cursor()
    for _ in range(5):
        if domain:
            cur.execute("SELECT id, url, section, kind, attempts FROM crawl_tasks "
                        "WHERE status = 'queued' AND (url LIKE ? OR url LIKE ?) ORDER BY id LIMIT 1",
                        (f"%://{domain}/%", f"%://www.{domain}/%"))
        else:
            cur.execute("SELECT id, url, section, kind, attempts FROM crawl_tasks "
                        "WHERE status = 'queued' ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("UPDATE crawl_tasks SET status='running', updated_at=? "
                    "WHERE id=? AND status='queued'",
                    (datetime.now().isoformat(), row["id"]))
        conn.commit()
        if cur.rowcount == 1:
            return dict(row)
    return None


def queued_domains(conn) -> list[tuple[str, int]]:
    """[(نطاق, عدد المهام المنتظرة)] تنازلياً — لتوزيع العمّال."""
    from urllib.parse import urlparse
    counts = {}
    for (url,) in conn.execute("SELECT url FROM crawl_tasks WHERE status='queued'"):
        d = (urlparse(url).netloc or "").lower()
        if d.startswith("www."):
            d = d[4:]
        if d:
            counts[d] = counts.get(d, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def mark(conn, task_id: int, status: str, error: str = None,
         bump_attempts: bool = False):
    conn.execute('''UPDATE crawl_tasks SET status=?, last_error=?,
                    attempts = attempts + ?, updated_at=? WHERE id=?''',
                 (status, error, 1 if bump_attempts else 0,
                  datetime.now().isoformat(), task_id))
    conn.commit()


def requeue(conn, task_id: int):
    """إعادة مهمة واحدة إلى الطابور مع تصفير عدّاد المحاولات.

    التصفير ليس تجميلاً: `requeue_by` يصفّر، وهذه كانت تُبقي attempts كما هي
    (قِيس: مهمة أُعيدت بـattempts=3 بقيت مُدانَة بعدّادها في `app/core_data`
    الذي يستدعيها صفاً صفاً) — فمسار «المحدد» كان أنقص جودة من مسار «الكل».
    الآن النواتان فعل واحد.
    """
    conn.execute("UPDATE crawl_tasks SET status='queued', attempts=0, "
                 "updated_at=? WHERE id=?",
                 (datetime.now().isoformat(), task_id))
    conn.commit()


def requeue_by(conn, statuses, contains=None):
    """إعادة مهام بالحالات المعطاة إلى الطابور مع تصفير عدّاد المحاولات.

    يعيد قائمة المهام المعادة (dicts: id/url/status/last_error).
    البذر (enqueue) يتخطى الرابط الموجود أياً كانت حالته، والمهمة
    الفاشلة لا تُلتقط من الطابور ثانية — هذه هي العودة الوحيدة لها.
    لا تمسّ queued/running/needs_review إلا بطلب صريح عبر statuses.
    """
    statuses = [s for s in statuses if s]
    if not statuses:
        return []
    sql = ("SELECT id, url, status, last_error FROM crawl_tasks "
           f"WHERE status IN ({','.join('?' * len(statuses))})")
    params = list(statuses)
    if contains:
        sql += " AND url LIKE ?"
        params.append(f"%{contains}%")
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    conn.execute(f"UPDATE crawl_tasks SET status='queued', attempts=0, "
                 f"updated_at=? WHERE id IN ({','.join('?' * len(ids))})",
                 (datetime.now().isoformat(), *ids))
    conn.commit()
    return [dict(r) for r in rows]


def pending_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) c FROM crawl_tasks "
                        "WHERE status IN ('queued','running')").fetchone()["c"]


def requeue_stale_running(conn, stale_minutes: int = 10) -> int:
    """إعادة مهام running العالقة إلى الطابور — يعيد عدد المهام المنقذة.

    المهمة تُعلَّم running لحظة التقاطها؛ إن انكسرت الدورة أثناءها
    (انقطاع كهرباء، Ctrl+C، استثناء غير محتوى) تبقى running إلى الأبد
    ولا يلتقطها claim_next ثانية — هذا هو الإنقاذ الوحيد لها. المهلة
    تحمي دورية حية متوازيتين (الواجهة) من سرقة مهمتها النشطة.
    """
    cutoff = (datetime.now() - timedelta(minutes=stale_minutes)).isoformat()
    cur = conn.execute(
        "UPDATE crawl_tasks SET status='queued', updated_at=? "
        "WHERE status='running' AND updated_at < ?",
        (datetime.now().isoformat(), cutoff))
    conn.commit()
    return cur.rowcount


def list_tasks(conn, statuses=None, contains=None, limit: int = 100):
    """قائمة مهام للفحص التشغيلي (read-only) — الأحدث أولاً.

    رؤية الطابور شرط تشخيصه: أعمدة الحالة والمحاولات وآخر عطل هي
    ما يحسم أين انتهت مهمة ولماذا (قِيس جولة تصحيح ويبو عند المالك).
    """
    sql = ("SELECT id, url, section, kind, status, attempts, last_error, "
           "updated_at FROM crawl_tasks")
    where, params = [], []
    statuses = [s for s in (statuses or []) if s]
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if contains:
        where.append("url LIKE ?")
        params.append(f"%{contains}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def counts_by_status(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) c FROM crawl_tasks "
                        "GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
