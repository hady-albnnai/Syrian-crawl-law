# -*- coding: utf-8 -*-
"""core_data.py — الواجهة الحقيقية بين النواة والشاشات (عقد Core+Shell §2).

يستبدل mock_data: نفس الأسماء والأشكال حرفياً، لكن كل قراءة تأتي من
قاعدة البيانات/الطابور/الحزمة المصدَّرة الحقيقية وقت العرض. القيم تُحسب
عند كل وصول (module __getattr__ — PEP 562) فلا تتقادم بعد دورة زحف.
"""
import csv
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SOURCE = ("law-library.syriaforums.net — مكتبة القانون السوري "
                  "(منتدى phpBB)")
DEFAULT_CREDIBILITY = 0.6
DEFAULT_SECTIONS = ["القانون المدني", "القانون الجزائي", "أصول المحاكمات",
                    "الأحوال الشخصية", "القانون التجاري", "الدساتير"]
PACKAGE_DIR = Path("export/content_package")
STATUS_LABELS = {
    "human_verified": ("مراجَع بشرياً", "badgeSuccess"),
    "auto_extracted": ("استخراج آلي", "badgeInfo"),
    "needs_review": ("يحتاج مراجعة", "badgeWarning"),
}
_DOC_TYPE_AR = {"law": "قانون", "decree": "مرسوم تشريعي"}
_STATUS_MAP = {"human_verified": "human_verified",
               "auto_accepted": "auto_extracted"}


@dataclass
class DocumentRow:
    title: str
    kind: str
    branch: str
    articles: int
    quality: float
    status: str
    year: int
    doc_id: int = 0
    source_url: str = ""
    # ف٢ — ما تحتاجه شاشة المراجعة فعلاً (لا تُخمَّن: None عند غياب العمود)
    identity_key: str = ""
    legal_status: str = ""
    domain_tier: int = 0


@dataclass
class DiscoveryRow:
    title: str
    url: str
    engine: str
    score: float
    verdict: str     # recommended / rejected / blocked
    via: str
    source_key: str = ""


@dataclass
class GapRow:
    branch: str          # اسم الفرع بالعربية (config.BRANCH_AR)
    count: int
    expected_min: float
    is_gap: bool


@dataclass
class SourcePerformanceRow:
    name: str
    runs_count: int
    new_identities_total: int
    consecutive_empty_runs: int
    learned_status: str   # active | exhausted



def _connect() -> sqlite3.Connection | None:
    from config import DB_PATH
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def _count(conn, table: str, where: str = "") -> int:
    """عدّ لا ينهار على جدول غير موجود — قاعدة جديدة أو نصف مهجرة حالة
    عادية للشاشة (قِيس: أول إقلاع على صندوق بلا قاعدة كان يستثني
    OperationalError: no such table: documents من refresh())."""
    if not _has_table(conn, table):
        return 0
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _sources():
    conn = _connect()
    if conn is None or not _has_table(conn, "sources"):
        conn and conn.close()
        return []
    rows = [dict(r) for r in conn.execute("SELECT * FROM sources")]
    conn.close()
    return rows


def _documents():
    conn = _connect()
    if conn is None or not _has_table(conn, "documents"):
        conn and conn.close()
        return []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    extra = "".join(f", d.{c}" for c in
                    ("identity_key", "legal_status", "source_domain_tier")
                    if c in cols)
    rows = conn.execute(f"""
        SELECT d.id, d.title, d.doc_type, d.branch, d.year, d.legal_score,
               d.review_status, d.status, d.source_url,
               (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.id)
                   AS n_articles{extra}
        FROM documents d ORDER BY d.id""").fetchall()
    conn.close()
    out = []
    for r in rows:
        status = _STATUS_MAP.get(r["review_status"], "needs_review")
        if r["status"] == "rejected":
            status = "rejected"
        elif r["status"] != "active":
            status = "needs_review"
        from config import BRANCH_AR  # مصدر حقيقة واحد — 14 فرعاً
        out.append(DocumentRow(
            identity_key=(r["identity_key"] if "identity_key" in r.keys() else "") or "",
            legal_status=(r["legal_status"] if "legal_status" in r.keys() else "") or "",
            domain_tier=(r["source_domain_tier"]
                         if "source_domain_tier" in r.keys() and r["source_domain_tier"]
                         else 0),
            doc_id=r["id"],
            title=r["title"] or "بدون عنوان",
            kind=_DOC_TYPE_AR.get(r["doc_type"], r["doc_type"] or "نص"),
            branch=BRANCH_AR.get(r["branch"], r["branch"] or "غير مصنف"),
            articles=r["n_articles"],
            quality=round(r["legal_score"] or 0.0, 2),
            status=status,
            year=r["year"] or 0,
            source_url=r["source_url"] or ""))
    return out


