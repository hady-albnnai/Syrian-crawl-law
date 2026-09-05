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
    python -m cli gaps                      # فجوات فروع القانون + استعلامات مقترحة
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


def cmd_index(_args):
    import chunker
    from database import get_connection
    conn = get_connection()
    rep = chunker.build_chunks(conn)
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    print(f"الفهرسة: {rep['chunks']} قطعة من {rep['docs']} وثيقة")
    return 0


def cmd_search(args):
    from database import get_connection
    import search as srch
    conn = get_connection()
    hits = srch.search(conn, args.query, limit=args.limit)
    if not hits:
        print("لا مصدر كافٍ — لا يُستنتج جواب.")
        return 0
    for h in hits:
        print(f"• [{h['doc_title'][:40]}] {h['label']} — "
              f"{h['text'][:80]}…  ← {h['source_url'][:60]}")
    conn.close()
    return 0


def cmd_ask(args):
    from database import get_connection
    import answer as ans
    conn = get_connection()
    rep = ans.answer_question(conn, args.question)
    conn.close()
    if rep["status"] == "refused":
        print(f"⛔ {rep['reason']}")
        return 0
    print(f"✔ الجواب (نص المادة حرفياً):\n{rep['answer']}\n")
    print("الاستشهادات:")
    for c in rep["citations"]:
        print(f"  • {c['doc_title'][:45]} — {c['label']} ← {c['source_url'][:60]}")
    return 0


