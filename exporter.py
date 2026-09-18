"""exporter.py — توليد «حزمة محتوى» مطابقة لعقد ميزان (ADR-001، التسليم 4).

العقد مُثبت من `lawyer-office2/content/legal_library/laws_decrees/laws_decrees_index.csv`:
- 14 عموداً بترتيب ثابت، الملف بترميز UTF-8 مع BOM.
- ملفات النصوص markdown/ باسم `{year}_{title}_{number}.md`.
- sha256 = بصمة **الملف المُصدَّر** (bytes) — أي ملف md المشار إليه في
  local_path، لأنه الملف الذي يفتحه المستورد في ميزان ويحمّصه
  (csv_legal_library_importer → planCsvImport). الدلالة القديمة كانت بصمة
  لقطة HTML الخام عند وجودها، فرفضت بوابةُ السلامة كل وثيقة مزحوفة
  «بصمة غير مطابقة» (قِيس 2026-09-17). بصمة اللقطة تبقى في JSON الجانبي
  (snapshot_sha256) لمن يريد الإسناد إلى الأصل الخام.

قرار المالك 2026-09-05: md + JSON — لذا يُكتب بجانب كل md ملف JSON
بالعقد الغني للمواد (رقم/لفظية/نص/فقرات/مسار هرمي) للاستهلاك الآلي.
"""
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from config import BRANCH_AR, DB_PATH  # مصدر حقيقة واحد لكل الـ14 فرعاً
from logging_setup import get_log

log = get_log(__name__)

COLUMNS = ["id", "title", "type", "number", "year", "date", "category",
           "url", "format", "priority", "status", "local_path",
           "size_bytes", "sha256"]
DEFAULT_PREFIX = "content/legal_library/laws_decrees/"
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
    lines = [f"# {_get(doc, 'title') or 'بدون عنوان'}", ""]
    meta = []
    if _get(doc, "number"):
        meta.append(f"الرقم: {doc['number']}")
    if _get(doc, "year"):
        meta.append(f"السنة: {doc['year']}")
    if _get(doc, "branch"):
        meta.append(f"الفرع: {BRANCH_AR.get(doc['branch'], doc['branch'])}")
    if _get(doc, "legal_status"):
        meta.append(f"الحالة القانونية: {doc['legal_status']}")
    meta.append(f"المصدر: {_get(doc, 'source_url') or ''}")
    lines.append("> " + " — ".join(meta))
    lines.append("")
    for a in articles:
        label = _get(a, "article_label") or ""
        if label.isdigit():  # لفظية رقمية فقط («1») — تُستكمل للعرض
            label = f"المادة {label}"
        if not label:
            label = (f"المادة {_get(a, 'article_number')}"
                     if _get(a, "article_number") else "مادة")
        lines.append(f"## {label}")
        lines.append("")
        pj = _get(a, "paragraphs_json")
        paras = json.loads(pj) if pj else None
        if paras:
            for para in paras:
                lines.append(para)
                lines.append("")
        else:
            lines.append(_get(a, "text") or "")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _get(row, key, default=None):
    """قيمة آمنة لعمود قد لا يوجد بمخطط قديم — sqlite3.Row لا يملك .get().

    عطل مقاس 2026-09-17: قاعدة بمخطط ما قبل ف١ (بلا amended_by) كانت تُسقط
    IndexError في منتصف التصدير وتموت الدورة كلها — نفس علة «SystemExit بـ
    pdf_to_text كان يقتل الدورة» الموثقة في دفتر التشغيل، وهي ممنوعة
    دستورياً (لا استثناء غير معالج في مسار حرج).
    """
    try:
        v = row[key]
    except (IndexError, KeyError):
        return default
    return default if v is None and default is not None else v


def doc_json(doc, articles) -> dict:
    return {
        "doc_id": _get(doc, "doc_id"),
        "title": _get(doc, "title"),
        "number": _get(doc, "number"),
        "year": _get(doc, "year"),
        "branch": _get(doc, "branch"),
        "source_url": _get(doc, "source_url"),
        "content_sha256": _get(doc, "content_sha256"),
        "snapshot_sha256": _get(doc, "snapshot_sha256"),
        "legal_status": _get(doc, "legal_status"),
        "review_status": _get(doc, "review_status", "auto_accepted"),
        "source_domain_tier": _get(doc, "source_domain_tier"),
        "quality_score": _get(doc, "quality_score"),
        "identity_key": _get(doc, "identity_key"),
        "articles": [{
            "number": _get(a, "article_number"),
            "label": _get(a, "article_label"),
            "text": _get(a, "text"),
            "hierarchy_path": _get(a, "hierarchy_path"),
            "paragraphs": json.loads(a["paragraphs_json"])
                          if _get(a, "paragraphs_json") else None,
            "amended_by": _get(a, "amended_by"),
        } for a in articles],
    }


