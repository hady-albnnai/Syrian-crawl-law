"""migrations.py — هجرة مخططة بإصدارات لقاعدة البيانات (التسليم 4).

القرارات المطبقة هنا (ADR-001 + إعادة تأطيره):
- sha256 هي البصمة القانونية المعتمدة؛ عمود md5 التاريخي (content_hash) يبقى
  للمطابقة مع القواعد القديمة ولا تُكتب عليه اعتمادات جديدة.
- كل هجرة إضافة فقط (additive) — لا حذف ولا تعديل أعمدة قائمة — حتى يكون
  التراجع آمناً: نسخة احتياطية قبل التطبيق + استعادتها تكفي.
"""
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from config import DB_PATH
from logging_setup import get_log

log = get_log(__name__)

BACKUP_DIR = Path("data/backups")


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _migration_001_sha256(cursor) -> dict:
    """إضافة بصمات sha256 وربط اللقطات الخام.

    - content_sha256: بصمة النص النظيف (بديل content_hash/md5 going forward).
    - snapshot_sha256: بصمة HTML الخام المخزّن في data/snapshots (يملأه
      الزاحف للوثائق الجديدة؛ التاريخيات تُترك فارغة لأن HTML لم يُحفظ لها).
    """
    stats = {"backfilled": 0, "empty": 0}
    cursor.execute("ALTER TABLE documents ADD COLUMN content_sha256 TEXT")
    cursor.execute("ALTER TABLE documents ADD COLUMN snapshot_sha256 TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_content_sha256 "
                   "ON documents(content_sha256)")
    rows = cursor.execute(
        "SELECT id, clean_content, raw_content FROM documents").fetchall()
    for row in rows:
        text = row[1] or row[2]
        if text:
            cursor.execute(
                "UPDATE documents SET content_sha256 = ? WHERE id = ?",
                (_sha256_text(text), row[0]))
            stats["backfilled"] += 1
        else:
            stats["empty"] += 1
    return stats


def _migration_002_chunks_fts(cursor) -> dict:
    """جدول chunks للفهرسة النصية + FTS5 بتقسيم unicode61 (يحترم العربية)."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER, article_id INTEGER, seq INTEGER,
            number TEXT, label TEXT, hierarchy_path TEXT,
            text TEXT, char_count INTEGER,
            source_url TEXT, doc_title TEXT
        )''')
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, content='chunks', content_rowid='id',
            tokenize='unicode61')""")
    n = cursor.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"chunks_existing": n}


def _migration_003_sources_decided_by(cursor) -> dict:
    """من قرّر اعتماد/رفض المصدر: 'user' أم الطيار الآلي 'auto'.

    إضافة فقط (قاعدة الهجرات) — القيم التاريخية تبقى NULL وتُقرأ «غير مسجل».
    قواعد أقدم من جدول sources تُبنى بالجداول كاملة (CREATE IF NOT EXISTS)
    ثم يُضاف العمود لمن يملك الجدول بدونه — idempotent في الحالتين.
    """
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_key TEXT UNIQUE,
        base_url TEXT UNIQUE,
        name TEXT,
        engine TEXT,
        credibility REAL DEFAULT 0.6,
        status TEXT DEFAULT 'proposed',
        discovered_via TEXT,
        discovered_at TEXT,
        decided_at TEXT,
        decided_by TEXT
    )
    ''')
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(sources)")]
    added = 0
    if "decided_by" not in cols:
        cursor.execute("ALTER TABLE sources ADD COLUMN decided_by TEXT")
        added = 1
    n = cursor.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    return {"sources_rows": n, "column_added": added}


def _add_column_if_missing(cursor, table, column, decl) -> int:
    """يضيف عموداً فقط إن لم يكن موجوداً — idempotent، بلا خطأ عند التكرار.

    قواعد تاريخية جداً (fixtures اختبار قديمة أو قواعد جزئية) قد لا تملك
    الجدول نفسه بعد (مثال: crawl_runs لم يكن موجوداً قبل التسليم 3) — في
    هذه الحالة لا شيء لإضافته، والتجاهل هنا آمن: create_tables تُنشئ
    الجدول لاحقاً بمخططه الكامل مباشرة عند أول استخدام فعلي."""
    tables = [r[0] for r in cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,))]
    if not tables:
        return 0
    cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table})")]
    if column in cols:
        return 0
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    return 1


def _migration_004_self_discovery(cursor) -> dict:
    """يضيف مخطط الاكتشاف الذاتي للمصادر (DELIVERY/DESIGN-SELF-DISCOVERY.md):

    - documents: identity_key/identity_confidence (هوية القانون نوع+رقم+
      سنة، §2)، is_complete_text (اكتمال النص، §4.2.2)، source_domain_tier
      (فئة رسمية المصدر منسوخة وقت الحفظ، §4.2.1)، quality_score (كانت
      تُحسب فعلياً بـ extract_main_content ولا تُحفظ أبداً — تُخزَّن الآن
      لاستخدامها كمعيار ثالث بالمقارنة عند تعادل الفئة والاكتمال).
    - sources.domain_tier: فئة الرسمية لكل مصدر (0=أعلى رسمية..4=منتدى عام).
    - document_versions: نسخ الوثائق المستبدلة — نسخ لا حذف (§4.2).
    - dedup_decisions: سجل تدقيق لكل قرار تنقيح بين نسختين (§4.2).
    - source_performance: تعلّم بسيط شفاف من أداء كل مصدر عبر الدورات (§5.2).

    كل ما هنا إضافي بحت (أعمدة/جداول جديدة) — لا حذف ولا تعديل لعمود قائم،
    التزاماً بقاعدة الهجرات الإضافية في CONSTITUTION.md.
    """
    added = 0
    added += _add_column_if_missing(cursor, "documents", "identity_key", "TEXT")
    added += _add_column_if_missing(cursor, "documents", "identity_confidence", "TEXT")
    added += _add_column_if_missing(cursor, "documents", "is_complete_text", "INTEGER")
    added += _add_column_if_missing(cursor, "documents", "source_domain_tier", "INTEGER")
    added += _add_column_if_missing(cursor, "documents", "quality_score", "REAL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_identity "
                   "ON documents(identity_key)")

    added += _add_column_if_missing(cursor, "sources", "domain_tier",
                                    "INTEGER DEFAULT 4")
    added += _add_column_if_missing(cursor, "crawl_runs",
                                    "branch_breakdown_json", "TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_doc_id INTEGER,
            doc_id TEXT, title TEXT, source_url TEXT,
            clean_content TEXT, quality_score REAL,
            superseded_at TEXT, superseded_reason TEXT,
            FOREIGN KEY (original_doc_id) REFERENCES documents(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dedup_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_key TEXT,
            winner_doc_id INTEGER, loser_doc_id INTEGER,
            decisive_criterion TEXT,
            winner_value REAL, loser_value REAL,
            decided_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_performance (
            source_key TEXT PRIMARY KEY,
            runs_count INTEGER DEFAULT 0,
            new_identities_total INTEGER DEFAULT 0,
            last_run_new_identities INTEGER DEFAULT 0,
            consecutive_empty_runs INTEGER DEFAULT 0,
            last_evaluated_at TEXT,
            learned_status TEXT DEFAULT 'active'
        )
    ''')
    return {"columns_added": added}