def document_text(doc_id: int, cap: int = 20_000) -> tuple[str, int]:
    """نص وثيقة لمعاينة المراجعة، مع سقف عرض صريح.

    قِيس على الشاشة القديمة: clean_content يُحمَّل كاملاً (حتى
    MAX_CLEAN_CONTENT_CHARS = 2,000,000) في QPlainTextEdit عند كل نقرة —
    تجميد فعلي للواجهة مع متن قانوني كامل (قانون العقوبات 775 مادة).
    يعيد (النص المقصوص، الطول الحقيقي) ليُقال للمستخدم كم يُخفى ولا يُوهَم.
    """
    conn = _connect()
    if conn is None:
        return "", 0
    row = conn.execute(
        "SELECT LENGTH(clean_content) AS n, clean_content FROM documents "
        "WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    if row is None:
        return "", 0
    text = row["clean_content"] or ""
    total = row["n"] or len(text)
    return (text[:cap] if cap and len(text) > cap else text), total


def _log_events(limit=200):

    conn = _connect()
    if conn is None or not _has_table(conn, "crawl_log"):
        conn and conn.close()
        return []
    rows = conn.execute(
        "SELECT timestamp, event_type, message, status FROM crawl_log "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [(r["timestamp"][11:19] if r["timestamp"] else "",
             r["event_type"] or "-", r["message"] or "",
             r["status"] or "info") for r in reversed(rows)]


def _run_stats():
    """إحصاءات حية: الطابور + آخر دورة (لشاشة التشغيل)."""
    conn = _connect()
    if conn is None:
        return None
    out = {"queue": {}, "last_run": None,
           "docs": _count(conn, "documents"),
           "articles": _count(conn, "articles")}
    if _has_table(conn, "crawl_tasks"):
        for r in conn.execute(
                "SELECT status, COUNT(*) n FROM crawl_tasks GROUP BY status"):
            out["queue"][r["status"]] = r["n"]
    if _has_table(conn, "crawl_runs"):
        r = conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC "
                         "LIMIT 1").fetchone()
        out["last_run"] = dict(r) if r else None
    conn.close()
    return out


def _discovery_rows():
    _verdict = {"approved": "recommended", "proposed": "recommended",
                "rejected": "rejected", "exhausted": "recommended"}
    rows = [DiscoveryRow(
        title=s["name"] or s["base_url"], url=s["base_url"],
        engine=s["engine"] or "unknown",
        score=round(s["credibility"] or 0.0, 2),
        verdict=_verdict.get(s["status"], "rejected"),
        via=s["discovered_via"] or "manual",
        source_key=s["source_key"]) for s in _sources()]
    # الأحدث اكتشافاً أولاً — نفس ترتيب ما يراه المستخدم منطقياً بعد ضغط
    # «اكتشاف تلقائي» (أضيف حديثاً ⇒ id أكبر ⇒ id غير محمَّل هنا فنستخدم
    # ترتيب _sources نفسه، وهو بحسب id تصاعدياً من SELECT * أعلاه، فنعكسه)
    return list(reversed(rows))


def _approved_sources():
    names = [f'{s["base_url"]} — {s["name"] or ""}'.strip(" —")
             for s in _sources() if s["status"] == "approved"]
    return names or [DEFAULT_SOURCE]


def _sections():
    conn = _connect()
    if conn is None or not _has_table(conn, "crawl_tasks"):
        conn and conn.close()
        return list(DEFAULT_SECTIONS)
    rows = [r[0] for r in conn.execute(
        "SELECT DISTINCT section FROM crawl_tasks WHERE section IS NOT NULL "
        "ORDER BY section")]
    conn.close()
    return rows or list(DEFAULT_SECTIONS)


def validate_package(pkg_dir=None) -> list:
    """بوابة التحقق من الحزمة — **منفّذة في مكان واحد** (verify_package).

    كانت هذه الدالة تحمل نسختها الخاصة من منطق الفحص (تحمّص ملف md بشدة
    أخفّ من بوابة ميزان)، فمرّ كسر دلالة sha256 في الفهرس دون أن تراه
    الواجهة (قِيس 2026-09-17). الآن تستدعي verify_package.check_package
    التي تطابق سلوك csv_legal_library_importer.dart سطرًا بسطر — أي أن
    «أخضر الواجهة» يعني حرفياً «ميزان سيستورد كل الصفوف».
    """
    # القراءة وقت النداء لا وقت التعريف — حتى يعمل الاختبار مع PACKAGE_DIR مُبدَّل
    pkg_dir = Path(pkg_dir) if pkg_dir else PACKAGE_DIR
    import verify_package
    return verify_package.check_package(pkg_dir)


def package_counts(pkg_dir=None) -> dict:
    """عدادات الحزمة من القرص (لا من القاعدة): صفوف/ملفات md/مواد."""
    pkg_dir = Path(pkg_dir) if pkg_dir else PACKAGE_DIR
    import verify_package
    c = verify_package.article_counts(pkg_dir)
    manifest = pkg_dir / "mizan_package_manifest.json"
    c["manifest"] = manifest.exists()
    if manifest.exists():
        import json
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            c["schema_version"] = m.get("schema_version")
            c["generated_at"] = m.get("generated_at")
            c["corpus"] = m.get("corpus", {})
        except (ValueError, OSError):
            pass
    return c


def run_history(limit: int = 10) -> list:
    """سجل دورات الزحف الحقيقي (crawl_runs) — لقسم التقارير (طلب المالك
    2026-09-17): الأرقام المقيسة لكل دورة، لا نص عام."""
    conn = _connect()
    if conn is None or not _has_table(conn, "crawl_runs"):
        conn and conn.close()
        return []
    rows = conn.execute(
        "SELECT id, started_at, finished_at, mode, pages, docs, articles,"
        " skipped, failures, branch_breakdown_json FROM crawl_runs "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def failure_breakdown(limit: int = 400) -> list:
    """توزيع أسباب الفشل من crawl_tasks.last_error — رقمياً لا سرداً."""
    conn = _connect()
    if conn is None or not _has_table(conn, "crawl_tasks"):
        conn and conn.close()
        return []
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(last_error,''),'(بلا سبب مسجل)') AS reason,"
        " status, COUNT(*) AS n FROM crawl_tasks "
        "WHERE status IN ('failed','blocked','needs_review') "
        "GROUP BY reason, status ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rejection_stats() -> dict:
    """توزيع أسباب الرفض البشري (rejection_reasons) — ما تعلّمه الزاحف."""
    conn = _connect()
    if conn is None or not _has_table(conn, "rejection_reasons"):
        conn and conn.close()
        return {"total": 0, "by_category": []}
    total = conn.execute("SELECT COUNT(*) FROM rejection_reasons").fetchone()[0]
    rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM rejection_reasons "
        "GROUP BY category ORDER BY n DESC").fetchall()
    conn.close()
    return {"total": total, "by_category": [dict(r) for r in rows]}


