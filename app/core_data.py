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
    if conn is None:
        return []
    rows = conn.execute("""
        SELECT d.id, d.title, d.doc_type, d.branch, d.year, d.legal_score,
               d.review_status, d.status, d.source_url,
               (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.id)
                   AS n_articles
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


def document_text(doc_id: int) -> str:
    """نص وثيقة كاملاً (clean_content) لمعاينة المراجعة — قراءة مباشرة
    بمعرّف الوثيقة، لا كل الأعمدة الثقيلة ضمن _documents() الافتراضية."""
    conn = _connect()
    if conn is None:
        return ""
    row = conn.execute(
        "SELECT clean_content FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return (row["clean_content"] if row else "") or ""


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
           "docs": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
           "articles": conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]}
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
    """بوابة تحقق حقيقية على الحزمة المصدَّرة (لا قيم ثابتة)."""
    # القراءة وقت النداء لا وقت التعريف — حتى يعمل الاختبار مع PACKAGE_DIR مُبدَّل
    pkg_dir = Path(pkg_dir) if pkg_dir else PACKAGE_DIR
    checks = []
    index = pkg_dir / "laws_decrees_index.csv"
    if not index.exists():
        return [("الحزمة غير مولَّدة بعد — اضغط «توليد الحزمة»", False)]
    rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
    ids = [r["id"] for r in rows]
    sha_ok = size_ok = True
    for r in rows:
        f = Path(pkg_dir) / "markdown" / r["local_path"].split("/")[-1]
        if not f.exists():
            sha_ok = size_ok = False
            continue
        b = f.read_bytes()
        sha_ok &= hashlib.sha256(b).hexdigest() == r["sha256"]
        size_ok &= str(len(b)) == r["size_bytes"]
    checks.append((f"sha256 مطابقة لكل ملفات الحزمة ({len(rows)})", sha_ok))
    checks.append(("size_bytes مطابقة لكل ملف", size_ok))
    checks.append(("لا id مكرر ولا عنوان فارغ",
                   len(ids) == len(set(ids))
                   and all(r["title"].strip() for r in rows)))
    checks.append(("الفهرس يُقرأ بأعمدة ميزان (UTF-8+BOM)",
                   open(index, "rb").read(3) == b"\xef\xbb\xbf"))
    return checks


def _gap_report():
    """تحليل فجوات فروع القانون (gap_analysis.py، §7) — حية من القاعدة،
    لا جدول مُخمَّن. تعيد قائمة مرتبة: الفجوات أولاً (الأكثر نقصاً أعلى)."""
    from config import BRANCH_AR
    conn = _connect()
    if conn is None:
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
    if conn is None:
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
}


def __getattr__(name):
    """PEP 562 — كل وصول يقرأ الحالة الحقيقية وقتها (لا تخزين مؤقت)."""
    if name in _LIVE:
        return _LIVE[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