def build_package(db_path=DB_PATH, out_dir="export/content_package",
                  prefix=DEFAULT_PREFIX, min_articles=0,
                  with_manifest: bool = True) -> dict:
    """يبني الحزمة كاملة ويعيد إحصاءات للتقرير.

    with_manifest=True (الافتراضي) يوسّع كل JSON جانبي بعقد المواد الغني
    (الحالة القانونية، سلسلة التعديل، طبقة الرسمية، بصمة كل مادة) ويكتب
    mizan_package_manifest.json، ثم يجتاز بوابة التحقق ذاتها التي يجتازها
    ميزان (verify_package). الإخفاق في التوسيع لا يُفشل التصدير: الحزمة
    تبقى صالحة للفهرس القديم، ويُبلَّغ السبب في إحصاءات التقرير.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    docs = conn.execute(
        "SELECT * FROM documents WHERE status = 'active' "
        "ORDER BY year, number, id").fetchall()
    out = Path(out_dir)
    (out / "markdown").mkdir(parents=True, exist_ok=True)
    used_ids, rows, skipped = set(), [], 0
    # stem → بايتات الملف المكتوب فعلاً. بدون هذا الحارس يكتب صفاً لنفس
    # الوثيقة نفس الاسم، ومن يكتب لاحقاً يدفن سابقه بصمت: الفهرس يبقى يحمل
    # بصمة وحجماً لملف لم يعد على القرص (قِيس على قاعدة المالك: بوابة حمراء
    # بـ«بصمة غير مطابقة» + «size_bytes مخالفة»).
    used_stems: set[str] = set()
    renamed = 0
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
        md_bytes = doc_markdown(doc, articles).encode("utf-8")
        # لا حذف «نسخة مطابقة» هنا: المتن يتضمّن «المصدر: <url>» و`documents
        # .source_url` مقيّد UNIQUE، فمستحيل أن يولّد صَفّان نفس البايتات — وأي
        # شقّ «دمج» would كان كوداً ميتاً يبيع حماية لا تعمل. التكرار الحقيقي
        # بنفس المصدر يُفصل عند الحفظ (save_document) لا هنا.
        base_stem, k = stem, 2
        while stem in used_stems:
            stem = f"{base_stem}_{k}"          # نفس الاسم ⇒ لاحقة، لا دفن
            k += 1
        if stem != base_stem:
            renamed += 1
        used_stems.add(stem)
        md_path = out / "markdown" / f"{stem}.md"
        js_path = out / "markdown" / f"{stem}.json"
        md_path.write_bytes(md_bytes)
        with open(js_path, "w", encoding="utf-8", newline="\n") as jf:
            # LF صريح: بايت الجانبي لا تتبدّل بين ويندوز وLinux (النص نفسه،
            # لكن «الحجم = البايتات» يجب أن يبقى صادقاً على كل منصة)
            jf.write(json.dumps(doc_json(doc, articles),
                                ensure_ascii=False, indent=2))
        # sha256 = بصمة **الملف الذي سيحمّصه ميزان فعلياً** (= ملف md المذكور
        # في local_path). الدلالة القديمة كانت «بصمة الملف المصدري» (لقطة
        # HTML الخام إن وُجدت)، وبوابة السلامة في csv_legal_library_importer
        # تتحقق من بايتات local_path ⇒ كل وثيقة مزحوفة كانت تُرفض «بصمة غير
        # مطابقة» (قِيس 2026-09-17: لا صَفْر مُصدَّر من زحف حيّ يمرّ). بصمة
        # اللقطة تبقى موثقة للاستهلاك الآلي في JSON الجانبي (snapshot_sha256).
        sha = hashlib.sha256(md_bytes).hexdigest()
        doc_id = (f"law_{doc['year']}_{doc['number']}"
                  if doc["year"] and doc["number"]
                  else "doc_" + (_get(doc, "content_sha256") or
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
            "title": _get(doc, "title") or "",
            "type": "قانون" if (_get(doc, "doc_type") or "") == "law"
                    else (_get(doc, "doc_type") or ""),
            "number": _get(doc, "number") if _get(doc, "number") is not None else "",
            "year": _get(doc, "year") if _get(doc, "year") is not None else "",
            "date": "",  # تاريخ الإصدار غير معروف من المنتدى — لا يُختلق
            "category": BRANCH_AR.get(_get(doc, "branch"),
                                      _get(doc, "branch") or "غير مصنف"),
            "url": _get(doc, "source_url") or "",
            "format": "html",
            "priority": _priority_for(_get(doc, "source_credibility")),
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
    if renamed:
        log.info(f"تكرار أسماء الملفات: {renamed} وثيقة أعيدت تسميتها بلاحقة "
                 "لتجنّب الدفن (نفس الهوية من مصدرين)")
    log.info(f"حزمة المحتوى: {len(rows)} وثيقة في {out} ({skipped} تخطي)")
    rep = {"docs": len(rows), "skipped": skipped,
           "renamed": renamed,
           "csv": str(csv_path), "out_dir": str(out)}
    if with_manifest:
        rep.update(_finalize(out, db_path, rows))
    return rep


def _finalize(out: Path, db_path, rows: list) -> dict:
    """توسيع عقد المواد + المانيفست + بوابة التحقق المشتركة.

    لا يفشل التصدير بأي حال — المانيفست طبقة فوق الحزمة، وغيابه لا يجب أن
    يهدم ما يعمل (درس «SystemExit بـ pdf_to_text كان يقتل الدورة»).
    """
    extra: dict = {}
    try:
        import package_manifest
        extra["enrich"] = package_manifest.enrich_doc_json(out, db_path, rows)
        manifest = package_manifest.build_manifest(db_path, out)
        extra["manifest"] = {"articles": manifest["corpus"]["articles"],
                             "files": len(manifest["files"]),
                             "schema_version": manifest["schema_version"]}
    except Exception as exc:  # noqa: BLE001 — طبقة إضافية، لا تُسقط الحزمة
        log.warning(f"توسيع عقد المواد مؤجل: {type(exc).__name__}: {exc}")
        extra["enrich_error"] = f"{type(exc).__name__}: {exc}"
    try:
        import verify_package
        checks = verify_package.check_package(out)
        extra["gate_ok"] = all(bool(ok) for _m, ok in checks)
        extra["gate_failed"] = [m for m, ok in checks if not ok]
        counts = verify_package.article_counts(out)
        extra["articles_in_package"] = counts["articles"]
    except Exception as exc:  # noqa: BLE001
        log.warning(f"بوابة التحقق لم تعمل: {type(exc).__name__}: {exc}")
        extra["gate_error"] = f"{type(exc).__name__}: {exc}"
    return extra
