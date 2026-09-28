# -*- coding: utf-8 -*-
"""مسار منفصل لاكتشاف النماذج القانونية وحفظها ومراجعتها وتصديرها.

النموذج ليس تشريعاً: لا يدخل documents ولا فهرس Mizan. البحث يسجل URL
وعنواناً فقط؛ الجلب مقيد بمصدر معتمد؛ تخزين النص الكامل يحتاج تصريح حقوق
صريحاً، والتصدير العادي لا يُخرج إلا نموذجاً مرّ بمراجعة بشرية للحداثة
والاكتمال والاختصاص وحقوق الاستخدام.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

FORM_TYPES = {
    "contract": "عقد",
    "summons": "استدعاء",
    "memorandum": "مذكرة",
    "petition": "لائحة/استدعاء دعوى",
    "application": "طلب",
    "other": "نموذج آخر",
}
RIGHTS_ALLOWED = {"public_domain", "licensed", "permission"}
RIGHTS_VALUES = RIGHTS_ALLOWED | {"unknown", "restricted"}
SOURCE_ROLES = {"official_publisher", "court", "bar_association", "law_firm",
                "legal_aid", "academic", "private", "other"}
REVIEW_OUTCOMES = {"pass", "fail", "unknown"}
REVIEW_TYPES = ("completeness", "currentness", "jurisdiction", "rights")

SYRIAN_FORM_QUERIES = {
    "contract": [
        "سوريا نموذج عقد بيع word pdf",
        "نموذج عقد إيجار عقار سوري",
        "نموذج عقد وكالة خاصة سوريا",
        "نموذج عقد عمل سوريا قانون العمل",
    ],
    "summons": [
        "نموذج استدعاء إلى المحكمة سوريا",
        "صيغة استدعاء قضائي سوري word",
        "نموذج استدعاء محكمة البداية سوريا",
    ],
    "memorandum": [
        "نموذج مذكرة دفاع سوريا محكمة",
        "صيغة مذكرة جوابية قانونية سورية",
        "نموذج مذكرة خطية أمام المحكمة سوريا",
    ],
    "petition": [
        "نموذج لائحة دعوى سوريا",
        "صيغة دعوى مدنية سورية word",
        "نموذج لائحة استئناف سوريا",
    ],
    "application": [
        "نموذج طلب إلى المحكمة سوريا",
        "نموذج طلب تنفيذ سوريا محكمة",
        "صيغة طلب قانوني سوري",
    ],
}


def sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def template_queries(template_type: str | None = None) -> list[str]:
    """استعلامات اكتشاف سورية ثابتة، قابلة للعرض دون أي اتصال بحث."""
    if template_type:
        if template_type not in SYRIAN_FORM_QUERIES:
            raise ValueError(f"نوع نموذج غير معروف أو بلا استعلامات: {template_type}")
        return list(SYRIAN_FORM_QUERIES[template_type])
    return [q for queries in SYRIAN_FORM_QUERIES.values() for q in queries]


def classify_form_type(text: str, title: str = "") -> str:
    sample = f"{title or ''}\n{text or ''}"
    patterns = [
        ("contract", ("عقد", "اتفاقية")),
        ("summons", ("استدعاء", "تكليف بالحضور")),
        ("memorandum", ("مذكرة", "لائحة جوابية")),
        ("petition", ("لائحة دعوى", "صحيفة دعوى", "استئناف")),
        ("application", ("طلب", "يرجى", "ألتمس")),
    ]
    for kind, words in patterns:
        if any(word in sample for word in words):
            return kind
    return "other"


def _validate_http_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("يلزم رابط http/https كامل")
    if parsed.username or parsed.password:
        raise ValueError("الرابط الذي يتضمن بيانات دخول غير مقبول")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("رقم منفذ الرابط غير صالح") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("رقم منفذ الرابط خارج النطاق")
    return url.strip()


def register_candidate(conn, title: str, source_url: str,
                       template_type: str | None = None,
                       discovered_via: str = "manual",
                       branch: str | None = None,
                       jurisdiction: str = "SY") -> tuple[int, bool]:
    """يسجل metadata فقط؛ لا snippet ولا body ولا مهمة زحف."""
    url = _validate_http_url(source_url)
    kind = template_type or classify_form_type(title or "")
    if kind not in FORM_TYPES:
        raise ValueError(f"نوع نموذج غير معروف: {kind}")
    title = (title or "").strip() or "نموذج بلا عنوان"
    existing = conn.execute(
        "SELECT id FROM templates WHERE source_url=? AND template_type=? "
        "ORDER BY id DESC LIMIT 1", (url, kind)).fetchone()
    if existing:
        conn.execute(
            "UPDATE templates SET title=CASE WHEN title IS NULL OR title='' "
            "THEN ? ELSE title END, discovered_via=COALESCE(discovered_via, ?) "
            "WHERE id=?", (title, discovered_via, existing["id"]))
        conn.commit()
        return existing["id"], False
    cur = conn.execute(
        "INSERT INTO templates (title, template_type, branch, source_url, "
        "created_at, jurisdiction, template_status, review_status, "
        "rights_status, discovered_via, is_complete_text) "
        "VALUES (?, ?, ?, ?, ?, ?, 'candidate', 'pending', 'unknown', ?, 0)",
        (title, kind, branch, url, datetime.now(timezone.utc).isoformat(),
         jurisdiction or "unknown", discovered_via))
    conn.commit()
    return cur.lastrowid, True


def register_search_results(conn, candidates, template_type: str,
                            discovered_via: str) -> dict:
    """يسجل نتائج مزود البحث كمرشحين metadata-only، بلا snippet أو fetch."""
    if template_type not in FORM_TYPES:
        raise ValueError(f"نوع نموذج غير معروف: {template_type}")
    added = duplicate = invalid = 0
    for candidate in candidates:
        if isinstance(candidate, dict):
            url = candidate.get("url")
            title = candidate.get("title", "")
        else:
            url = getattr(candidate, "url", None)
            title = getattr(candidate, "title", "")
        if not url:
            invalid += 1
            continue
        try:
            _id, created = register_candidate(
                conn, title, url, template_type=template_type,
                discovered_via=discovered_via)
            added += bool(created)
            duplicate += not created
        except ValueError:
            invalid += 1
    return {"added": added, "duplicates": duplicate, "invalid": invalid}


def approved_source_for_url(conn, url: str):
    """غلاف توافق لبوابة المصدر المركزية في crawl_queue."""
    from crawl_queue import approved_source_for_url as lookup
    return lookup(conn, url)


def extract_template_text(html: str, source_url: str = "") -> tuple[str, str]:
    """استخراج محلي بسيط؛ لا يدّعي الاكتمال ولا يصنف النص تشريعاً."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    title_tag = soup.select_one("h1") or soup.select_one("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    for node in soup.select("script, style, noscript, svg, nav, header, footer, aside"):
        node.decompose()
    root = (soup.select_one("main") or soup.select_one("article") or
            soup.select_one(".entry-content") or soup.select_one(".content") or
            soup.body or soup)
    # الحقول الفارغة في النماذج مهمة؛ نحتفظ بموضعها بشكل وصفي.
    for node in list(root.select("input, textarea, select")):
        label = (node.get("placeholder") or node.get("aria-label") or
                 node.get("name") or node.name or "حقل")
        node.replace_with(f"[حقل نموذج: {label}]")
    text = "\n".join(line.strip() for line in root.get_text("\n").splitlines()
                      if line.strip())
    return title, text.strip()