def identity_and_status_stats() -> dict:
    """الهوية والحالة القانونية على مستوى القاعدة — الأرقام التي تهمّ
    المحامي قبل أن يفتح أي ملف: كم صكّاً له هوية؟ وكم منها سارٍ؟"""
    conn = _connect()
    if conn is None or not _has_table(conn, "documents"):
        conn and conn.close()
        return {}
    out = {}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    out["documents"] = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status='active'").fetchone()[0]
    out["with_identity"] = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status='active' "
        "AND identity_key IS NOT NULL AND identity_key != ''").fetchone()[0] if "identity_key" in cols else 0
    if "legal_status" in cols:
        for r in conn.execute(
                "SELECT COALESCE(legal_status,'(بلا حالة)') s, COUNT(*) n "
                "FROM documents WHERE status='active' GROUP BY s ORDER BY n DESC"):
            out.setdefault("legal_status", {})[r["s"]] = r["n"]
    if "source_domain_tier" in cols:
        for r in conn.execute(
                "SELECT COALESCE(source_domain_tier,4) t, COUNT(*) n "
                "FROM documents WHERE status='active' GROUP BY t ORDER BY t"):
            out.setdefault("domain_tier", {})[str(r["t"])] = r["n"]
    if "review_status" in cols:
        for r in conn.execute(
                "SELECT COALESCE(review_status,'auto_accepted') rs, COUNT(*) n "
                "FROM documents WHERE status='active' GROUP BY rs ORDER BY n DESC"):
            out.setdefault("review_status", {})[r["rs"]] = r["n"]
    conn.close()
    return out


