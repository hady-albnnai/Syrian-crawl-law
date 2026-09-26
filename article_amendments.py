# -*- coding: utf-8 -*-
"""
article_amendments.py — تصدير تعديلات المواد بعينها لميزان (ذ19).

الاستخراج والتسجيل موجودان أصلاً في `article_links.py` (A-4): جدول
`article_amendments` بأعمدة (amending_doc_id, target_identity,
article_number, action, context) وإسقاطه على `articles.amended_by`.
هذه الوحدة لا تعيد الاستخراج ولا تنشئ جدولاً موازياً؛ تقرأ جدول A-4
وتصدّره في `article_amendments.csv` مع ما ينقص ميزان عن JSON الحزمة:
سياق العبارة، وهوية الصك المعدِّل وتاريخه ومصدره.

حدود صريحة: «نافذة» في ميزان تعني «لا تعديل ولا إلغاء لهذه المادة بالمتن
المتوفر» — ويقولها ميزان بهذه الصيغة. لا تخمين.
"""
import csv
from pathlib import Path

from article_links import extract_article_amendments, rebuild_article_links  # noqa: F401 — الواجهة الواحدة


def ensure_table(conn) -> None:
    """الجدول بعقد A-4 نفسه إن لم يكن موجوداً (قواعد قديمة)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS article_amendments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amending_doc_id INTEGER NOT NULL,
        target_identity TEXT NOT NULL,
        article_number TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('amend','repeal')),
        context TEXT, created_at TEXT,
        UNIQUE (amending_doc_id, target_identity, article_number, action))""")


def rebuild(conn) -> dict:
    """إعادة البناء = A-4 نفسه (article-links)."""
    return rebuild_article_links(conn)


CSV_COLUMNS = ["target_identity", "target_type", "target_number", "target_year", "article", "action",
               "amending_identity", "amending_title", "amending_year", "amending_date",
               "context", "source_url"]


def export_rows(conn) -> list[dict]:
    ensure_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    date_col = "d.issue_date" if "issue_date" in cols else "NULL"
    q = f"""SELECT a.target_identity, a.article_number, a.action, a.context,
                   d.identity_key, d.title, d.year, {date_col}, d.source_url
            FROM article_amendments a JOIN documents d ON d.id = a.amending_doc_id
            ORDER BY a.target_identity, CAST(a.article_number AS INTEGER), d.year, d.id"""
    out = []
    for r in conn.execute(q).fetchall():
        parts = (r[0] or "").split(":")
        ttype, tnum, tyear = (parts + ["", "", ""])[:3]
        out.append({
            "target_identity": r[0], "target_type": ttype, "target_number": tnum, "target_year": tyear,
            "article": r[1], "action": r[2], "amending_identity": r[4] or "", "amending_title": r[5] or "",
            "amending_year": r[6] or "", "amending_date": r[7] or "",
            "context": (r[3] or "").replace("\n", " "), "source_url": r[8] or "",
        })
    return out


def export_csv(conn, out_path) -> dict:
    rows = export_rows(conn)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return {"count": len(rows), "path": str(p),
            "repeal": sum(r["action"] == "repeal" for r in rows),
            "amend": sum(r["action"] == "amend" for r in rows)}
