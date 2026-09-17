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
    python -m cli hf-import                 # ف٢: تبنٍّ مجموعة HF المجتمعية
    python -m cli seed-community            # ف٢-ج: بذر قوانين syria-law
    python -m cli tasks --contains wipo     # فحص حالة مهام الطابور
    python -m cli requeue --contains wipo   # إعادة مهمة فاشلة إلى الطابور
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
    from config import DB_PATH
    from exporter import build_package
    rep = build_package(db_path=args.db or DB_PATH, out_dir=args.out,
                        prefix=args.prefix,
                        min_articles=args.min_articles,
                        with_manifest=not args.no_manifest)
    print(f"حزمة المحتوى: {rep['docs']} وثيقة → {rep['out_dir']}")
    print(f"  الفهرس: {rep['csv']}")
    if rep["skipped"]:
        print(f"  تخطي (مواد < {args.min_articles}): {rep['skipped']}")
    if rep.get("manifest"):
        m = rep["manifest"]
        print(f"  المانيفست: schema v{m['schema_version']} — {m['files']} حزمة ملفات "
              f"| {m['articles']} مادة")
    if rep.get("enrich_error"):
        print(f"  ⚠︎ توسيع عقد المواد لم يعمل: {rep['enrich_error']}")
    if "gate_ok" in rep:
        print(f"  بوابة ميزان: {'✓ ستُستورد كل الصفوف' if rep['gate_ok'] else '✗ ستُتخطى صفوف'}")
        for msg in rep.get("gate_failed", []):
            print(f"     ✗ {msg}")
        n = rep.get("articles_in_package")
        if n is not None:
            print(f"  مواد داخل الحزمة (معدودة من القرص): {n}")
    return 0 if rep.get("gate_ok", True) else 1


def cmd_verify_package(args):
    """بوابة مستقلة: افحص حزمة جاهزة بنفس منطق ميزان (بلا إعادة توليد)."""
    from pathlib import Path as _P
    import verify_package
    checks = verify_package.check_package(args.pkg)
    for msg, ok in checks:
        print(f"  [{'✓' if ok else '✗'}] {msg}")
    counts = verify_package.article_counts(args.pkg)
    print(f"  صفوف: {counts['rows']} | ملفات JSON: {counts['docs_with_json']} "
          f"| مواد: {counts['articles']}")
    return 0 if all(bool(ok) for _m, ok in checks) else 1


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


def cmd_tasks(args):
    """فحص مهام الطابور: الحالة والمحاولات وآخر عطل — عين التشغيل."""
    from database import create_tables, get_connection
    from crawl_queue import list_tasks
    create_tables()
    conn = get_connection()
    statuses = ([s.strip() for s in args.status.split(",") if s.strip()]
                if args.status else None)
    rows = list_tasks(conn, statuses=statuses, contains=args.contains,
                      limit=args.limit)
    if not rows:
        log.info("لا مهام بهذه الشروط")
    for t in rows:
        err = f" — آخر عطل: {t['last_error']}" if t["last_error"] else ""
        log.info(f"#{t['id']} [{t['status']}] محاولات {t['attempts']}{err}")
        log.info(f"   {t['kind']} | {t['section']} | {t['url'][:75]}")
    if rows:
        log.info(f"{len(rows)} مهمة (الحد {args.limit})")
    conn.close()
    return 0


def cmd_requeue(args):
    """إعادة مهام فاشلة/محجوبة إلى الطابور (تصفير عدّاد المحاولات)."""
    from database import create_tables, get_connection
    from crawl_queue import requeue_by
    create_tables()
    conn = get_connection()
    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    revived = requeue_by(conn, statuses, contains=args.contains)
    if not revived:
        log.info("لا مهام بهذه الحالة"
                 + (f" ورابطها يحوي «{args.contains}»" if args.contains else ""))
    for t in revived[:10]:
        err = f" — آخر عطل: {t['last_error']}" if t["last_error"] else ""
        log.info(f"↻ #{t['id']} {t['status']} → queued{err}")
        log.info(f"   {t['url'][:75]}")
    if len(revived) > 10:
        log.info(f"   … و{len(revived) - 10} مهمة أخرى")
    if revived:
        log.info(f"أعيد للطابور {len(revived)} مهمة — شغّل crawl لمعالجتها")
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