def fetch_candidate(conn, template_id: int, fetch_fn=None,
                    store_text: bool = False,
                    rights_status: str = "unknown",
                    rights_evidence_url: str | None = None) -> dict:
    """يجلب URL واحداً من مصدر approved. لا يحفظ النص دون حقوق موثقة.

    عند ``store_text=True`` يجب تمرير حالة حقوق قابلة للاستخدام ودليل؛
    وإلا تحفظ metadata والبصمة فقط ويظل النص خارج القاعدة.
    """
    row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    if row is None:
        raise ValueError(f"النموذج المرشح غير موجود: {template_id}")
    source = approved_source_for_url(conn, row["source_url"])
    if source is None:
        raise PermissionError("يجب اعتماد المصدر ونطاق الرابط قبل الجلب")
    if store_text:
        if rights_status not in RIGHTS_ALLOWED:
            raise ValueError("تخزين النص يحتاج حقوقاً مسموحة: public_domain/licensed/permission")
        if not (rights_evidence_url or "").strip():
            raise ValueError("رابط دليل الحقوق مطلوب قبل تخزين النص الكامل")
        rights_evidence_url = _validate_http_url(rights_evidence_url)
    if fetch_fn is None:
        from fetcher import fetch as fetch_fn
    result = fetch_fn(row["source_url"])
    if not result or not result.get("ok"):
        return {"ok": False, "error": (result or {}).get("error", "fetch_failed")}
    final_url = result.get("final_url") or row["source_url"]
    final_source = approved_source_for_url(conn, final_url)
    if final_source is None or final_source["id"] != source["id"]:
        return {"ok": False, "error": "redirect_outside_approved_source"}

    title, body = extract_template_text(result.get("html", ""), final_url)
    if not body:
        return {"ok": False, "error": "empty_template_text"}
    digest = sha256_text(body)
    fetched_at = datetime.now(timezone.utc).isoformat()
    kind = row["template_type"] or classify_form_type(body, title)
    old = conn.execute("SELECT content_sha256, body, rights_status, "
                        "rights_evidence_url FROM templates WHERE id=?",
                        (template_id,)).fetchone()
    persisted_body = body if store_text else None
    persisted_rights = rights_status if store_text else "unknown"
    persisted_rights_evidence = (rights_evidence_url.strip()
                                 if store_text and rights_evidence_url else None)
    # إذا لم يتغير النص وكان لدينا نسخة مخزنة بإذن، لا نمحو النسخة المسموح بها.
    if (not store_text and old["content_sha256"] == digest and old["body"] and
            old["rights_status"] in RIGHTS_ALLOWED and old["rights_evidence_url"]):
        persisted_body = old["body"]
        persisted_rights = old["rights_status"]
        persisted_rights_evidence = old["rights_evidence_url"]

    if store_text:
        conn.execute(
            "INSERT OR IGNORE INTO template_versions "
            "(template_id, content_sha256, body, source_url, retrieved_at, "
            " rights_status, rights_evidence_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (template_id, digest, body, final_url, fetched_at, rights_status,
             rights_evidence_url.strip()))
    conn.execute(
        "UPDATE templates SET title=?, template_type=?, body=?, source_url=?, "
        "source_role=?, content_sha256=?, retrieved_at=?, is_complete_text=0, "
        "review_status='pending', template_status='candidate', reviewed_by=NULL, "
        "reviewed_at=NULL, rights_status=?, rights_evidence_url=? WHERE id=?",
        (title or row["title"], kind, persisted_body, final_url,
         source.get("source_role") or "unknown", digest, fetched_at,
         persisted_rights, persisted_rights_evidence, template_id))
    conn.commit()
    return {"ok": True, "template_id": template_id, "title": title or row["title"],
            "chars": len(body), "content_sha256": digest,
            "text_stored": bool(persisted_body), "rights_status": persisted_rights,
            "source_role": source.get("source_role") or "unknown"}


