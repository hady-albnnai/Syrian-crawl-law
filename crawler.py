# -*- coding: utf-8 -*-
"""crawler.py — v2.4 (التسليم 3): زحف قابل للاستئناف.

الطابور دائم في SQLite (crawl_tasks): الإيقاف/الانقطاع لا يضيع العمل،
والاستئناف يكمل بلا تكرار. كل دورة زحف تسجل في crawl_runs بتقرير.
اللقطات الخام تُحفظ خارج Git (data/snapshots) للتدقيق وإعادة الاستخراج.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import crawl_queue as taskqueue
from config import BASE_URL, SAVE_RAW_HTML
from database import get_connection
from extractor import detect_branch, is_legal_content, legal_score
from extractor_v4 import extract_main_content
from fetcher import classify_error, fetch
from logging_setup import get_log
from urls import canonicalize_url, clean_url  # إعادة تصدير للتوافق

log = get_log("crawl")

SNAPSHOT_DIR = Path(__file__).parent / "data" / "snapshots"
MAX_TASK_ATTEMPTS = 2


def make_doc_id(url: str) -> str:
    """معرّف وثيقة مستقر مشتق من الرابط المطبَّع — لا من وقت التشغيل (P0)."""
    normalized = canonicalize_url(url)
    return "sha256:" + hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def get_hash(text: str) -> str:
    # md5 تاريخي لمحتوى clean_content — الترحيل إلى sha256 قرار تسليم 4 (ADR-001)
    return hashlib.md5(text.strip().encode('utf-8')).hexdigest()


def save_document(cursor, doc_id, title, url, branch, confidence, score,
                  content_hash, clean_text):
    """حفظ idempotent: فحص doc_id قبل الإدراج (P0). يعيد (row_id, created)."""
    cursor.execute("SELECT id FROM documents WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    if row is not None:
        return row["id"], False
    cursor.execute('''
        INSERT INTO documents
        (doc_id, title, source_url, branch, branch_confidence, legal_score,
         content_hash, scraped_at, clean_content, doc_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (doc_id, title, url, branch, confidence, score, content_hash,
          datetime.now().isoformat(), clean_text, "law"))
    return cursor.lastrowid, True


def extract_topic_links(html: str, base_url: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if re.search(r"/t\d+", href):
            full = clean_url(urljoin(base_url, href))
            if full not in links:
                links.append(full)
    return links[:30]


def extract_pagination_links(html: str, base_url: str, limit: int = 3) -> list:
    """روابط صفحات الأقسام التالية (start=) — تدعم pagination المنتدى."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "start=" in href and re.search(r"/f\d+|[?&]f=\d+", href):
            full = urljoin(base_url, href)
            if full not in out:
                out.append(full)
            if len(out) >= limit:
                break
    return out


def save_snapshot(html: str) -> str:
    """لقطة خام خارج Git للتدقيق وإعادة الاستخراج (ROADMAP §4.1)."""
    h = "sha256:" + hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / (h.split(":")[1] + ".html")).write_text(html, encoding="utf-8")
    return h


