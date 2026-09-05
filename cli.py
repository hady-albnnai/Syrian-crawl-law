# -*- coding: utf-8 -*-
"""cli.py — طريقة التشغيل الموحدة (التسليم 1).

أمثلة:
    python -m cli init                      # إنشاء الجداول والمجلدات
    python -m cli stats                     # أعداد الوثائق/المواد/المصادر
    python -m cli crawl --pages 5 --mode dry     # زحف تجريبي بلا حفظ
    python -m cli crawl --pages 20 --mode limited
    python -m cli crawl --pages 500 --mode full --yes
    python -m cli discover "القانون المدني السوري" --via ddg
    python -m cli seeds                     # قائمة دليل البذور
    python -m cli sources list|approve ID|reject ID
"""
import argparse
import sys

from logging_setup import get_log

log = get_log("cli")


def cmd_init(_args):
    from database import create_tables, get_db_info
    create_tables()
    get_db_info()
    return 0


def cmd_migrate(_args):
    from migrations import migrate
    rep = migrate()
    print(f"إصدار المخطط: {rep['start_version']} ← {rep['end_version']}")
    for b in rep["backups"]:
        print(f"  نسخة احتياطية: {b}")
    for m in rep["applied"]:
        print(f"  هجرة {m['version']}: {m['name']} — "
              f"backfilled={m.get('backfilled')} empty={m.get('empty')}")
    if not rep["applied"]:
        print("  لا هجرات معلّقة — المخطط محدث.")
    return 0


def cmd_export(args):
    from exporter import build_package
    rep = build_package(out_dir=args.out, prefix=args.prefix,
                        min_articles=args.min_articles)
    print(f"حزمة المحتوى: {rep['docs']} وثيقة → {rep['out_dir']}")
    print(f"  الفهرس: {rep['csv']}")
    if rep["skipped"]:
        print(f"  تخطي (مواد < {args.min_articles}): {rep['skipped']}")
    return 0


def cmd_stats(_args):
    from database import get_connection
    conn = get_connection()
    cur = conn.cursor()
    for table in ("documents", "articles", "sources", "crawl_log"):
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        log.info(f"{table:10s}: {cur.fetchone()['c']}")
    cur.execute("SELECT status, COUNT(*) AS c FROM sources GROUP BY status")
    for row in cur.fetchall():
        log.info(f"sources[{row['status']}] = {row['c']}")
    conn.close()
    return 0


def cmd_crawl(args):
    from database import create_tables
    from crawler import start_crawling
    create_tables()
    if args.mode == "full" and not args.yes:
        log.error("الوضع full يتطلب --yes صراحة (الخيار الآمن افتراضياً)")
        return 2
    start_crawling(max_pages=args.pages, dry_run=(args.mode == "dry"))
    return 0


def cmd_discover(args):
    from database import create_tables, get_connection
    from discovery import (BingApiProvider, DuckDuckGoHtmlProvider,
                           SearchUnavailable, evaluate_candidate,
                           register_candidate)
    create_tables()
    try:
        provider = (BingApiProvider() if args.via == "bing"
                    else DuckDuckGoHtmlProvider())
        candidates = provider.search(args.query, limit=args.limit)
    except SearchUnavailable as exc:
        log.error(str(exc))
        return 2
    conn = get_connection()
    for cand in candidates:
        log.info(f"• {cand.title}  ←  {cand.url}")
        if args.evaluate:
            ev = evaluate_candidate(cand.url)
            register_candidate(conn, cand.url, cand.via, ev)
            log.info(f"   الحكم: {ev.verdict} | الدرجة {ev.score:.1f} | "
                     f"المحرك {ev.engine} | {'؛ '.join(ev.reasons)}")
    conn.commit()
    conn.close()
    return 0