def cmd_wayback_crawl(args):
    """زحف الأصول المؤرشفة (طبقة 1) — يرقّي المتبنّى تلقائياً (قرار ج)."""
    from database import create_tables, get_connection
    from urls import canonicalize_url
    import crawl_queue as taskqueue
    import crawler
    import wayback_source
    from hf_syria_laws import load_laws_with_articles
    create_tables()
    conn = get_connection()
    urls, seen = [], set()
    for law, _arts in load_laws_with_articles():
        u = law.get("source_url")
        if not u or u in seen or u.lower().split("?")[0].endswith(".pdf"):
            continue  # PDF مؤجل — يحتاج مسار PDF كاملاً
        seen.add(u)
        urls.append(u)
    if args.limit:
        urls = urls[:args.limit]
    log.info(f"أهداف Wayback: {len(urls)} رابطاً أصلياً (روابط PDF مؤجلة)")

    stats = {"fetched": 0, "no_snapshot": 0, "failed": 0,
             "saved": 0, "skipped": 0}
    for i, url in enumerate(urls, 1):
        res = wayback_source.as_pipeline_result(url)
        if not res.get("ok"):
            err = res.get("error", "wayback_failed")
            key = "no_snapshot" if err == "wayback_no_snapshot" else "failed"
            stats[key] += 1
            log.info(f"[{i}/{len(urls)}] ✗ {err} ← {url[:65]}")
            continue
        taskqueue.enqueue(conn, url, wayback_source.SECTION, "topic")
        row = conn.execute("SELECT id FROM crawl_tasks WHERE url=?",
                           (canonicalize_url(url),)).fetchone()
        task = {"id": row["id"], "url": url,
                "section": wayback_source.SECTION, "kind": "topic"}
        cstats = {"pages": 1, "docs": 0, "articles": 0,
                  "skipped": 0, "failures": 0}
        crawler._handle_topic(conn, task, res["html"], args.dry, cstats)
        stats["fetched"] += 1
        stats["saved"] += cstats["docs"]
        stats["skipped"] += cstats["skipped"]
    log.info(f"خلاصة Wayback: {stats}")
    conn.close()
    return 0


def cmd_dedup_existing(_args):
    """دمج الوثائق النشطة المتصادمة بالهوية (تصادمات ما قبل الهوية)."""
    from database import create_tables, get_connection
    from dedup import dedupe_active_by_identity
    create_tables()
    conn = get_connection()
    rep = dedupe_active_by_identity(conn)
    if rep["collisions"]:
        log.info(f"تصادمات هوية: {rep['collisions']} — أُرشف الخاسر "
                 f"{rep['archived']} (نسخ لا حذف؛ المواد تبقى بالتاريخ)")
    else:
        log.info("لا تصادمات هوية بين الوثائق النشطة — المتن نظيف")
    conn.close()
    return 0


def cmd_seed_community(args):
    """بذر الطبقة المجتمعية (ف٢-ج): syria-law.com عبر خرائط sitemap."""
    from community_seed import seed_syria_law
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()
    rep = seed_syria_law(conn, dry_run=args.dry)
    log.info(f"خلاصة بذر المجتمع: {rep}")
    conn.close()
    return 0


def cmd_hf_import(args):
    """التبني المرحلي لمجموعة HF ipfs_syria_laws عبر بوابات الأنبوب."""
    from database import create_tables, get_connection
    from hf_syria_laws import download_dataset, import_hf_laws
    create_tables()
    for name, st in download_dataset().items():
        log.info(f"   {name}: {st}")
    conn = get_connection()
    rep = import_hf_laws(conn, dry_run=args.dry)
    log.info(f"استيراد HF: حُفظ {rep['imported']} | بديل {rep['alternate']} | "
             f"مطابق {rep['skipped']} | مراجعة {rep['needs_review']} | "
             f"فشل {rep['failed']} | فارغ (للأرشيف) {rep['empty']}")
    conn.close()
    return 0


def cmd_seed_official(args):
    """ف١/ف١-ب: بذر المصادر الرسمية — moj من sitemap + قوانين ويبو."""
    from database import create_tables, get_connection
    from official_seed import seed_moj, seed_wipo
    create_tables()
    conn = get_connection()
    stats = {"moj": seed_moj(conn, dry_run=args.dry),
             "wipo": seed_wipo(conn, dry_run=args.dry)}
    conn.close()
    log.info(f"خلاصة البذر: {stats}")
    return 0