def _handle_topic(conn, task, html, dry_run, stats):
    ext = extract_main_content(html, task["url"])
    if not ext["success"]:
        taskqueue.mark(conn, task["id"], "failed", ext.get("error"))
        stats["failures"] += 1
        log.info(f"   ⚠️ فشل الاستخراج: {ext.get('error')}")
        return
    title, clean = ext["title"], ext["clean_text"]
    articles = ext["articles"]
    if SAVE_RAW_HTML:
        save_snapshot(html)
    if not is_legal_content(clean, title):
        taskqueue.mark(conn, task["id"], "needs_review", "غير قانوني ظاهرياً")
        log.info("   ⚠️ لم يجتز الفحص القانوني — needs_review")
        return
    content_hash = get_hash(clean)
    if dry_run:
        taskqueue.mark(conn, task["id"], "success")
        stats["docs"] += 1
        stats["articles"] += len(articles)
        log.info(f"   [dry-run] سيُحفظ: {title[:60]} ({len(articles)} مادة، "
                 f"جودة {ext['quality_score']})")
        return
    branch, confidence = detect_branch(clean, task["section"])
    cursor = conn.cursor()
    doc_row_id, created = save_document(
        cursor, make_doc_id(task["url"]), title, task["url"], branch,
        float(confidence), legal_score(clean, title), content_hash,
        clean[:15000])
    if not created:
        conn.commit()
        taskqueue.mark(conn, task["id"], "success")
        stats["skipped"] += 1
        log.info("   🔁 الوثيقة محفوظة سابقاً — تخطي بلا تكرار")
        return
    for art in articles:
        cursor.execute('''
            INSERT INTO articles (doc_id, article_number, article_label,
                                text, paragraphs_json, hierarchy_path, char_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (doc_row_id, str(art["article_number"]), art["label"], art["text"],
              json.dumps(art.get("paragraphs", []), ensure_ascii=False),
              json.dumps(art.get("hierarchy_path", []), ensure_ascii=False),
              art["char_count"]))
        stats["articles"] += 1
    conn.commit()
    taskqueue.mark(conn, task["id"], "success")
    stats["docs"] += 1
    log.info(f"   ✅ حُفظت {title[:60]} ({len(articles)} مادة)")


def start_crawling(max_pages=40, dry_run=False):
    log.info("=" * 100)
    log.info(f"🚀 الزاحف القابل للاستئناف v2.4 — طابور دائم + تقرير دورة")
    log.info(f"الحد الأقصى: {max_pages} | الوضع: {'تجريبي' if dry_run else 'فعلي'} | "
             f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    log.info("-" * 100)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO crawl_runs (started_at, mode, max_pages) "
                "VALUES (?, ?, ?)",
                (datetime.now().isoformat(), "dry" if dry_run else "live",
                 max_pages))
    run_id = cur.lastrowid
    conn.commit()

    # بذر الطابور إن كان فارغاً تماماً (أول تشغيل)
    if taskqueue.pending_count(conn) == 0 and not conn.execute(
            "SELECT 1 FROM crawl_tasks WHERE status='success' LIMIT 1").fetchone():
        for path, section in [(f"{BASE_URL}f3-montada", "القانون المدني"),
                              (f"{BASE_URL}f9-montada", "القانون الجزائي"),
                              (f"{BASE_URL}f15-montada", "أصول المحاكمات"),
                              (f"{BASE_URL}f24-montada", "الأحوال الشخصية"),
                              (f"{BASE_URL}f14-montada", "القانون التجاري"),
                              (f"{BASE_URL}f4-montada", "الدساتير")]:
            taskqueue.enqueue(conn, path, section, "section")
        log.info(" بُذر الطابور بأقسام البداية")

    stats = {"pages": 0, "docs": 0, "articles": 0, "skipped": 0, "failures": 0}
    while stats["pages"] < max_pages:
        task = taskqueue.claim_next(conn)
        if task is None:
            log.info("📭 الطابور فارغ — لا عمل متبقٍ")
            break
        stats["pages"] += 1
        log.info(f"[{stats['pages']}/{max_pages}] {'📂' if task['kind']=='section' else '📄'} "
                 f"{task['section']} ← {task['url'][:70]}")

        result = fetch(task["url"])
        if not result.get("ok"):
            err = result.get("error", "fetch_failed")
            kind = classify_error(err)
            if kind == "block":
                taskqueue.mark(conn, task["id"], "blocked", err)
            elif kind == "retry" and task["attempts"] < MAX_TASK_ATTEMPTS:
                taskqueue.mark(conn, task["id"], "queued", err, bump_attempts=True)
                log.info(f"   ↻ عطل عابر ({err}) — أعيدت المهمة للطابور")
                stats["pages"] -= 1  # الإعادة لا تُحتسب صفحة جديدة
                continue
            else:
                taskqueue.mark(conn, task["id"], "failed", err)
                stats["failures"] += 1
            log.info(f"   ❌ {err}")
            continue

        if SAVE_RAW_HTML and task["kind"] == "section":
            save_snapshot(result["html"])

        if task["kind"] == "section":
            topics = extract_topic_links(result["html"], BASE_URL)
            pages = extract_pagination_links(result["html"], BASE_URL)
            for link in topics:
                taskqueue.enqueue(conn, link, task["section"], "topic")
            for link in pages:
                taskqueue.enqueue(conn, link, task["section"], "section")
            taskqueue.mark(conn, task["id"], "success")
            log.info(f"   📌 {len(topics)} موضوعاً + {len(pages)} صفحات تالية في الطابور")
        else:
            _handle_topic(conn, task, result["html"], dry_run, stats)

        time.sleep(1.6)

    by_status = taskqueue.counts_by_status(conn)
    report = (f"دورة #{run_id} — {datetime.now():%Y-%m-%d %H:%M}\n"
              f"الوضع: {'تجريبي' if dry_run else 'فعلي'} | صفحات: {stats['pages']}\n"
              f"وثائق: {stats['docs']} | مواد: {stats['articles']} | "
              f"تخطي تكرار: {stats['skipped']} | إخفاقات: {stats['failures']}\n"
              f"الطابور: {by_status}\n")
    conn.execute("UPDATE crawl_runs SET finished_at=?, pages=?, docs=?, "
                 "articles=?, skipped=?, failures=?, report=? WHERE id=?",
                 (datetime.now().isoformat(), stats["pages"], stats["docs"],
                  stats["articles"], stats["skipped"], stats["failures"],
                  report, run_id))
    conn.commit()
    out = Path(__file__).parent / "output"
    out.mkdir(exist_ok=True)
    (out / f"run_{run_id}.md").write_text(report, encoding="utf-8")

    log.info("=" * 100)
    log.info("🏁 انتهت الدورة")
    log.info(report)
    if not dry_run:
        docs = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        arts = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
        log.info(f"📊 القاعدة: {docs} وثيقة | {arts} مادة")
    conn.close()


if __name__ == "__main__":
    start_crawling(max_pages=50)