def cmd_runs(args):
    from database import get_connection
    conn = get_connection()
    rows = conn.execute("SELECT id, started_at, mode, pages, docs, articles, "
                        "skipped, failures FROM crawl_runs ORDER BY id DESC "
                        "LIMIT ?", (args.limit,)).fetchall()
    if not rows:
        log.info("لا دورات مسجلة بعد")
        return 0
    for r in rows:
        log.info(f"#{r['id']:>3} {r['started_at'][:16]} [{r['mode']:4s}] "
                 f"صفحات {r['pages']:>3} | وثائق {r['docs']:>2} | مواد "
                 f"{r['articles']:>4} | تخطي {r['skipped']:>2} | إخفاق {r['failures']:>2}")
    if args.report:
        rep = conn.execute("SELECT report FROM crawl_runs WHERE id = ?",
                           (args.report,)).fetchone()
        if rep:
            log.info("\n" + rep["report"])
    conn.close()
    return 0


def cmd_seeds(_args):
    from discovery import seed_candidates
    for cand in seed_candidates():
        log.info(f"• {cand.title}  ←  {cand.url}  (عبر: {cand.via})")
    return 0


def cmd_sources(args):
    from database import create_tables, get_connection
    from discovery import decide_source
    create_tables()
    conn = get_connection()
    cur = conn.cursor()
    if args.action == "list":
        cur.execute("SELECT id, source_key, base_url, name, engine, status "
                    "FROM sources ORDER BY id")
        rows = cur.fetchall()
        if not rows:
            log.info("لا مصادر مسجلة بعد — استخدم discover أو seeds")
        for r in rows:
            log.info(f"[{r['id']}] {r['status']:9s} {r['engine']:10s} "
                     f"{r['name'][:40]:42s} {r['base_url']}")
    elif args.action in ("approve", "reject"):
        decide_source(conn, _key_of(conn, args.id), args.action == "approve")
        log.info(f"{'اعتُمد' if args.action == 'approve' else 'رُفض'} المصدر {args.id}")
    conn.close()
    return 0


def _key_of(conn, ref: str) -> str:
    """يقبل معرف الصف أو بادئة مصدر — ويرجع source_key كاملاً."""
    cur = conn.cursor()
    if ref.isdigit():
        cur.execute("SELECT source_key FROM sources WHERE id = ?", (int(ref),))
    else:
        cur.execute("SELECT source_key FROM sources WHERE source_key LIKE ?",
                    (ref + "%",))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"مصدر غير موجود: {ref}")
    return row["source_key"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mizan-harvest",
                                description="حاصدة ميزان — أداة جمع التشريعات السورية")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="إنشاء الجداول والمجلدات")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("stats", help="أعداد قاعدة البيانات")
    sp.set_defaults(fn=cmd_stats)

    sp = sub.add_parser("crawl", help="تشغيل الزحف")
    sp.add_argument("--pages", type=int, default=10)
    sp.add_argument("--mode", choices=("dry", "limited", "full"), default="dry")
    sp.add_argument("--yes", action="store_true",
                    help="تأكيد صريح للوضع full")
    sp.set_defaults(fn=cmd_crawl)

    sp = sub.add_parser("discover", help="البحث عن مصادر جديدة")
    sp.add_argument("query")
    sp.add_argument("--via", choices=("ddg", "bing"), default="ddg")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--evaluate", action="store_true",
                    help="تقييم كل مرشح وتسجيله proposed")
    sp.set_defaults(fn=cmd_discover)

    sp = sub.add_parser("runs", help="سجل دورات الزحف وتقاريرها")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--report", type=int, metavar="RUN_ID",
                    help="طباعة تقرير دورة معينة")
    sp.set_defaults(fn=cmd_runs)

    sp = sub.add_parser("migrate", help="تطبيق هجرات المخطط (مع نسخة احتياطية)")
    sp.set_defaults(fn=cmd_migrate)

    sp = sub.add_parser("export", help="توليد حزمة محتوى لميزان (CSV+md+JSON)")
    sp.add_argument("--out", default="export/content_package")
    sp.add_argument("--prefix", default="content/legal_library/laws_decrees/")
    sp.add_argument("--min-articles", type=int, default=0)
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("seeds", help="عرض دليل البذور المرفق")
    sp.set_defaults(fn=cmd_seeds)

    sp = sub.add_parser("sources", help="إدارة سجل المصادر")
    sp.add_argument("action", choices=("list", "approve", "reject"))
    sp.add_argument("id", nargs="?")
    sp.set_defaults(fn=cmd_sources)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)  # أغلق المستهلك الأنبوب (head مثلاً) — ليس خطأ منتجياً