def cmd_eval_qa(args):
    import json
    from pathlib import Path
    from datetime import datetime
    from database import get_connection
    import answer as ans
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    conn = get_connection()
    rep = ans.run_qa_eval(conn, questions, k=args.k)
    conn.close()
    out = Path("output"); out.mkdir(exist_ok=True)
    lines = [f"# تقرير تقييم السؤال-جواب — {datetime.now():%Y-%m-%d %H:%M}",
             f"دقة الإسناد = {rep['qa_accuracy']:.2f} | "
             f"دقة الرفض الآمن = {rep['refusal_precision']:.2f} | "
             f"مُجاب: {rep['answered']} / مرفوض: {rep['refused']}", ""]
    for q, note, ok in rep["details"]:
        lines.append(f"- [{'✓' if ok else '✗'}] {q} — {note}")
    Path(out / "qa_eval.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    print("\n".join(lines))
    print("  التقرير: output/qa_eval.md")
    return 0


def cmd_eval_search(args):
    import json
    from pathlib import Path
    from datetime import datetime
    from database import get_connection
    import search as srch
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    conn = get_connection()
    rep = srch.run_eval(conn, questions, k=args.k)
    conn.close()
    out = Path("output"); out.mkdir(exist_ok=True)
    lines = [f"# تقرير تقييم الاسترجاع — {datetime.now():%Y-%m-%d %H:%M}",
             f"Recall@{rep['k']} = {rep['recall_at_k']:.2f} | "
             f"MRR = {rep['mrr']:.2f} | أسئلة مُجاباة: {rep['answered']}"
             f" من {rep['total']}", ""]
    for q, note, ok in rep["details"]:
        lines.append(f"- [{'✓' if ok else '✗'}] {q} — {note}")
    Path(out / "search_eval.md").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    print("\n".join(lines[:2]))
    for q, note, ok in rep["details"]:
        print(f"  [{'✓' if ok else '✗'}] {q} — {note}")
    print(f"  التقرير: output/search_eval.md")
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
            if args.auto and ev.verdict == "recommended":
                from autopilot import consider_auto_approve
                consider_auto_approve(conn, cand.url, ev)
    conn.commit()
    conn.close()
    return 0


def cmd_prune(_args):
    """صيانة المتن: حذف وثائق بلا مواد وتكرارات البصمة."""
    from database import create_tables, get_connection, prune_corpus
    create_tables()
    conn = get_connection()
    stats = prune_corpus(conn)
    log.info(f"🧹 حُذفت {stats['zero_article']} وثيقة بلا مواد + "
             f"{stats['duplicates']} تكرار بصمة + {stats['foreign']} تشريع "
             f"غير سوري")
    conn.close()
    return 0


def cmd_autopilot(args):
    """الطيار الآلي: توليد ← تقييم ← اعتماد تلقائي ← زحف المعتمد."""
    from autopilot import run_autopilot
    stats = run_autopilot(pages=args.pages, use_search=not args.no_search,
                          auto_approve=not args.no_auto,
                          crawl=not args.no_crawl,
                          max_evaluate=args.max_evaluate)
    log.info("═══ تقرير الطيار الآلي ═══")
    log.info(f"مرشحون: {stats['seen']} | قُيّموا: {stats['evaluated']} | "
             f"جدد: {stats['new']}")
    log.info(f"اعتُمد تلقائياً: {stats['approved']} | مقترح/مرفوض: "
             f"{stats['rejected']} | محجوب robots: {stats['blocked']}")
    for src in stats["approved_list"]:
        log.info(f"  🤖 {src['title'][:50]} — {src['engine']} | "
                 f"{src['score']:.1f} | {src['articles']} مادة | {src['via']}")
    if stats["errors"]:
        log.info(f"أعطال تقييم متجاوزة: {len(stats['errors'])}")
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


def cmd_gaps(_args):
    """تحليل فجوات فروع القانون (DESIGN-SELF-DISCOVERY.md §7): توزيع
    الوثائق الفعلي بكل فرع مقارنة بحد أدنى محسوب آلياً من القاعدة نفسها،
    مع استعلامات بحث موجَّهة لكل فرع ناقص التغطية."""
    from database import create_tables, get_connection
    from gap_analysis import analyze_gaps, gap_queries_for_branch
    create_tables()
    conn = get_connection()
    report = analyze_gaps(conn)
    conn.close()

    log.info("=" * 70)
    log.info("تحليل فجوات فروع القانون")
    log.info("=" * 70)
    for branch, info in sorted(report.items(), key=lambda kv: kv[1]["count"]):
        flag = "⚠️ فجوة" if info["gap"] else "✅"
        log.info(f"{flag}  {branch:24s} فعلي={info['count']:<4d} "
                 f"الحد الأدنى المتوقَّع={info['expected_min']}")
    gapped = [b for b, info in report.items() if info["gap"]]
    if gapped:
        log.info("-" * 70)
        log.info("استعلامات بحث مقترحة للفروع الناقصة:")
        for branch in gapped:
            for q in gap_queries_for_branch(branch):
                log.info(f"  [{branch}] {q}")
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
    sp.add_argument("--auto", action="store_true",
                    help="اعتماد تلقائي لمن يجتاز بوابة الطيار الآلي الأعلى")
    sp.set_defaults(fn=cmd_discover)

    sp = sub.add_parser("autopilot",
                        help="طيار آلي: يلاقي مصادر لحالو — يولّد/يقيّم/"
                             "يعتمد تلقائياً ثم يزحف المعتمد")
    sp.add_argument("--pages", type=int, default=20,
                    help="حد صفحات الزحف بعد الاكتشاف")
    sp.add_argument("--max-evaluate", type=int, default=12,
                    help="حد المرشحين المقيَّمين في الدورة")
    sp.add_argument("--no-search", action="store_true",
                    help="تعطيل قنوات البحث (DDG/Bing)")
    sp.add_argument("--no-auto", action="store_true",
                    help="تسجيل proposed فقط بلا اعتماد تلقائي")
    sp.add_argument("--no-crawl", action="store_true",
                    help="اكتشاف فقط — بلا زحف")
    sp.set_defaults(fn=cmd_autopilot)

    sp = sub.add_parser("runs", help="سجل دورات الزحف وتقاريرها")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--report", type=int, metavar="RUN_ID",
                    help="طباعة تقرير دورة معينة")
    sp.set_defaults(fn=cmd_runs)

    sp = sub.add_parser("migrate", help="تطبيق هجرات المخطط (مع نسخة احتياطية)")
    sp.set_defaults(fn=cmd_migrate)

    sp = sub.add_parser("index", help="بناء chunks + فهرس FTS5")
    sp.set_defaults(fn=cmd_index)

    sp = sub.add_parser("prune",
                        help="صيانة المتن: حذف وثائق بلا مواد وتكرارات البصمة")
    sp.set_defaults(fn=cmd_prune)

    sp = sub.add_parser("search", help="بحث نصي عربي مع الإسناد")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("eval-search", help="تقييم الاسترجاع (Recall@k/MRR)")
    sp.add_argument("--questions", default="eval/questions.json")
    sp.add_argument("--k", type=int, default=5)
    sp.set_defaults(fn=cmd_eval_search)

    sp = sub.add_parser("ask", help="جواب موثَّق: نص المادة + استشهادات أو رفض آمن")
    sp.add_argument("question")
    sp.set_defaults(fn=cmd_ask)

    sp = sub.add_parser("eval-qa", help="تقييم عربي للسؤال-جواب والرفض")
    sp.add_argument("--questions", default="eval/questions.json")
    sp.add_argument("--k", type=int, default=3)
    sp.set_defaults(fn=cmd_eval_qa)

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

    sp = sub.add_parser("gaps", help="تحليل فجوات فروع القانون + استعلامات مقترحة")
    sp.set_defaults(fn=cmd_gaps)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)  # أغلق المستهلك الأنبوب (head مثلاً) — ليس خطأ منتجياً
