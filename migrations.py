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


MIGRATIONS = [
    (1, "sha256 fingerprints + snapshot link", _migration_001_sha256),
    (2, "chunks + FTS5 arabic text index", _migration_002_chunks_fts),
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
