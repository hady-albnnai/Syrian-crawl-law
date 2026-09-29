"""الحصاد بضغطة واحدة: اكتشاف ← اختبار ← اعتماد ← إدراج ← زحف (والجديد لاحقاً).

الفكرة (قرار المالك 2026-09-29): الزاحف يجد مصادره بنفسه ولا يقتصر على قائمة
محدودة، وكل ما يظهر جديداً في المصادر المعتمدة يُحمَّل في الدورات التالية.

الضوابط المتفق عليها (كلها قبل أي اعتماد):
  1) بنية قانونية + درجة ≥ 70 + ≥ 3 مواد (auto_verdict).
  2) اختصاص المصدر «سوري» صراحة (jurisdiction.py) — الأجنبي يُرفض، والمختلط لا يُعتمد.
  3) عينة probation: ≈12 صفحة قانونية، بلا تسرب أجنبي، ≥ 70% متوافقة مع سورية.
  4) الاعتماد يُسجَّل decided_by='auto-probation' ويُعكس بـ sources reject.
  بوابة التصدير إلى ميزان (المراجعة) تبقى كما هي — الزحف لا يعني نشراً.

--dry: تقييم واختبار بلا أي كتابة ولا إدراج ولا زحف.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from logging_setup import get_log

log = get_log("harvest")

DEFAULT_REFRESH_DAYS = 7


def refresh_sections(conn, days: int = DEFAULT_REFRESH_DAYS) -> int:
    """يعيد صفحات الأقسام المكتملة للمصادر المعتمدة إلى الطابور بعد `days` يوماً.

    هذا ما يجعل «الجديد لاحقاً» يُلتقط: الزاحف يعيد فحص الفهرس فيجد المواضيع
    الجديدة فقط (التكرار مُصفّى بالطابور وهوية الوثيقة).
    """
    from urls import canonicalize_url
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    n = 0
    for src in conn.execute("SELECT base_url FROM sources WHERE status='approved' "
                            "AND base_url IS NOT NULL").fetchall():
        key = canonicalize_url(src["base_url"], keep_params=("start",))
        cur = conn.execute(
            "UPDATE crawl_tasks SET status='queued', attempts=0, updated_at=? "
            "WHERE url=? AND kind='section' AND status='success' "
            "AND COALESCE(updated_at,'') < ?",
            (datetime.now().isoformat(), key, cutoff))
        n += cur.rowcount
    conn.commit()
    return n


def run_harvest(pages: int = 100, use_search: bool = False,
                search_via: str | None = None, max_evaluate: int = 12,
                refresh_days: int = DEFAULT_REFRESH_DAYS, crawl: bool = True,
                dry_run: bool = False, stop_event=None) -> dict:
    from autopilot import run_discovery
    from crawl_queue import enqueue_approved_sources
    from database import create_tables, get_connection
    from probation import run_probation

    create_tables()
    conn = get_connection()
    report = {"discovery": {}, "probation": {}, "enqueued": 0, "refreshed": 0,
              "crawl_pages": 0, "dry_run": dry_run}
    try:
        log.info("① اكتشاف المصادر (تتبع بين المصادر + المتن + خرائط المواقع"
                 + (" + بحث" if use_search else "") + ")")
        report["discovery"] = run_discovery(
            conn, use_search=use_search, search_via=search_via,
            max_evaluate=max_evaluate, dry_run=dry_run)
        if stop_event is not None and stop_event.is_set():
            return report
        log.info("② اختبار المصادر الموصى بها (عينة بلا حفظ)")
        report["probation"] = run_probation(conn, dry_run=dry_run,
                                            stop_event=stop_event)
        if dry_run:
            log.info("تجريبي: لا إدراج ولا زحف")
            return report
        if not crawl:
            log.info("--no-crawl: اكتشاف واعتماد فقط؛ لا إدراج ولا زحف (يُدرج في الدورة التالية)")
            return report
        log.info("③ إدراج المصادر المعتمدة + تجديد الفهارس القديمة")
        items = enqueue_approved_sources(conn)
        report["enqueued"] = sum(1 for i in items if i["enqueued"])
        report["refreshed"] = refresh_sections(conn, refresh_days)
        log.info(f"أُدرج {report['enqueued']} مصدر جديد، وأُعيد {report['refreshed']} فهرس للتجديد")
    finally:
        conn.close()
    if crawl and pages > 0 and not (stop_event is not None and stop_event.is_set()):
        log.info(f"④ الزحف (حتى {pages} صفحة)")
        from crawler import start_crawling
        start_crawling(max_pages=pages, dry_run=False, stop_event=stop_event)
        report["crawl_pages"] = pages
    return report