def review_template(conn, template_id: int, reviewer: str,
                    completeness: str, currentness: str, jurisdiction: str,
                    rights_status: str, source_role: str = "unknown",
                    completeness_evidence_url: str | None = None,
                    currentness_evidence_url: str | None = None,
                    jurisdiction_evidence_url: str | None = None,
                    rights_evidence_url: str | None = None,
                    note: str | None = None) -> dict:
    """يسجل مراجعات بشرية مستقلة؛ يوافق فقط عند نجاح الأربعة كلها."""
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("اسم المراجع مطلوب")
    if completeness not in REVIEW_OUTCOMES or currentness not in REVIEW_OUTCOMES:
        raise ValueError("نتيجة الاكتمال والحداثة يجب أن تكون pass/fail/unknown")
    if jurisdiction not in ("SY", "non-SY", "unknown"):
        raise ValueError("الاختصاص يجب أن يكون SY أو non-SY أو unknown")
    if rights_status not in RIGHTS_VALUES:
        raise ValueError(f"حالة حقوق غير معروفة: {rights_status}")
    if source_role not in SOURCE_ROLES:
        raise ValueError(f"دور المصدر غير معروف: {source_role}")

    row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    if row is None:
        raise ValueError(f"النموذج غير موجود: {template_id}")
    if not row["body"] or not row["content_sha256"]:
        raise ValueError("لا يمكن اعتماد نموذج بلا نص محفوظ ذي بصمة وحقوق تخزين موثقة")
    digest = sha256_text(row["body"])
    if digest != row["content_sha256"]:
        raise ValueError("بصمة النص لا تطابق المحتوى المخزن؛ أعد جلبه ومراجعته")
    if row["rights_status"] not in RIGHTS_ALLOWED or not row["rights_evidence_url"]:
        raise ValueError("لا يمكن مراجعة/تصدير النص قبل توثيق حقوق تخزينه")

    jurisdiction_outcome = "pass" if jurisdiction == "SY" else (
        "fail" if jurisdiction == "non-SY" else "unknown")
    rights_outcome = "pass" if rights_status in RIGHTS_ALLOWED else (
        "fail" if rights_status == "restricted" else "unknown")
    evidence = {
        "completeness": completeness_evidence_url,
        "currentness": currentness_evidence_url,
        "jurisdiction": jurisdiction_evidence_url,
        "rights": rights_evidence_url or row["rights_evidence_url"],
    }
    outcomes = {
        "completeness": completeness,
        "currentness": currentness,
        "jurisdiction": jurisdiction_outcome,
        "rights": rights_outcome,
    }
    for review_type, outcome in outcomes.items():
        raw_evidence = (evidence[review_type] or "").strip()
        if outcome == "pass" and not raw_evidence:
            raise ValueError(f"دليل {review_type} مطلوب لقرار pass")
        if raw_evidence:
            evidence[review_type] = _validate_http_url(raw_evidence)

    reviewed_at = datetime.now(timezone.utc).isoformat()
    for review_type in REVIEW_TYPES:
        conn.execute(
            "INSERT INTO template_reviews "
            "(template_id, review_type, outcome, reviewer, evidence_url, note, "
            " subject_sha256, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (template_id, review_type, outcomes[review_type], reviewer,
             (evidence[review_type] or "").strip() or None, note, digest,
             reviewed_at))
    approved = all(value == "pass" for value in outcomes.values())
    template_status = ("current" if currentness == "pass" and
                       jurisdiction_outcome == "pass" else
                       ("stale" if currentness == "fail" else "candidate"))
    review_status = ("approved" if approved else
                     ("rejected" if "fail" in outcomes.values() else "pending"))
    conn.execute(
        "UPDATE templates SET jurisdiction=?, template_status=?, review_status=?, "
        "source_role=?, rights_status=?, rights_evidence_url=?, "
        "is_complete_text=?, reviewed_by=?, reviewed_at=? WHERE id=?",
        (jurisdiction, template_status, review_status, source_role,
         rights_status, evidence["rights"], int(completeness == "pass"),
         reviewer, reviewed_at, template_id))
    conn.commit()
    return {"template_id": template_id, "review_status": review_status,
            "template_status": template_status, "outcomes": outcomes,
            "content_sha256": digest}


