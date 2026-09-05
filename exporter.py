"""exporter.py — توليد «حزمة محتوى» مطابقة لعقد ميزان (ADR-001، التسليم 4).

العقد مُثبت من `lawyer-office2/content/legal_library/laws_decrees/laws_decrees_index.csv`:
- 14 عموداً بترتيب ثابت، الملف بترميز UTF-8 مع BOM.
- ملفات النصوص markdown/ باسم `{year}_{title}_{number}.md`.
- sha256 = بصمة **الملف المصدري** (bytes) كما في حزمة ميزان — عندنا هو
  لقطة HTML الخام إن وُجدت، وإلا بصمة ملف md نفسه (موثق في التقرير).

قرار المالك 2026-09-05: md + JSON — لذا يُكتب بجانب كل md ملف JSON
بالعقد الغني للمواد (رقم/لفظية/نص/فقرات/مسار هرمي) للاستهلاك الآلي.
"""
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from config import DB_PATH
from logging_setup import get_log

log = get_log(__name__)

COLUMNS = ["id", "title", "type", "number", "year", "date", "category",
           "url", "format", "priority", "status", "local_path",
           "size_bytes", "sha256"]
DEFAULT_PREFIX = "content/legal_library/laws_decrees/"
# مفاتيح detect_branch ⇒ تسميات ميزان العربية (فئات الفهرس عربية كلها)
BRANCH_AR = {
    "civil_law": "مدني",
    "penal_law": "جزائي",
    "procedural_law": "أصول ومحاكمات",
    "personal_status": "أحوال شخصية",
    "commercial_law": "تجاري",
    "constitutional": "دستوري",
    "administrative": "إداري",
}
SNAPSHOT_DIR = Path("data/snapshots")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(title: str) -> str:
    """اسم ملف آمن على Windows وLinux معاً (ميزان تطبيق Windows)."""
    name = _UNSAFE.sub("", (title or "بدون_عنوان").strip())
    name = re.sub(r"\s+", "_", name)
    return name[:120] or "بدون_عنوان"


def _priority_for(credibility) -> int:
    try:
        c = float(credibility or 0.6)
    except (TypeError, ValueError):
        c = 0.6
    return 1 if c >= 0.7 else (2 if c >= 0.5 else 3)


def doc_markdown(doc, articles) -> str:
    lines = [f"# {doc['title'] or 'بدون عنوان'}", ""]
    meta = []
    if doc["number"]:
        meta.append(f"الرقم: {doc['number']}")
    if doc["year"]:
        meta.append(f"السنة: {doc['year']}")
    if doc["branch"]:
        meta.append(f"الفرع: {BRANCH_AR.get(doc['branch'], doc['branch'])}")
    meta.append(f"المصدر: {doc['source_url']}")
    lines.append("> " + " — ".join(meta))
    lines.append("")
    for a in articles:
        label = a["article_label"] or ""
        if label.isdigit():  # لفظية رقمية فقط («1») — تُستكمل للعرض
            label = f"المادة {label}"
        if not label:
            label = (f"المادة {a['article_number']}"
                     if a["article_number"] else "مادة")
        lines.append(f"## {label}")
        lines.append("")
        paras = json.loads(a["paragraphs_json"]) if a["paragraphs_json"] else None
        if paras:
            for para in paras:
                lines.append(para)
                lines.append("")
        else:
            lines.append(a["text"] or "")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def doc_json(doc, articles) -> dict:
    return {
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "number": doc["number"],
        "year": doc["year"],
        "branch": doc["branch"],
        "source_url": doc["source_url"],
        "content_sha256": doc["content_sha256"],
        "snapshot_sha256": doc["snapshot_sha256"],
        "articles": [{
            "number": a["article_number"],
            "label": a["article_label"],
            "text": a["text"],
            "hierarchy_path": a["hierarchy_path"],
            "paragraphs": json.loads(a["paragraphs_json"])
                          if a["paragraphs_json"] else None,
            "amended_by": a["amended_by"],
        } for a in articles],
    }


def build_package(db_path=DB_PATH, out_dir="export/content_package",
                  prefix=DEFAULT_PREFIX, min_articles=0) -> dict:
    """يبني الحزمة كاملة ويعيد إحصاءات للتقرير."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    docs = conn.execute(
        "SELECT * FROM documents WHERE status = 'active' "
        "ORDER BY year, number, id").fetchall()
    out = Path(out_dir)
    (out / "markdown").mkdir(parents=True, exist_ok=True)
    used_ids, rows, skipped = set(), [], 0
    for doc in docs:
        articles = conn.execute(
            "SELECT * FROM articles WHERE doc_id = ? ORDER BY id",
            (doc["id"],)).fetchall()
        if len(articles) < min_articles:
            skipped += 1
            continue
        stem = "_".join(x for x in [
            str(doc["year"]) if doc["year"] else None,
            sanitize_filename(doc["title"]),
            str(doc["number"]) if doc["number"] else None,
        ] if x)
        md_path = out / "markdown" / f"{stem}.md"
        js_path = out / "markdown" / f"{stem}.json"
        md_bytes = doc_markdown(doc, articles).encode("utf-8")
        md_path.write_bytes(md_bytes)
        js_path.write_text(json.dumps(doc_json(doc, articles),
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
        # sha256 = بصمة الملف المصدري: اللقطة الخام إن وُجدت، وإلا md نفسه
        snap = doc["snapshot_sha256"]
        snap_file = (SNAPSHOT_DIR / (snap.split(":")[-1] + ".html")
                     if snap else None)
        if snap_file and snap_file.exists():
            sha = hashlib.sha256(snap_file.read_bytes()).hexdigest()
        else:
            sha = hashlib.sha256(md_bytes).hexdigest()
        doc_id = (f"law_{doc['year']}_{doc['number']}"
                  if doc["year"] and doc["number"]
                  else "doc_" + (doc["content_sha256"] or
                                 hashlib.sha256(
                                     (doc["doc_id"] or stem).encode()
                                 ).hexdigest())[:8])
        base_id, n = doc_id, 2
        while doc_id in used_ids:
            doc_id = f"{base_id}_{n}"
            n += 1
        used_ids.add(doc_id)
        rows.append({
            "id": doc_id,
            "title": doc["title"] or "",
            "type": "قانون" if (doc["doc_type"] or "") == "law"
                    else (doc["doc_type"] or ""),
            "number": doc["number"] if doc["number"] is not None else "",
            "year": doc["year"] if doc["year"] is not None else "",
            "date": "",  # تاريخ الإصدار غير معروف من المنتدى — لا يُختلق
            "category": BRANCH_AR.get(doc["branch"],
                                       doc["branch"] or "غير مصنف"),
            "url": doc["source_url"] or "",
            "format": "html",
            "priority": _priority_for(doc["source_credibility"]),
            "status": "crawled",
            "local_path": f"{prefix}markdown/{stem}.md",
            "size_bytes": len(md_bytes),
            "sha256": sha,
        })
    conn.close()
    csv_path = out / "laws_decrees_index.csv"
    # fاصله الأسطر LF حصراً — فهرس ميزان LF-only (مثبت بالفحص، لا CRLF)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    log.info(f"حزمة المحتوى: {len(rows)} وثيقة في {out} ({skipped} تخطي)")
    return {"docs": len(rows), "skipped": skipped,
            "csv": str(csv_path), "out_dir": str(out)}