def _gap_report():
    """تحليل فجوات فروع القانون (gap_analysis.py، §7) — حية من القاعدة،
    لا جدول مُخمَّن. تعيد قائمة مرتبة: الفجوات أولاً (الأكثر نقصاً أعلى)."""
    from config import BRANCH_AR
    conn = _connect()
    if conn is None or not _has_table(conn, "documents"):
        conn and conn.close()
        return []
    import gap_analysis
    report = gap_analysis.analyze_gaps(conn)
    conn.close()
    rows = [GapRow(branch=BRANCH_AR.get(b, b), count=info["count"],
                   expected_min=info["expected_min"], is_gap=info["gap"])
            for b, info in report.items()]
    rows.sort(key=lambda r: (not r.is_gap, r.count))
    return rows


def _gap_queries(limit_branches: int = 5):
    """أمثلة استعلامات بحث موجَّهة للفروع الناقصة — نفس ما يستخدمه
    autopilot.generate_candidates فعلياً بالدورة القادمة (لا نص توضيحي)."""
    conn = _connect()
    if conn is None or not _has_table(conn, "documents"):
        conn and conn.close()
        return []
    import gap_analysis
    report = gap_analysis.analyze_gaps(conn)
    conn.close()
    gapped = [b for b, info in report.items() if info["gap"]]
    out = []
    for branch in gapped[:limit_branches]:
        out.extend(gap_analysis.gap_queries_for_branch(branch, limit=2))
    return out


def _source_performance():
    """أداء كل مصدر معتمد عبر الدورات (learning.py، §5) — حي من القاعدة."""
    conn = _connect()
    if conn is None or not _has_table(conn, "source_performance"):
        conn and conn.close()
        return []
    rows = conn.execute("""
        SELECT sp.*, s.name, s.base_url FROM source_performance sp
        JOIN sources s ON s.source_key = sp.source_key
        ORDER BY sp.new_identities_total DESC
    """).fetchall()
    conn.close()
    return [SourcePerformanceRow(
        name=r["name"] or r["base_url"],
        runs_count=r["runs_count"],
        new_identities_total=r["new_identities_total"],
        consecutive_empty_runs=r["consecutive_empty_runs"],
        learned_status=r["learned_status"]) for r in rows]


