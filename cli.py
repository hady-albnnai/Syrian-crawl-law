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
import shutil
from pathlib import Path
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
    if rep.get("renamed"):
        print(f"  تكرار أسماء: {rep['renamed']} وثيقة نالت لاحقة بدل أن تُدفن "
              "تحت ملف آخر (نفس الهوية من مصدرين)")
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


def cmd_inject(args):
    """حقن الحزمة في جذر ميزان: دمج فهرس، نسخ ملفات، إيصالية — بلا لمس DBهم."""
    import mizan_injector as inj
    from config import MIZAN_ROOT
    args.mizan_root = args.mizan_root or MIZAN_ROOT or inj.default_mizan_root()
    if not args.mizan_root:
        log.error("يلزم --mizan-root <جذر ميزان> (المجلد الذي يحتوي content/)، "
                  "أو اضبط MIZAN_ROOT في config.py/المحيط")
        return 2
    log.info(f"جذر ميزان: {args.mizan_root}")
    try:
        plan = inj.plan(args.pkg, args.mizan_root,
                        replace_index=args.replace_index)
    except FileNotFoundError as exc:
        log.error(str(exc))
        return 2
    print(inj.summarize(plan, for_write=not args.preview))
    if args.preview:
        return 0
    try:
        rec = inj.apply(args.pkg, args.mizan_root,
                        replace_index=args.replace_index,
                        allow_red_gate=args.force, prefetch=plan)
    except inj.GateError as exc:
        log.error(str(exc))
        return 1
    v = rec["verify_our_rows"]
    log.info(f"حُقن: +{rec['rows']['added']} صفاً | {rec['files_written']} ملف "
             f"| فهرس بعد الحقن {rec['rows']['index_rows_after']} صفًّا "
             f"| الإيصالية: {rec['dest']}/{inj.RECEIPT_NAME}")
    if not v["ok"]:
        log.error(f"✗ قياس الوجهة لم يطابق: مفقود {v['missing'][:5]} "
                  f"وبصمة مختلفة {v['sha_mismatch'][:5]}")
        return 1
    if rec["rows"]["updated_same_path"]:
        log.warning(f"⚠︎ {rec['rows']['updated_same_path']} وثيقة معدَّلة بنفس "
                    f"filePath: ميزان سيتخطاها — نفّذ «استبدال» عنده "
                    f"({inj.UPDATE_PLAN_NAME})")
    return 0


