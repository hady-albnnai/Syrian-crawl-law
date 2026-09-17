# -*- coding: utf-8 -*-
"""package_manifest.py — عقد المواد لحزمة ميزان (دفعة «عقد المواد الكامل»).

لماذا؟ الحزمة القديمة كانت تحمل فهرس 14 عموداً + ملفات md، فترى ميزان
«مؤشراً على ملف» لا متنـاً: لا جدول مواد، ولا حالة قانونية، ولا هوية.
قياس 2026-09-17: 16,930 مادة محصودة ولا صَفْر مواد يصل إلى ميزان.

ما تبنيه هذه الوحدة (بلا كسر للوراء — الفهرس يبقى 14 عموداً كما يقرؤه
`csv_legal_library_importer.dart`):

  mizan_package_manifest.json   ← عقد الحزمة الآلي، حاملة الأرقام والـsha256
  markdown/<stem>.json          ← عقد الوثيقة (موسّع الآن: الحالة القانونية،
                                   سلسلة التعديل، طبقة الرسمية، الهوية)

الأرقام كلها مأخوذة **من الحزمة بعد كتابتها** (بصمة على القرص)، لا من
القاعدة — وإلا كان المانيفست يكذب عند أي انحدار في التصدير.
"""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from logging_setup import get_log

log = get_log(__name__)

SCHEMA_VERSION = "2"
MANIFEST_NAME = "mizan_package_manifest.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _amendment_maps(conn) -> tuple[dict, dict]:
    """خرائط سلسلة التعديل لوثائق الحزمة (ف١ — law_amendments).

    يعيد (out_by_doc, in_by_identity):
      out_by_doc[doc_row_id]  : إحالات هذه الوثيقة (تعديل/إلغاء صكوكاً أخرى)
      in_by_identity[identity]: الوثائق التي تستهدف صكّاً بهويته (ما عُدِّل/أُلغي به)
    """
    out_by_doc, in_by_identity = {}, {}
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "law_amendments" not in tables:
        return out_by_doc, in_by_identity
    for r in conn.execute("""
        SELECT la.amending_doc_id AS doc, la.action, la.target_identity,
               la.context, d.title AS amender, d.number AS number,
               d.year AS year
        FROM law_amendments la JOIN documents d ON d.id = la.amending_doc_id
        ORDER BY COALESCE(d.year, 0), la.id"""):
        out_by_doc.setdefault(r["doc"], []).append({
            "action": r["action"], "target_identity": r["target_identity"],
            "amender": r["amender"], "amender_number": r["number"],
            "amender_year": r["year"],
            "context": (r["context"] or "")[:240]})
    # المعكوس: من يستهدف هوية هذه الوثيقة ⇒ هي المعدَّلة/الملغاة به
    for r in conn.execute("""
        SELECT la.target_identity AS ident, la.action, d.title AS amender,
               d.number AS number, d.year AS year
        FROM law_amendments la JOIN documents d ON d.id = la.amending_doc_id
        ORDER BY COALESCE(d.year, 0), la.id"""):
        in_by_identity.setdefault(r["ident"], []).append({
            "action": r["action"], "amender": r["amender"],
            "amender_number": r["number"], "amender_year": r["year"]})
    return out_by_doc, in_by_identity