def cmd_law_status(args):
    """ف١: إعادة تحديد الهوية + سلسلة الإحالات + الحالة القانونية."""
    from database import create_tables, get_connection
    from law_identity import reidentify_documents
    from law_status import compute_legal_statuses, law_chain, rebuild_links
    create_tables()
    conn = get_connection()
    if args.reidentify:
        stats = reidentify_documents(conn)
        log.info(f"إعادة تحديد الهوية: {stats}")
    links = rebuild_links(conn) if args.rebuild else None
    if args.list:
        rows = conn.execute(
            """SELECT a.target_identity, a.action, COUNT(*) AS n,
                      (SELECT COUNT(*) FROM documents d
                       WHERE d.identity_key = a.target_identity) AS present
               FROM law_amendments a
               GROUP BY a.target_identity, a.action
               ORDER BY n DESC""").fetchall()
        if not rows:
            log.info("لا إحالات مسجلة بعد")
        for r in rows:
            verb = "إلغاء" if r["action"] == "repeal" else "تعديل"
            here = "✓ موجود بالمتن" if r["present"] else "… خارج المتن بعد"
            log.info(f"  {verb} ×{r['n']} ← {r['target_identity']} ({here})")
    counts = compute_legal_statuses(conn)
    summary = f"الحالات: {counts}"
    if links is not None:
        summary = f"إحالات مُعاد بناؤها: {links} | " + summary
    log.info(summary)
    if args.law:
        chain = law_chain(conn, args.law)
        if not chain:
            log.info(f"لا إحالات مسجلة تستهدف {args.law}")
        for row in chain:
            verb = "إلغاء" if row["action"] == "repeal" else "تعديل"
            log.info(f"  {verb} ← {row['doc_type']} "
                     f"{row['number']}/{row['year']}: "
                     f"{(row['title'] or '')[:60]}")
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

    sp = sub.add_parser("tasks",
                        help="فحص مهام الطابور (حالة/محاولات/آخر عطل)")
    sp.add_argument("--status",
                    help="تصفية بالحالات مفصولة بفواصل (مثل failed,blocked)")
    sp.add_argument("--contains", metavar="TEXT",
                    help="حصر المهام التي يحوي رابطها هذا النص")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(fn=cmd_tasks)

    sp = sub.add_parser("requeue",
                        help="إعادة مهام فاشلة/محجوبة إلى الطابور")
    sp.add_argument("--status", default="failed",
                    help="الحالات المستهدفة مفصولة بفواصل (الافتراضي failed)")
    sp.add_argument("--contains", metavar="TEXT",
                    help="حصر الإعادة بالمهام التي يحوي رابطها هذا النص")
    sp.set_defaults(fn=cmd_requeue)

    sp = sub.add_parser("migrate", help="تطبيق هجرات المخطط (مع نسخة احتياطية)")
    sp.set_defaults(fn=cmd_migrate)

    sp = sub.add_parser("seed-official",
                        help="بذر المصادر الرسمية: moj (sitemap) + ويبو "
                             "(فهرس عضوية سوريا الحي)")
    sp.add_argument("--dry", action="store_true",
                    help="عرض ما سيُبذر دون إدراجه")
    sp.set_defaults(fn=cmd_seed_official)

    sp = sub.add_parser("hf-import",
                        help="ف٢: تبنٍّ مرحلي لمجموعة HF ipfs_syria_laws "
                             "عبر بوابات الأنبوب (طبقة 3)")
    sp.add_argument("--dry", action="store_true",
                    help="عرض ما سيُستورد دون حفظ")
    sp.set_defaults(fn=cmd_hf_import)

    sp = sub.add_parser("wayback-crawl",
                        help="ف٢: زحف الأصول المؤرشفة عبر Wayback "
                             "(طبقة 1 — يرقّي المتبنّى من HF تلقائياً)")
    sp.add_argument("--limit", type=int, default=None,
                    help="حصر العدد (تجربة أولى مثلاً 5)")
    sp.add_argument("--dry", action="store_true",
                    help="تشغيل تجريبي بلا حفظ")
    sp.set_defaults(fn=cmd_wayback_crawl)

    sp = sub.add_parser("dedup-existing",
                        help="ف٢: دمج الوثائق النشطة المتصادمة بالهوية "
                             "(الخاسر يُؤرشف نسخاً لا حذفاً)")
    sp.set_defaults(fn=cmd_dedup_existing)

    sp = sub.add_parser("seed-community",
                        help="ف٢-ج: بذر قوانين syria-law.com من خرائط "
                             "sitemap (طبقة مجتمعية)")
    sp.add_argument("--dry", action="store_true",
                    help="عرض ما سيُبذر دون إدراجه")
    sp.set_defaults(fn=cmd_seed_community)

    sp = sub.add_parser("law-status",
                        help="ف١: حساب الحالة القانونية (ساري/معدَّل/ملغى)")
    sp.add_argument("--reidentify", action="store_true",
                    help="إعادة استخراج هوية الوثائق المخزَّنة بالكود الحالي أولاً")
    sp.add_argument("--rebuild", action="store_true",
                    help="إعادة بناء جدول الإحالات من كل الوثائق أولاً")
    sp.add_argument("--list", action="store_true",
                    help="عرض كل الإحالات المستخرجة (تعديل/إلغاء) ومستهدفاتها")
    sp.add_argument("--law", metavar="IDENTITY",
                    help="طباعة سلسلة تعديلات صك (مثل القانون:17:2010)")
    sp.set_defaults(fn=cmd_law_status)

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
    sp.add_argument("--db", default=None,
                    help="مسار قاعدة بديلة (افتراضياً data/syrian_law.db)")
    sp.add_argument("--no-manifest", action="store_true",
                    help="اكتفِ بالفهرس+md+JSON دون توسيع عقد المواد والمانيفست")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("verify",
                        help="افحص حزمة جاهزة بنفس منطق ميزان (planCsvImport) بلا إعادة توليد")
    sp.add_argument("pkg", nargs="?", default="export/content_package",
                    help="مجلد الحزمة (يحتوي laws_decrees_index.csv وmarkdown/)")
    sp.set_defaults(fn=cmd_verify_package)

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