def _dedup_stats():
    """عدد قرارات التنقيح المسجَّلة فعلياً (dedup.py، §4) — للشفافية:
    كم مرة اكتُشف قانون مكرر من مصدرين وحُسم آلياً."""
    conn = _connect()
    if conn is None or not _has_table(conn, "dedup_decisions"):
        conn and conn.close()
        return {"total": 0, "recent": []}
    total = conn.execute(
        "SELECT COUNT(*) FROM dedup_decisions").fetchone()[0]
    recent = conn.execute(
        "SELECT identity_key, decisive_criterion, decided_at "
        "FROM dedup_decisions ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    return {"total": total, "recent": [dict(r) for r in recent]}


def _db_info():
    """معلومات القاعدة الحقيقية لشاشة الإعدادات — لا مسار Windows وهمي."""
    from config import DB_PATH, VERSION
    p = Path(DB_PATH)
    return {
        "path": str(p.resolve()),
        "exists": p.exists(),
        "size_mb": round(p.stat().st_size / (1024 * 1024), 2) if p.exists() else 0.0,
        "version": VERSION,
    }


def _package_tree():
    index = PACKAGE_DIR / "laws_decrees_index.csv"
    if not index.exists():
        return [("لم تولَّد الحزمة بعد — اضغط «توليد الحزمة» ◀", True)]
    rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
    mds = list((PACKAGE_DIR / "markdown").glob("*.md"))
    js = list((PACKAGE_DIR / "markdown").glob("*.json"))
    return [
        (f"{PACKAGE_DIR.name}/", True),
        (f"+-- laws_decrees_index.csv    ({len(rows)} صفاً — أعمدة ميزان حرفياً)", False),
        (f"+-- markdown/                 ({len(mds)} ملف md)", False),
        (f"`-- markdown/                 ({len(js)} ملف JSON — عقد المادة)", False),
    ]




# ═════════════════════════ المصادر والسياسة (دفعة 5) ════════════════════════
SOURCE_FILTERS = {"الكل": "", "معلّق للاعتماد": "proposed",
                  "معتمد": "approved", "مرفوض": "rejected"}


def source_rows(status: str = "", needle: str = "") -> list[dict]:
    """صفوف سجل المصادر + عدد وثائق كل مصدر — للعرض والقرار معاً.

    القراءة من `sources` مباشرة (الحالة والجدارة والتير) + عدّ وثائق من
    `documents.source_url` تحت نطاق المصدر. القرار نفسه يُترك لدوال
    `decide_sources` أدناه التي تندب `discovery.decide_source` — نفس ما
    يستدعيه `cli sources`، لا نسخة ثانية منه.
    """
    conn = _connect()
    if conn is None or not _has_table(conn, "sources"):
        conn and conn.close()
        return []
    has_docs = _has_table(conn, "documents")
    sql = ("SELECT id, source_key, base_url, name, engine, credibility, status,"
           " domain_tier, discovered_via, decided_by, rejection_count"
           " FROM sources")
    cond, params = [], []
    if status:
        cond.append("status = ?"); params.append(status)
    if needle:
        cond.append("(name LIKE ? OR base_url LIKE ?)")
        params += [f"%{needle}%", f"%{needle}%"]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY CASE status WHEN 'proposed' THEN 0 ELSE 1 END, id"
    rows = [dict(r) for r in conn.execute(sql, params)]
    for r in rows:
        r["docs"] = 0
        if has_docs and r.get("base_url"):
            r["docs"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE source_url LIKE ?",
                (r["base_url"] + "%",)).fetchone()[0]
    conn.close()
    return rows


def sources_stats() -> dict:
    """عدّ لكل حالة — يدفّ «زرّ الاعتماد» على رقم، لا على إحساس."""
    conn = _connect()
    out = {"total": 0, "proposed": 0, "approved": 0, "rejected": 0}
    if conn is None or not _has_table(conn, "sources"):
        conn and conn.close()
        return out
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM sources "
                          "GROUP BY status"):
        out[r["status"]] = r["n"]
    out["total"] = sum(v for k, v in out.items() if k != "total")
    conn.close()
    return out


def decide_sources(ids: list[int], approve: bool, *, decided_by: str = "ui") -> dict:
    """اعتماد/رفض مصادر محددة — عبر `discovery.decide_source` نفسها (الـCLI).

    قرار مصدر ليس تجميل حالة صف: هو ما يفتح الباب للزحف منه أو يغلقه، لذا
    السطر الواحد المكتوب هنا هو سطر `cli sources approve 3` حرفياً.
    """
    if not ids:
        return {"changed": 0, "error": "لم تُحدَّد أي مصدر"}
    conn = _connect()
    if conn is None:
        return {"changed": 0, "error": "لا قاعدة بيانات"}
    changed, missing = 0, []
    try:
        from discovery import decide_source
        for i in ids:
            row = conn.execute("SELECT source_key FROM sources WHERE id = ?",
                               (int(i),)).fetchone()
            if row is None:
                missing.append(i)
                continue
            decide_source(conn, row["source_key"], approve, decided_by)
            changed += 1
    except Exception as exc:  # noqa: BLE001 — الشاشة تعرض، لا تنهار
        conn.close()
        return {"changed": changed, "error": f"{type(exc).__name__}: {exc}"}
    conn.close()
    return {"changed": changed, "missing": missing}


def queue_counts() -> dict:
    """حالة الطابور رقماً: كم فاشل/محجوب/بمراجعة/منتظر — للزرّ وللمعاينة."""
    conn = _connect()
    out = {"failed": 0, "blocked": 0, "needs_review": 0, "queued": 0,
           "success": 0, "total": 0}
    if conn is None or not _has_table(conn, "crawl_tasks"):
        conn and conn.close()
        return out
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM crawl_tasks "
                          "GROUP BY status"):
        out[r["status"]] = r["n"]
        out["total"] += r["n"]
    conn.close()
    return out


