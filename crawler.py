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
import dedup
import engines
import law_identity
import source_quality
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
    # md5 تاريخي لمحتوى clean_content — حُسم في التسليم 4 (ADR-001):
    # sha256 هي البصمة المعتمدة (content_sha256)، وهذا يبقى للمطابقة القديمة فقط.
    return hashlib.md5(text.strip().encode('utf-8')).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode('utf-8')).hexdigest()


def save_document(cursor, doc_id, title, url, branch, confidence, score,
                  content_hash, clean_text, snapshot_sha256=None,
                  identity_key=None, identity_confidence=None,
                  law_number=None, law_year=None, doc_type_name=None,
                  is_complete_text=None, source_domain_tier=None,
                  quality_score=None, status=None):
    """حفظ idempotent: فحص doc_id قبل الإدراج (P0). يعيد (row_id, created).

    المعاملات الجديدة (اكتشاف ذاتي للمصادر، DESIGN-SELF-DISCOVERY.md §2/§4)
    اختيارية بقيمة افتراضية None — الاستدعاءات القديمة (بلا هذه الحقول)
    تبقى صالحة بلا تعديل، وتُترك number/year/identity_key فارغة كما كانت.
    status=None يترك القيمة الافتراضية بمخطط الجدول ('active') — يُمرَّر
    صراحة 'alternate_source' فقط عند خسارة المقارنة أمام نسخة أفضل (§4.2).
    """
    cursor.execute("SELECT id FROM documents WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    if row is not None:
        return row["id"], False
    cursor.execute('''
        INSERT INTO documents
        (doc_id, title, source_url, branch, branch_confidence, legal_score,
         content_hash, scraped_at, clean_content, doc_type,
         content_sha256, snapshot_sha256, identity_key, identity_confidence,
         number, year, is_complete_text, source_domain_tier, quality_score,
         status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (doc_id, title, url, branch, confidence, score, content_hash,
          datetime.now().isoformat(), clean_text, doc_type_name or "law",
          sha256_text(clean_text), snapshot_sha256, identity_key,
          identity_confidence, law_number, law_year, is_complete_text,
          source_domain_tier, quality_score, status or "active"))
    return cursor.lastrowid, True


def extract_topic_links(html: str, base_url: str) -> list:
    """مسار phpBB (للتوافق) — المسار الحي في الدورة يكتشف المحرك لكل صفحة."""
    return [clean_url(u) for u in
            engines.extract_topic_links(html, base_url, "phpbb")]


def extract_pagination_links(html: str, base_url: str, limit: int = 3) -> list:
    """ترقيم phpBB (للتوافق) — انظر engines.extract_pagination_links."""
    return engines.extract_pagination_links(html, base_url, "phpbb", limit)


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
    snapshot_sha256 = save_snapshot(html) if SAVE_RAW_HTML else None
    if not is_legal_content(clean, title):
        taskqueue.mark(conn, task["id"], "needs_review", "غير قانوني ظاهرياً")
        log.info("   ⚠️ لم يجتز الفحص القانوني — needs_review")
        return
    # بوابة الجودة الدنيا (2026-09-05 — عطل كشفه الزحف الحي على مصدر مكتشف):
    # صفحات مدونات بلا مواد مستخرجة أو بدرجة هزيلة لا تدخل المتن — needs_review
    # بلا إسقاط صامت.
    real_articles = [a for a in articles if not a.get("is_preamble")]
    if len(real_articles) < 1 or legal_score(clean, title) < 55.0:
        taskqueue.mark(conn, task["id"], "needs_review",
                       f"بلا مواد كافية ({len(real_articles)}) أو درجة هزيلة")
        log.info(f"   ⚠️ {len(real_articles)} مادة — دون بوابة الجودة "
                 f"— needs_review")
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

    # هوية القانون + فئة رسمية المصدر + اكتمال النص — الاكتشاف الذاتي
    # للمصادر (DESIGN-SELF-DISCOVERY.md §2 و§4.2). حساب لا افتراض: كل
    # وثيقة تُفحص فعلياً حتى لو لم يُعثر على رقم/سنة (identity_key=None).
    identity = law_identity.extract_law_identity(title, clean)
    domain_tier = source_quality.domain_tier_for_url(task["url"])
    complete = source_quality.is_complete_text(clean, articles)
    q_score = ext.get("quality_score")
    has_hierarchy = any(a.get("hierarchy_path") for a in real_articles)

    existing_row = dedup.find_existing_by_identity(
        cursor, identity["identity_key"])

    doc_status = None  # None → الافتراضي 'active' في save_document
    if existing_row is not None:
        new_candidate = dedup.build_new_candidate(
            domain_tier, complete, q_score, len(real_articles),
            has_hierarchy, len(clean))
        existing_candidate = dedup.build_existing_candidate(cursor, existing_row)
        decision = dedup.compare_candidates(new_candidate, existing_candidate)

        if decision["winner"] == "new":
            # الجديدة أفضل: القديمة تُؤرشف (نسخ لا حذف) وتُعلَّم superseded،
            # الجديدة تصبح active.
            dedup.archive_document_version(
                cursor, original_doc_id=existing_row["id"],
                doc_row=dict(existing_row),
                reason=f"استُبدلت — {decision['decisive_criterion']}")
            cursor.execute(
                "UPDATE documents SET status='superseded' WHERE id=?",
                (existing_row["id"],))
        else:
            # القديمة أفضل أو تعادل: الجديدة تُحفظ كمصدر بديل موثَّق —
            # لا تُسقَط بصمت (القرار الآمن دستورياً في §4.2).
            doc_status = "alternate_source"

        log.info(f"   🔍 تطابق هوية {identity['identity_key']} — "
                 f"الفائز: {decision['winner']} "
                 f"({decision['decisive_criterion']})")

    doc_row_id, created = save_document(
        cursor, make_doc_id(task["url"]), title, task["url"], branch,
        float(confidence), legal_score(clean, title), content_hash,
        clean[:15000], snapshot_sha256=snapshot_sha256,
        identity_key=identity["identity_key"],
        identity_confidence=identity["identity_confidence"],
        law_number=identity["law_number"], law_year=identity["law_year"],
        is_complete_text=complete, source_domain_tier=domain_tier,
        quality_score=q_score, status=doc_status)
    if not created:
        conn.commit()
        taskqueue.mark(conn, task["id"], "success")
        stats["skipped"] += 1
        log.info("   🔁 الوثيقة محفوظة سابقاً — تخطي بلا تكرار")
        return

    if existing_row is not None:
        winner_id = doc_row_id if decision["winner"] == "new" else existing_row["id"]
        loser_id = existing_row["id"] if decision["winner"] == "new" else doc_row_id
        if decision["decisive_criterion"] is not None:
            dedup.record_dedup_decision(
                cursor, identity["identity_key"], winner_id, loser_id,
                decision["decisive_criterion"], decision["new_value"],
                decision["existing_value"])

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


def start_crawling(max_pages=40, dry_run=False, stop_event=None):
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
    # لالتقاط الوثائق المكتسبة بهذه الدورة تحديداً للفرز الختامي بالفرع
    # (§7.2) — أي id أكبر من هذا يُعتبر «جديداً بهذه الدورة».
    last_doc_id_before_run = (
        conn.execute("SELECT MAX(id) FROM documents").fetchone()[0] or 0)

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

    # المصادر المعتمدة (يدوياً أو بالطيار الآلي) تُبذر كل دورة — idempotent:
    # الرابط المكرر لا يُدرج، والمكتمل سابقاً يبقى مكتملاً. الترتيب هنا
    # يتبع أداء كل مصدر تاريخياً (learning.prioritized_active_sources,
    # §5 من خطة الاكتشاف الذاتي): الأكثر إنتاجاً لقوانين فريدة يُبذر أولاً
    # فيُزار أولاً (الطابور FIFO)؛ المصادر «المستنفدة» (3 دورات فارغة
    # متتالية) تُستبعد تلقائياً من إعادة الزحف — توفير موارد شبكة.
    try:
        import learning
        for src in learning.prioritized_active_sources(conn):
            name = src["name"] or src["base_url"]
            if taskqueue.enqueue(conn, src["base_url"], name, "section"):
                log.info(f"🌐 مصدر معتمد أُضيف للطابور: {name} "
                         f"({src['base_url']})")
    except Exception as exc:  # جدول sources غير موجود (قاعدة قديمة) — نتجاوزه
        log.info(f"تخطي بذر المصادر المعتمدة: {exc}")

    stats = {"pages": 0, "docs": 0, "articles": 0, "skipped": 0, "failures": 0}
    while stats["pages"] < max_pages:
        if stop_event is not None and stop_event.is_set():
            log.info("⏹ إيقاف تعاوني طُلب — تُغلق الدورة بأمان (الطابور دائم)")
            break
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
            # التعامل مع المصدر المكتشف: المحرك يُكشف لكل صفحة، ومستخرج
            # الروابط يُختار حسب المحرك — لا أنماط منتدى محجوزة.
            engine = engines.detect_engine(result["html"])
            base = task["url"]
            topics = engines.extract_topic_links(result["html"], base, engine)
            pages = engines.extract_pagination_links(result["html"], base,
                                                     engine)
            for link in topics:
                taskqueue.enqueue(conn, link, task["section"], "topic")
            for link in pages:
                taskqueue.enqueue(conn, link, task["section"], "section")
            log.info(f"   📌 [{engine}] {len(topics)} وثيقة مرشحة + "
                     f"{len(pages)} صفحات تالية في الطابور")
            # المصدر أحادي الصفحة (ويكي مصدر مثلاً) قد يكون وثيقة كاملة
            # بنفسه — تُحفظ مباشرة ولا تضيع باعتباره «قائمة» فقط.
            ext = extract_main_content(result["html"], task["url"])
            n_arts = (len([a for a in ext.get("articles", [])
                           if not a.get("is_preamble")])
                      if ext["success"] else 0)
            if n_arts >= 3 and is_legal_content(ext["clean_text"],
                                                ext["title"]):
                log.info(f"   📜 الصفحة نفسها وثيقة كاملة ({n_arts} مادة) — "
                         f"تُحفظ مباشرة")
                _handle_topic(conn, task, result["html"], dry_run, stats)
            else:
                taskqueue.mark(conn, task["id"], "success")
        else:
            _handle_topic(conn, task, result["html"], dry_run, stats)

        time.sleep(1.6)

    by_status = taskqueue.counts_by_status(conn)
    report = (f"دورة #{run_id} — {datetime.now():%Y-%m-%d %H:%M}\n"
              f"الوضع: {'تجريبي' if dry_run else 'فعلي'} | صفحات: {stats['pages']}\n"
              f"وثائق: {stats['docs']} | مواد: {stats['articles']} | "
              f"تخطي تكرار: {stats['skipped']} | إخفاقات: {stats['failures']}\n"
              f"الطابور: {by_status}\n")
    # فرز/تصنيف الوثائق المكتسبة بهذه الدورة تحديداً حسب فرع القانون (§7.2)
    try:
        import gap_analysis
        breakdown = gap_analysis.branch_breakdown_for_run(
            conn, last_doc_id_before_run)
    except Exception as exc:  # جدول documents بمخطط قديم — نتجاوز الفرز
        breakdown = {}
        log.info(f"تخطي الفرز بالفرع لهذه الدورة: {exc}")
    if breakdown:
        log.info(f"   📚 فرز هذه الدورة بالفرع: {breakdown}")

    conn.execute("UPDATE crawl_runs SET finished_at=?, pages=?, docs=?, "
                 "articles=?, skipped=?, failures=?, report=?, "
                 "branch_breakdown_json=? WHERE id=?",
                 (datetime.now().isoformat(), stats["pages"], stats["docs"],
                  stats["articles"], stats["skipped"], stats["failures"],
                  report, json.dumps(breakdown, ensure_ascii=False), run_id))
    conn.commit()

    # تعلّم من هذه الدورة (§5): يُحدَّث عدد القوانين الفريدة الجديدة بكل
    # مصدر معتمد — يوجّه ترتيب البذر بالدورة القادمة (أعلى بهذا الملف).
    try:
        import learning
        learning.update_source_performance(conn)
    except Exception as exc:  # جدول source_performance غير موجود (قاعدة قديمة)
        log.info(f"تخطي تحديث أداء المصادر: {exc}")

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