def _migration_005_rejection_feedback(cursor) -> dict:
    """سبب رفض صريح عند المراجعة البشرية (طلب المالك 2026-09-06): «حتى
    يتعلّم الزاحف للمرات القادمة». سجل تدقيق كامل (من رفض ماذا ولماذا)
    + عمود تنازلي بسيط على sources يُقرأ عند البذر القادم (learning.py).

    - rejection_reasons: سجل كل رفض بشري (doc_id, source_key, الفئة، ملاحظة حرة).
    - sources.rejection_count: عدّاد تراكمي بسيط — يُستشار قبل البذر
      (نفس فكرة learned_status الحالية، بس مصدرها قرار بشري صريح لا
      عدّاد فارغ آلي). إضافي بحت، لا يمسّ learned_status الموجود أصلاً.
    """
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rejection_reasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER,
            source_key TEXT,
            category TEXT,
            note TEXT,
            rejected_at TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents(id)
        )
    ''')
    added = _add_column_if_missing(cursor, "sources", "rejection_count",
                                   "INTEGER DEFAULT 0")
    return {"table_created": True, "columns_added": added}


MIGRATIONS = [
    (1, "sha256 fingerprints + snapshot link", _migration_001_sha256),
    (2, "chunks + FTS5 arabic text index", _migration_002_chunks_fts),
    (3, "sources.decided_by (user vs autopilot)", _migration_003_sources_decided_by),
    (4, "self-discovery: identity_key + domain_tier + versions/dedup/perf",
     _migration_004_self_discovery),
    (5, "rejection_reasons + sources.rejection_count (learn from human review)",
     _migration_005_rejection_feedback),
]
LATEST = MIGRATIONS[-1][0]


def get_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def backup_db(db_path=DB_PATH) -> Path | None:
    p = Path(db_path)
    if not p.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / (p.stem + "_pre_mig_"
                         + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
    shutil.copy2(p, dest)
    return dest


def migrate(db_path=DB_PATH) -> dict:
    """يطبق كل الهجرات غير المطبقة. Idempotent وآمنة للتكرار."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report = {"start_version": get_version(conn), "applied": [], "backups": []}
    current = report["start_version"]
    pending = [(v, name, fn) for v, name, fn in MIGRATIONS if v > current]
    if not pending:
        report["end_version"] = current
        conn.close()
        return report
    backup = backup_db(db_path)
    if backup:
        report["backups"].append(str(backup))
    cursor = conn.cursor()
    try:
        for version, name, fn in pending:
            stats = fn(cursor)
            cursor.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            report["applied"].append(
                {"version": version, "name": name, **stats})
            log.info(f"هجرة {version} مطبقة: {name} — {stats}")
    except Exception:
        conn.rollback()
        conn.close()
        raise
    report["end_version"] = get_version(conn)
    conn.close()
    return report