def requeue_failed(statuses=("failed", "blocked"), contains: str | None = None,
                   limit: int | None = None) -> dict:
    """إعادة مهام فاشلة إلى الطابور — عبر دوال `crawl_queue` نفسها (الـCLI).

    بلا `limit` تُعاد كل المطابقة (سلوك `cli requeue`)؛ ومع `limit` تُعاد
    الأولى فقط (id تصاعدياً) — لأن «8٬50١ مهمة فاشلة» بقاعدة المالك قرار
    لا يُتخذ بخطأ إدخال. المعاينة أولاً: `preview_requeue` تعدّ ولا تكتب.
    """
    statuses = [x for x in statuses if x]
    conn = _connect()
    if conn is None or not _has_table(conn, "crawl_tasks") or not statuses:
        conn and conn.close()
        return {"revived": 0, "error": "لا قاعدة/لا طابور/لا حالة مختارة"}
    where = "status IN (" + ",".join("?" * len(statuses)) + ")"
    params: list = list(statuses)
    if contains:
        where += " AND url LIKE ?"
        params.append(f"%{contains}%")
    if limit is not None:
        ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM crawl_tasks WHERE {where} ORDER BY id LIMIT ?",
            [*params, int(limit)]).fetchall()]
        from crawl_queue import requeue as _one
        for tid in ids:
            _one(conn, tid)
        result = {"revived": len(ids), "limited_to": int(limit)}
    else:
        from crawl_queue import requeue_by
        result = {"revived": len(requeue_by(conn, statuses, contains=contains))}
    conn.close()
    result.update({"statuses": statuses, "contains": contains or ""})
    return result


def preview_requeue(statuses=("failed", "blocked"),
                    contains: str | None = None) -> dict:
    """كم مهمة ستعود، لكل حالة — عدّ لا كتابة (لا ادعاء بلا قياس)."""
    conn = _connect()
    out = {"total": 0, "by_status": {}, "contains": contains or ""}
    if conn is None or not _has_table(conn, "crawl_tasks"):
        conn and conn.close()
        return out
    statuses = [x for x in statuses if x]
    if not statuses:
        conn.close()
        return out
    params: list = list(statuses)
    sql = ("SELECT status, COUNT(*) AS n FROM crawl_tasks WHERE status IN ("
           + ",".join("?" * len(statuses)) + ")")
    if contains:
        sql += " AND url LIKE ?"
        params.append(f"%{contains}%")
    for r in conn.execute(sql + " GROUP BY status", params):
        out["by_status"][r["status"]] = r["n"]
        out["total"] += r["n"]
    conn.close()
    return out


_LIVE = {
    "SOURCE_NAME": lambda: next(
        (f'{s["base_url"]} — {s["name"] or ""}'.strip(" —")
         for s in _sources() if s["status"] == "approved"), DEFAULT_SOURCE),
    "SOURCE_CREDIBILITY": lambda: next(
        (s["credibility"] or DEFAULT_CREDIBILITY
         for s in _sources() if s["status"] == "approved"),
        DEFAULT_CREDIBILITY),
    "SECTIONS": _sections,
    "LOG_EVENTS": _log_events,
    "DOCUMENTS": _documents,
    "DISCOVERY_RESULTS": _discovery_rows,
    "APPROVED_SOURCES": _approved_sources,
    "PACKAGE_TREE": _package_tree,
    "VALIDATION_CHECKS": validate_package,
    "RUN_STATS": _run_stats,
    "GAP_REPORT": _gap_report,
    "GAP_QUERIES": _gap_queries,
    "SOURCE_PERFORMANCE": _source_performance,
    "DEDUP_STATS": _dedup_stats,
    "DB_INFO": _db_info,
    "PACKAGE_COUNTS": lambda: package_counts(),
    "RUN_HISTORY": lambda: run_history(),
    "FAILURE_BREAKDOWN": lambda: failure_breakdown(),
    "REJECTION_STATS": lambda: rejection_stats(),
    "CORPUS_PROFILE": lambda: identity_and_status_stats(),
    "SOURCE_ROWS": lambda: source_rows(),
    "SOURCES_STATS": lambda: sources_stats(),
    "QUEUE_COUNTS": lambda: queue_counts(),
}


def __getattr__(name):
    """PEP 562 — كل وصول يقرأ الحالة الحقيقية وقتها (لا تخزين مؤقت)."""
    if name in _LIVE:
        return _LIVE[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