def cmd_sync(args):
    """C-2: أمر ميزان الواحد — تنقيح → تصدير → حقن، وسطر JSON أخير للآلة.

    ميزان يشغّله كعملية خلفية (زر «تحديث من الزاحف») ويقرأ السطر الأخير فقط؛
    كل خطوة تفشل تُسجَّل في `steps` ولا تُسقط الأمر باستثناء غير معالج.
    """
    import json as _json
    from config import DB_PATH, MIZAN_ROOT
    result = {"ok": False, "steps": {}, "mizan_root": None}

    def stage(msg):  # سطر تقدّم على stdout يقرأه ميزان مباشرة
        print(f"المرحلة: {msg}", flush=True)

    # 1) تنقيح
    if not args.no_refine:
        stage("1/3 تنقيح (طبيعة → هوية → إحالات → حالة النفاذ)…")
        try:
            from database import create_tables, get_connection
            import postprocess
            create_tables()
            conn = get_connection()
            result["steps"]["refine"] = postprocess.refine_all(conn)
            conn.close()
        except Exception as exc:  # noqa: BLE001 — يُبلَّغ لا يُخفى
            result["steps"]["refine"] = {"error": str(exc)}
    # 2) تصدير
    stage("2/3 تصدير الحزمة (ملفات md/json + الفهرس)…")
    try:
        from exporter import build_package
        rep = build_package(db_path=DB_PATH, out_dir=args.out)
        result["steps"]["export"] = {
            "docs": rep["docs"], "articles": rep.get("articles_in_package"),
            "gate_ok": rep.get("gate_ok", True),
            "gate_failed": rep.get("gate_failed", [])}
        if not rep.get("gate_ok", True):
            result["error"] = "بوابة ميزان حمراء عند التصدير"
            print(_json.dumps(result, ensure_ascii=False))
            return 1
    except Exception as exc:  # noqa: BLE001
        result["steps"]["export"] = {"error": str(exc)}
        result["error"] = f"التصدير فشل: {exc}"
        print(_json.dumps(result, ensure_ascii=False))
        return 1
    # 3) حقن
    import mizan_injector as inj
    root = args.mizan_root or MIZAN_ROOT or inj.default_mizan_root()
    result["mizan_root"] = root
    if not root:
        result["error"] = "جذر ميزان غير معروف"
        print(_json.dumps(result, ensure_ascii=False))
        return 2
    stage(f"3/3 حقن في ميزان: {root}…")
    try:
        rec = inj.apply(args.out, root)
        result["steps"]["inject"] = {
            "added": rec["rows"]["added"],
            "files": rec["files_written"],
            "index_rows": rec["rows"]["index_rows_after"],
            "updated_same_path": rec["rows"]["updated_same_path"],
            "verify_ok": rec["verify_our_rows"]["ok"]}
        result["ok"] = bool(rec["verify_our_rows"]["ok"])
    except (inj.GateError, FileNotFoundError, OSError) as exc:
        result["steps"]["inject"] = {"error": str(exc)}
        result["error"] = f"الحقن فشل: {exc}"
    # 4) الاجتهادات (ف٣): المعتمَد فقط ⇒ content/legal_library/precedents/precedents.csv
    #    طبقة إضافية لا تُسقط المزامنة إن فشلت (تُبلَّغ).
    try:
        import precedent_export as pe
        from database import get_connection
        conn = get_connection()
        pm = pe.build_package(conn, out_dir=str(Path(args.out).parent / "precedents"))
        conn.close()
        dest = Path(root) / "content" / "legal_library" / "precedents"
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("precedents.csv", "precedents.json", "manifest.json"):
            shutil.copyfile(Path(pm["out_dir"]) / name, dest / name)
        result["steps"]["precedents"] = {"count": pm["count"], "overruled": pm["overruled"],
                                         "dest": str(dest)}
    except Exception as exc:  # noqa: BLE001 — يُبلَّغ لا يُخفى
        result["steps"]["precedents"] = {"error": str(exc)}
    print(_json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


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
    # «كم وثيقة عندي» ≠ «كم وثيقة تُصدَّر»: المُصدِّر يأخذ status='active' وحده،
    # والفارق كان يُسأل عنه كل مرة (قِيس: 513 في القاعدة مقابل 405 في الحزمة).
    cur.execute("SELECT status, COUNT(*) AS c FROM documents GROUP BY status"
                " ORDER BY c DESC")
    doc_rows = cur.fetchall()
    for row in doc_rows:
        log.info(f"documents[{row['status']}] = {row['c']}")
    active = next((r["c"] for r in doc_rows if r["status"] == "active"), 0)
    art = cur.execute(
        "SELECT COUNT(*) AS c FROM articles WHERE doc_id IN"
        " (SELECT id FROM documents WHERE status='active')").fetchone()["c"]
    log.info(f"قابلة للتصدير (active) = {active} وثيقة / {art} مادة")
    ident = cur.execute("SELECT COUNT(*) AS c FROM documents WHERE status='active'"
                        " AND identity_key IS NULL").fetchone()["c"]
    if ident:
        log.info(f"⚠︎ منها بلا هوية (رقم/سنة) = {ident} — تُصدَّر بعنوان فقط")
    # صيانة law-status --reidentify تملأ السنة وحدها أحياناً؛ الفرق يُرى هنا:
    # «سنة بلا رقم» تُصدَّر باسم ملف فيه السنة، فتظهر بميزان في موضعها الزمني.
    half = cur.execute(
        "SELECT COUNT(*) AS c FROM documents WHERE status='active'"
        " AND year IS NOT NULL AND number IS NULL").fetchone()["c"]
    if half:
        log.info(f"   منها بسنة بلا رقم = {half} — تُصدَّر بعنوان وسنة")
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
    from official_seed import seed_moj, seed_wipo, seed_bunud
    create_tables()
    conn = get_connection()
    stats = {"moj": seed_moj(conn, dry_run=args.dry),
             "wipo": seed_wipo(conn, dry_run=args.dry),
             "bunud": seed_bunud(conn, dry_run=args.dry)}
    conn.close()
    log.info(f"خلاصة البذر: {stats}")
    return 0


def cmd_parts(args):
    """ف٧: أجزاء الصك الواحد — عرض/ربط."""
    from database import create_tables, get_connection
    from law_parts import link_parts
    create_tables()
    conn = get_connection()
    if getattr(args, "explain", False):
        from law_parts import explain_parts
        for line in explain_parts(conn):
            log.info(line)
        return 0
    if args.link:
        rep = link_parts(conn)
        log.info(f"مجموعات الأجزاء: {rep['groups']}، أجزاء مربوطة: "
                 f"{rep['parts_linked']}")
        for head, num, year, parts, contained in rep["detail"]:
            log.info(f"  رأس #{head} (رقم {num}/{year or '؟'}) ← أجزاء {parts}"
                     + (f" (محتواة: {contained})" if contained else ""))
    else:
        rows = conn.execute(
            "SELECT part_of, COUNT(*) c FROM documents WHERE part_of IS NOT NULL "
            "GROUP BY part_of").fetchall()
        log.info("مجموعات مربوطة: " + (", ".join(
            f"#{r['part_of']}×{r['c']}" for r in rows) or "لا شيء"))
    return 0


def cmd_issue_dates(args):
    """A-2: تقرير تاريخ الإصدار — عيّنة بلا تاريخ/متعارضة للفحص."""
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()
    from issue_date import extract_issue_dates
    st = extract_issue_dates(conn)
    lines = [f"# تاريخ الإصدار: {st}"]
    rows = conn.execute(
        """SELECT id, title, identity_key, year, issue_date, issue_date_hijri,
                  issue_date_confidence, substr(clean_content, -220) AS tail
           FROM documents WHERE status='active'
           AND COALESCE(nature,'instrument')='instrument'
           AND (issue_date IS NULL OR issue_date_confidence LIKE '%conflict%')
           ORDER BY id LIMIT ?""", (args.limit,)).fetchall()
    for r in rows:
        lines.append(f"#{r['id']} | {(r['title'] or '')[:70]} | {r['identity_key']} "
                     f"| hijri={r['issue_date_hijri']} conf={r['issue_date_confidence']}")
        if r["issue_date_confidence"] and "conflict" in r["issue_date_confidence"]:
            from issue_date import extract_issue_date
            ev = extract_issue_date(conn.execute(
                "SELECT clean_content FROM documents WHERE id=?", (r["id"],)
            ).fetchone()[0] or "", r["year"])
            lines.append(f"    ⚠ الدليل: {ev.get('evidence')}")
        lines.append("    ⌐ " + " ".join((r["tail"] or "").split())[-200:])
    text = "\n".join(lines)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8")
        log.info(f"{lines[0]} — كُتب إلى {args.out}")
    else:
        log.info(text)
    conn.close()


def cmd_refine(args):
    """تنقيح شامل بأمر واحد (يجري آلياً أيضاً في نهاية كل دورة زحف)."""
    from database import create_tables, get_connection
    import postprocess
    create_tables()
    conn = get_connection()
    log.info(postprocess.format_summary(postprocess.refine_all(conn)))
    conn.close()


def cmd_nature(args):
    """ف٤: طبيعة الوثائق — تصنيف/توزيع (صك، أعمال تحضيرية، فهرس، مسودة…)."""
    from database import create_tables, get_connection
    from doc_nature import reclassify_documents
    create_tables()
    conn = get_connection()
    if args.reclassify:
        rep = reclassify_documents(conn)
        log.info(f"التوزيع ({rep['total']} وثيقة): {rep['distribution']}")
        if rep["travaux_by_parent"]:
            log.info(f"الأعمال التحضيرية حسب القانون الأم: "
                     f"{rep['travaux_by_parent']}")
    else:
        rows = conn.execute(
            "SELECT COALESCE(nature,'instrument') n, COUNT(*) c FROM documents "
            "GROUP BY n ORDER BY c DESC").fetchall()
        log.info("التوزيع: " + ", ".join(f"{r['n']}={r['c']}" for r in rows))
    unid = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE identity_key IS NULL AND "
        "status='active' AND COALESCE(nature,'instrument')='instrument'"
    ).fetchone()[0]
    log.info(f"صكوك نشطة بلا هوية (الرقم الصادق): {unid}")
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
    if getattr(args, "unidentified", 0):
        # ف٣: عيّنة «بلا هوية» لتحسين المستخرج بالدليل (عناوين حقيقية)
        # ف٦: صكوك فقط (nature='instrument') — الأعمال التحضيرية والفهارس
        # ليست «بلا هوية» بل بلا حاجة إليها؛ وكل صك يُفرز إلى فئة علاج.
        from law_identity import triage_unidentified
        rows = conn.execute(
            """SELECT id, title, number, year, part_of,
                      substr(clean_content, 1, 300) AS head
               FROM documents WHERE identity_key IS NULL
               AND status='active' AND COALESCE(nature,'instrument')='instrument'
               AND part_of IS NULL AND parent_identity IS NULL
               ORDER BY id LIMIT ?""",
            (args.unidentified,)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE identity_key IS NULL "
            "AND status='active' AND COALESCE(nature,'instrument')='instrument'"
            " AND part_of IS NULL AND parent_identity IS NULL"
        ).fetchone()[0]
        folded = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE identity_key IS NULL "
            "AND status='active' AND part_of IS NOT NULL").fetchone()[0]
        # ف٧: الجزء المربوط برأسه ليس «بلا هوية» — هويته هوية رأسه عند التصدير
        log.info(f"أجزاء مطوية تحت رأس (مستثناة من العدّ): {folded}")
        log.info(f"صكوك نشطة بلا هوية: {total} (عرض {len(rows)})")
        by_cat: dict = {}
        lines = []
        for r in rows:
            tri = triage_unidentified(r["title"] or "", r["head"] or "")
            by_cat.setdefault(tri["category"], []).append((r, tri))
        for cat, items in sorted(by_cat.items()):
            lines.append(f"## {cat} ({len(items)})")
            for r, tri in items:
                head = " ".join((r["head"] or "").split())[:160]
                lines.append(f"#{r['id']} | {r['title']}\n    db=(number={r['number']},"
                             f" year={r['year']}, part_of={r['part_of']}) hint={tri['hint']}"
                             f"\n    ↳ {head}")
        summary = ", ".join(f"{c}={len(v)}" for c, v in sorted(by_cat.items()))
        log.info(f"الفرز: {summary}")
        out_file = getattr(args, "out", None)
        if out_file:
            # إلى ملف بدل الشاشة: المخرجات الطويلة تُرفق لا تُلصق
            with open(out_file, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(f"# صكوك نشطة بلا هوية: {total} — الفرز: {summary}\n")
                fh.write("\n".join(lines) + "\n")
            log.info(f"كُتبت العيّنة إلى {out_file}")
        else:
            for ln in lines:
                log.info(ln)
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
    if getattr(args, "repealed_report", None):
        # ف٥: كل صك عُلِّم «ملغى» مع دليله (المعدِّل + السياق) — للمراجعة
        # البشرية قبل الوثوق؛ إلى ملف لأن المخرجات طويلة.
        # صك واحد لكل سطر؛ الأدلة المكررة (نفس المُلغي ونفس السياق من
        # نسخ متعددة للوثيقة) تُجمع بعدّاد — قِيس: المرسوم 49/1962 ظهر 17
        # مرة لأن القانون 17/2010 محفوظ بـ17 نسخة.
        rows = conn.execute(
            """SELECT d.identity_key, MIN(d.title) AS title, d.year,
                      m.identity_key AS by_key, MIN(m.title) AS by_title,
                      m.year AS by_year, MIN(a.context) AS context,
                      COUNT(*) AS copies
               FROM documents d
               JOIN law_amendments a ON a.target_identity = d.identity_key
               JOIN documents m ON m.id = a.amending_doc_id
               WHERE d.legal_status = 'ملغى' AND a.action = 'repeal'
               GROUP BY d.identity_key, COALESCE(m.identity_key, m.title)
               ORDER BY d.year, d.identity_key""").fetchall()
        targets = {r["identity_key"] for r in rows}
        with open(args.repealed_report, "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(f"# {len(targets)} صكاً معلَّماً «ملغى» — راجع الدليل "
                     "قبل الاعتماد\n\n")
            for r in rows:
                fh.write(f"## {r['identity_key']} — {r['title']} ({r['year']})\n")
                fh.write(f"- ألغاه: {r['by_title']} ({r['by_year']})"
                         f"{' ×' + str(r['copies']) + ' نسخة' if r['copies'] > 1 else ''}\n")
                fh.write(f"- السياق: …{' '.join((r['context'] or '').split())}…\n\n")
        log.info(f"تقرير الملغى: {len(targets)} صكاً / {len(rows)} دليلاً "
                 f"→ {args.repealed_report}")
    if getattr(args, "why", None):
        # تشخيص: من يذكر هذا الصك، وبأي فعل، ولماذا قُبل/أُسقط الدليل
        rows = conn.execute(
            """SELECT a.action, m.id, m.title, m.year, m.identity_key,
                      COALESCE(m.nature,'instrument') AS nature, m.status,
                      substr(a.context,1,120) AS ctx
               FROM law_amendments a JOIN documents m ON m.id=a.amending_doc_id
               WHERE a.target_identity=?""", (args.why,)).fetchall()
        tgt = conn.execute("SELECT year, legal_status FROM documents WHERE "
                           "identity_key=? LIMIT 1", (args.why,)).fetchone()
        log.info(f"المستهدَف {args.why}: سنة={tgt['year'] if tgt else '?'} "
                 f"حالة={tgt['legal_status'] if tgt else '?'} | "
                 f"{len(rows)} دليل")
        for r in rows:
            reasons = []
            if r["nature"] != "instrument":
                reasons.append(f"مُسقَط: طبيعة={r['nature']}")
            if tgt and r["year"] is not None and tgt["year"] is not None \
                    and r["year"] < tgt["year"]:
                reasons.append(f"مُسقَط: أقدم ({r['year']}<{tgt['year']})")
            log.info(f"  {r['action']} ← #{r['id']} {r['title'][:60]} "
                     f"(سنة={r['year']}, هوية={r['identity_key']}, "
                     f"status={r['status']}) {' '.join(reasons) or 'مقبول'}")
            log.info(f"      «{' '.join((r['ctx'] or '').split())}»")
        mentions = conn.execute(
            """SELECT id, title, year FROM documents
               WHERE clean_content LIKE ? AND id NOT IN
               (SELECT amending_doc_id FROM law_amendments WHERE target_identity=?)
               LIMIT 10""",
            (f"%{args.why.split(':')[1]} لعام {args.why.split(':')[2]}%",
             args.why)).fetchall()
        if mentions:
            log.info(f"  وثائق تذكر الرقم/السنة نصياً بلا إحالة مسجلة "
                     f"({len(mentions)}):")
            for m in mentions:
                log.info(f"    #{m['id']} {m['title'][:70]} (سنة={m['year']})")
    if args.law:
        st = conn.execute("SELECT legal_status, legal_status_reason, issue_date FROM documents"
                          " WHERE identity_key=? AND status='active'", (args.law,)).fetchone()
        if st:
            log.info(f"  الحالة: {st['legal_status']} | صدر: {st['issue_date']} | السبب: {st['legal_status_reason']}")
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


def cmd_article_links(args) -> int:
    import database
    from article_links import rebuild_article_links
    conn = database.get_connection()
    st = rebuild_article_links(conn)
    lines = [f"# مواد: {st}"]
    rows = conn.execute("""SELECT aa.target_identity, aa.article_number, aa.action,
                                  d.identity_key AS by_key, aa.context
                           FROM article_amendments aa JOIN documents d ON d.id=aa.amending_doc_id
                           ORDER BY aa.target_identity, CAST(aa.article_number AS INTEGER)""").fetchall()
    for r in rows:
        lines.append(f"{r['target_identity']} م{r['article_number']} ← "
                     f"{'إلغاء' if r['action']=='repeal' else 'تعديل'} بـ {r['by_key']} | {r['context'][:120]}")
    txt = "\n".join(lines)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(txt)
        print(lines[0], f"→ {args.out}")
    else:
        print(txt)
    conn.close()
    return 0


def cmd_missing(args) -> int:
    import database
    from missing_targets import missing_targets, format_report
    conn = database.get_connection()
    txt = format_report(missing_targets(conn, args.limit))
    conn.close()
    if args.out:
        open(args.out, "w", encoding="utf-8").write(txt)
        print(txt.splitlines()[0], f"→ {args.out}")
    else:
        print(txt)
    return 0


def cmd_seed_bunud(args) -> int:
    from database import create_tables, get_connection
    from official_seed import seed_bunud
    create_tables()
    conn = get_connection()
    st = seed_bunud(conn, dry_run=args.dry)
    conn.close()
    print(f"بنود: {st}")
    return 0


def cmd_precedents(args) -> int:
    """ف٣: جمع الاجتهادات من mohamah.net إلى الجداول الجديدة (pending)."""
    from database import create_tables, get_connection
    from fetcher import fetch
    import precedent_source as ps
    create_tables()
    conn = get_connection()
    if args.stats:
        print(ps.stats(conn))
        conn.close()
        return 0

    def http_get(url):
        r = fetch(url)
        return r["html"] if r.get("ok") else None

    rep = ps.harvest_mohamah(conn, http_get, limit=args.limit, dry_run=args.dry)
    pages = rep.pop("pages")
    print("الاجتهادات (mohamah.net):", rep)
    for st in pages[-10:]:
        print("  ", st)
    if not args.dry:
        print("الحالة الآن:", ps.stats(conn))
    conn.close()
    return 0


def cmd_precedents_bar(args) -> int:
    """ف٣: منتدى محامي سوريا (damascusbar) عبر أرشيف Wayback — قابل للاستئناف."""
    import requests

    import damascusbar_source as ds
    import fetcher
    from config import USER_AGENT
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()

    import time
    last = [0.0]
    MIN_GAP = 3.0                      # أرشيف الإنترنت يقطع الاتصال عند أسرع من ذلك
    BACKOFF = (10, 30, 60)

    def get_bytes(url):
        for attempt in range(len(BACKOFF) + 1):
            wait = MIN_GAP - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                r = requests.get(url, timeout=90, headers={"User-Agent": USER_AGENT})
            except requests.RequestException as e:
                if attempt < len(BACKOFF):
                    print(f"  قطع اتصال ({e.__class__.__name__}) — انتظار {BACKOFF[attempt]} ث ثم إعادة")
                    time.sleep(BACKOFF[attempt])
                    continue
                print("  فشل نهائي:", url[-60:], e.__class__.__name__)
                return None
            if r.status_code in (429, 503) and attempt < len(BACKOFF):
                print(f"  حدّ المعدل {r.status_code} — انتظار {BACKOFF[attempt]} ث")
                time.sleep(BACKOFF[attempt])
                continue
            return r.content if r.status_code == 200 else None
        return None

    def get_text(url):
        b = get_bytes(url)
        return b.decode("utf-8", "replace") if b else None

    rep = ds.harvest_damascusbar(conn, get_bytes, get_text, limit=args.limit, dry_run=args.dry,
                                 refresh_threads=args.refresh)
    pages = rep.pop("pages")
    aborted = rep.pop("aborted", None)
    print("منتدى محامي سوريا (Wayback):", rep)
    if aborted:
        print("!!", aborted)
    for st in pages:
        if st["citations"]:
            print("  ", st["thread"], st["citations"], st.get("title", "")[:60])
    conn.close()
    return 0


def cmd_precedents_export(args) -> int:
    """ف٣: حزمة الاجتهادات لميزان (approved فقط افتراضياً)."""
    import precedent_export as pe
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()
    m = pe.build_package(conn, out_dir=args.out, include_pending=args.include_pending)
    print("حزمة الاجتهادات:", m)
    conn.close()
    return 0


def cmd_precedents_approve(args) -> int:
    """ف٣: اعتماد جماعي بقرار المالك (ثقة ≥ حد، واختيارياً مصدران مستقلان)."""
    import precedent_export as pe
    from database import create_tables, get_connection
    create_tables()
    conn = get_connection()
    r = pe.approve_bulk(conn, min_confidence=args.min_confidence, multi_source_only=args.multi_source,
                        courts=tuple(args.court) if args.court else None, dry_run=args.dry)
    print("الاعتماد الجماعي:", r)
    conn.close()
    return 0


def cmd_dedup_audit(args) -> int:
    import database
    from dedup import audit_dedup, rebalance_suspicious
    conn = database.get_connection()
    fixed = rebalance_suspicious(conn) if args.fix else 0
    rows = audit_dedup(conn)
    sus = [r for r in rows if r["suspicious"]]
    lines = [f"# أزواج التكرار: {len(rows)} | مشبوه (الخاسر أكمل بوضوح): {len(sus)} | أُعيد ميزانه: {fixed}"]
    for r in sorted(rows, key=lambda r: (not r["suspicious"], r["identity"])):
        flag = "⚠" if r["suspicious"] else " "
        lines.append(f"{flag} {r['identity']} | فائز #{r['winner_id']} ط{r['winner_tier']} {r['winner_articles']} مادة"
                     f" | خاسر #{r['loser_id']} ط{r['loser_tier']} {r['loser_articles']} مادة ({r['loser_status']})")
    txt = "\n".join(lines)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(txt)
        print(lines[0], f"→ {args.out}")
    else:
        print(txt)
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

    sp = sub.add_parser("sync",
                        help="C-2: تنقيح → تصدير → حقن في ميزان؛ آخر سطر JSON")
    sp.add_argument("--out", default="export/content_package")
    sp.add_argument("--mizan-root", default=None)
    sp.add_argument("--no-refine", action="store_true")
    sp.set_defaults(fn=cmd_sync)
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

    sp = sub.add_parser("issue-dates", help="A-2: استخراج تاريخ الإصدار + عيّنة ما لم يُستخرج")
    sp.add_argument("--limit", type=int, default=60)
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_issue_dates)
    sp = sub.add_parser(
        "refine", help="تنقيح شامل: طبيعة → هوية → أجزاء → إحالات وحالة النفاذ")
    sp.set_defaults(fn=cmd_refine)
    sp = sub.add_parser("nature",
                        help="طبيعة الوثائق: صك/أعمال تحضيرية/فهرس/مسودة (ف٤)")
    sp.add_argument("--reclassify", action="store_true",
                    help="إعادة تصنيف كل الوثائق المخزَّنة وكتابة nature")
    sp.set_defaults(fn=cmd_nature)

    sp = sub.add_parser("parts",
                        help="ف٧: ربط أجزاء الصك الواحد المشتّتة (part_of)")
    sp.add_argument("--link", action="store_true",
                    help="حساب المجموعات وكتابة documents.part_of")
    sp.add_argument("--explain", action="store_true",
                    help="تشخيص: لكل رقم مكرر، نطاق مواد كل وثيقة وسبب القبول/الرفض")
    sp.set_defaults(fn=cmd_parts)

    sp = sub.add_parser("law-status",
                        help="ف١: حساب الحالة القانونية (ساري/معدَّل/ملغى)")
    sp.add_argument("--unidentified", type=int, default=0, metavar="N",
                    help="عرض N وثيقة نشطة بلا هوية (عنوان + مطلع النص)")
    sp.add_argument("--out", metavar="FILE",
                    help="كتابة عيّنة --unidentified إلى ملف بدل الشاشة")
    sp.add_argument("--reidentify", action="store_true",
                    help="إعادة استخراج هوية الوثائق المخزَّنة بالكود الحالي أولاً")
    sp.add_argument("--rebuild", action="store_true",
                    help="إعادة بناء جدول الإحالات من كل الوثائق أولاً")
    sp.add_argument("--list", action="store_true",
                    help="عرض كل الإحالات المستخرجة (تعديل/إلغاء) ومستهدفاتها")
    sp.add_argument("--repealed-report", metavar="FILE",
                    help="كتابة كل صك «ملغى» مع دليله إلى ملف للمراجعة")
    sp.add_argument("--why", metavar="IDENTITY",
                    help="تشخيص: أدلة صك ولماذا قُبلت/أُسقطت + من يذكره بلا إحالة")
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

    sp = sub.add_parser("article-links", help="A-4: تقرير التعديلات على مستوى المادة")
    sp.add_argument("--out", metavar="FILE")
    sp.set_defaults(fn=cmd_article_links)

    sp = sub.add_parser("missing", help="B-1: الصكوك غير المحصودة التي تستهدفها الإحالات، بالأهمية")
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--out", metavar="FILE")
    sp.set_defaults(fn=cmd_missing)

    sp = sub.add_parser("seed-bunud", help="B-2: بذر تشريعات بنود (bunud.ai) من خريطة الموقع")
    sp.add_argument("--dry", action="store_true")
    sp.set_defaults(fn=cmd_seed_bunud)

    sp = sub.add_parser("precedents", help="ف٣: جمع الاجتهادات (mohamah.net) بحالة بانتظار المراجعة")
    sp.add_argument("--limit", type=int, default=None, help="عدد الصفحات الجديدة كحد أقصى")
    sp.add_argument("--dry", action="store_true", help="جلب وتحليل بلا كتابة")
    sp.add_argument("--stats", action="store_true", help="أعداد الجداول فقط")
    sp.set_defaults(fn=cmd_precedents)

    sp = sub.add_parser("precedents-bar", help="ف٣: منتدى محامي سوريا عبر Wayback (يُستأنف تلقائياً)")
    sp.add_argument("--limit", type=int, default=None, help="عدد الخيوط الجديدة كحد أقصى")
    sp.add_argument("--dry", action="store_true", help="جلب وتحليل بلا كتابة")
    sp.add_argument("--refresh", action="store_true", help="إعادة بناء قائمة الخيوط من CDX")
    sp.set_defaults(fn=cmd_precedents_bar)

    sp = sub.add_parser("precedents-export", help="ف٣: حزمة الاجتهادات لميزان (export/precedents)")
    sp.add_argument("--out", default="export/precedents")
    sp.add_argument("--include-pending", action="store_true", help="إضافة غير المراجَع بوسمه (لشاشة المراجعة)")
    sp.set_defaults(fn=cmd_precedents_export)

    sp = sub.add_parser("precedents-approve", help="ف٣: اعتماد جماعي للقرارات عالية الثقة")
    sp.add_argument("--min-confidence", type=float, default=0.85)
    sp.add_argument("--multi-source", action="store_true", help="فقط ما ورد في مصدرين مستقلين")
    sp.add_argument("--court", action="append", help="حصر بجهة (نقض، هيئة_عامة_نقض…) — يتكرر")
    sp.add_argument("--dry", action="store_true", help="عدّ فقط بلا تعديل")
    sp.set_defaults(fn=cmd_precedents_approve)

    sp = sub.add_parser("dedup-audit", help="B-3: مراجعة أزواج التكرار (الفائز/الخاسر) وإعادة الميزان للمشبوه")
    sp.add_argument("--fix", action="store_true", help="إعادة الميزان للأزواج المشبوهة الآن")
    sp.add_argument("--out", metavar="FILE")
    sp.set_defaults(fn=cmd_dedup_audit)

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

    sp = sub.add_parser("inject",
                        help="حقن حزمة جاهزة في جذر ميزان (دمج فهرس + ملفات + إيصالية)")
    sp.add_argument("pkg", nargs="?", default="export/content_package",
                    help="مجلد الحزمة المولَّد بـ`cli export`")
    sp.add_argument("--mizan-root", default=None,
                    help="جذر مستودع lawyer-office2 (يحتوي content/)؛ افتراضياً config.MIZAN_ROOT")
    sp.add_argument("--preview", action="store_true",
                    help="احسب واطبع ما سيحدث، بلا كتابة أي بايت")
    sp.add_argument("--replace-index", action="store_true",
                    help="استبدل فهرسهم بالكامل بدل الدمج (متلف: يتخلى عن صفوفهم)")
    sp.add_argument("--force", action="store_true",
                    help="اسمح بالحقن ولو كانت بوابة الحزمة حمراء (يُسجَّل في الإيصالية)")
    sp.set_defaults(fn=cmd_inject)

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