def _review_is_pass(conn, template_id: int, review_type: str, digest: str) -> bool:
    row = conn.execute(
        "SELECT outcome, evidence_url FROM template_reviews WHERE template_id=? "
        "AND review_type=? AND subject_sha256=? ORDER BY id DESC LIMIT 1",
        (template_id, review_type, digest)).fetchone()
    return bool(row and row["outcome"] == "pass" and row["evidence_url"])


def is_exportable(conn, row) -> bool:
    if not row["body"] or not row["content_sha256"]:
        return False
    if sha256_text(row["body"]) != row["content_sha256"]:
        return False
    if row["template_status"] != "current" or row["review_status"] != "approved":
        return False
    if row["jurisdiction"] != "SY" or not row["is_complete_text"]:
        return False
    if row["source_role"] not in SOURCE_ROLES:
        return False
    if row["rights_status"] not in RIGHTS_ALLOWED or not row["rights_evidence_url"]:
        return False
    return all(_review_is_pass(conn, row["id"], kind, row["content_sha256"])
               for kind in REVIEW_TYPES)


def export_templates(conn, out_dir="export/forms", include_pending: bool = False) -> dict:
    """تصدير منفصل؛ pending = metadata فقط، ولا يخلط مع فهرس التشريعات."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT * FROM templates ORDER BY id").fetchall()
    items, pending_count = [], 0
    for row in rows:
        allowed = is_exportable(conn, row)
        if not allowed:
            pending_count += 1
            if not include_pending:
                continue
        item = {
            "id": row["id"],
            "title": row["title"],
            "template_type": row["template_type"],
            "template_type_ar": FORM_TYPES.get(row["template_type"], "نموذج آخر"),
            "branch": row["branch"],
            "jurisdiction": row["jurisdiction"],
            "template_status": row["template_status"],
            "review_status": row["review_status"],
            "source_url": row["source_url"],
            "source_role": row["source_role"],
            "rights_status": row["rights_status"],
            "rights_evidence_url": row["rights_evidence_url"],
            "is_complete_text": bool(row["is_complete_text"]),
            "content_sha256": row["content_sha256"],
            "based_on_articles_json": row["based_on_articles_json"],
            "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            # pending/غير مؤهل يُصدَّر metadata فقط، حتى في وضع المراجعة.
            "body": row["body"] if allowed else "",
            "export_eligible": allowed,
        }
        items.append(item)

    columns = ["id", "title", "template_type", "template_type_ar", "branch",
               "jurisdiction", "template_status", "review_status", "source_url",
               "source_role", "rights_status", "rights_evidence_url",
               "is_complete_text", "content_sha256", "based_on_articles_json",
               "reviewed_by", "reviewed_at", "body", "export_eligible"]
    csv_path = out / "syrian_legal_forms.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for item in items:
            writer.writerow(item)
    json_path = out / "syrian_legal_forms.json"
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    manifest = {
        "schema_version": "1",
        "package_type": "legal_forms_not_legislation",
        "jurisdiction": "SY",
        "forms_exported": sum(bool(item["export_eligible"]) for item in items),
        "metadata_only": sum(not item["export_eligible"] for item in items),
        "pending_in_database": pending_count,
        "rights_policy": "full_text_only_when_reviewed_and_permitted",
        "files": {},
    }
    for path in (csv_path, json_path):
        manifest["files"][path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
    manifest_path = out / "syrian_legal_forms_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return {"rows": len(items), "exported": manifest["forms_exported"],
            "metadata_only": manifest["metadata_only"],
            "pending_in_database": pending_count,
            "csv": str(csv_path), "json": str(json_path),
            "manifest": str(manifest_path)}