def enrich_doc_json(package_dir: Path, db_path, docs_index: list[dict]) -> dict:
    """يكتب في كل JSON جانبي الحقول الغنية (الحالة/السلسلة/الهوية/الطبقة).

    docs_index: صفوف الفهرس بعد توليدها. نطابق كل صَفْر على ملفه ثم نوسّع
    الـJSON من القاعدة — الفهرس نفسه لا يُمسّ (عقد 14 عموداً محفوظ).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out_by_doc, in_by_ident = _amendment_maps(conn)
    touched = 0
    for r in docs_index:
        md = package_dir / Path(r["local_path"]).parent.name / Path(r["local_path"]).name
        js = md.with_suffix(".json")
        if not js.exists():
            continue
        try:
            data = json.loads(js.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        doc_url = data.get("source_url") or ""
        row = conn.execute(
            "SELECT id, identity_key, identity_confidence, legal_status,"
            " review_status, status, source_domain_tier, quality_score,"
            " is_complete_text, branch, doc_type, number, year,"
            " content_sha256, snapshot_sha256 FROM documents WHERE source_url = ?",
            (doc_url,)).fetchone()
        if row is None:
            continue
        data["schema_version"] = SCHEMA_VERSION
        data["identity_key"] = row["identity_key"]
        data["identity_confidence"] = row["identity_confidence"]
        data["legal_status"] = row["legal_status"]
        data["review_status"] = row["review_status"]
        data["document_status"] = row["status"]
        data["domain_tier"] = row["source_domain_tier"]
        data["quality_score"] = row["quality_score"]
        data["is_complete_text"] = bool(row["is_complete_text"])
        data["branch_key"] = row["branch"]
        data["document_type"] = row["doc_type"]
        data["amends"] = out_by_doc.get(row["id"], [])
        data["amended_by_docs"] = (in_by_ident.get(row["identity_key"], [])
                                   if row["identity_key"] else [])
        # لكل مادة: بصمة نصها (يستطيع ميزان أن يطمئن عليها عند البناء)
        for a in data.get("articles", []):
            txt = a.get("text") or ""
            a["text_sha256"] = hashlib.sha256(txt.encode("utf-8")).hexdigest()
        js.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        touched += 1
    conn.close()
    return {"enriched": touched, "amendments_out": sum(len(v) for v in out_by_doc.values())}


def build_manifest(db_path, package_dir, corpus_stats: dict | None = None) -> dict:
    """يكتب mizan_package_manifest.json من الحزمة على القرص، ويعيد المانيفست."""
    package_dir = Path(package_dir)
    index = package_dir / "laws_decrees_index.csv"
    if not index.exists():
        raise FileNotFoundError(f"لا فهرس في {package_dir} — ولِّد الحزمة أولاً")
    rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
    files, n_articles, n_docs = [], 0, 0
    for r in rows:
        rel = r["local_path"]
        md = package_dir / Path(rel).parent.name / Path(rel).name
        js = md.with_suffix(".json")
        if not md.exists():
            continue
        n_docs += 1
        files.append({"id": r["id"], "title": r["title"],
                      "markdown": f"{Path(rel).parent.name}/{md.name}",
                      "markdown_sha256": _sha256_file(md),
                      "size_bytes": md.stat().st_size,
                      "json": (f"{Path(rel).parent.name}/{js.name}"
                               if js.exists() else None),
                      "json_sha256": (_sha256_file(js) if js.exists() else None),
                      "category": r["category"], "type": r["type"],
                      "number": r["number"], "year": r["year"],
                      "url": r["url"], "format": r["format"],
                      "priority": r["priority"], "status": r["status"]})
    for f in files:
        jp = package_dir / (f.get("json") or "")
        if f.get("json") and jp.exists():
            try:
                n_articles += len(json.loads(jp.read_text(encoding="utf-8")).get("articles", []))
            except (ValueError, OSError):
                pass
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "producer": "mizan-harvester",
        "index": {"file": "laws_decrees_index.csv",
                  "columns": list(rows[0].keys()) if rows else [],
                  "sha256": _sha256_file(index),
                  "rows": len(rows)},
        "corpus": {"documents": n_docs, "articles": n_articles,
                   **(corpus_stats or {})},
        "index_bom": index.read_bytes().startswith(b"\xef\xbb\xbf"),
        "index_line_endings": ("crlf" if b"\r\n" in index.read_bytes() else "lf"),
        "files": files,
    }
    (package_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"مانيفست الحزمة: {n_docs} وثيقة | {n_articles} مادة | "
             f"{len(files)} ملف → {package_dir / MANIFEST_NAME}")
    return manifest
