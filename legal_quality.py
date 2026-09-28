# -*- coding: utf-8 -*-
"""مراجعة بشرية مرتبطة ببصمة النص وبوابة محافظة لتصدير التشريع النافذ.

لا تعني القيمة الآلية ``legal_status='ساري'`` أن النفاذ القانوني مثبت؛
هي نتيجة لسلسلة التعديل الموجودة في المتن فقط. يلزم لذلك مراجعة بشرية
مؤرخة مع دليل، وتُبطل المراجعة تلقائياً عند تغير بصمة المحتوى.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

REVIEW_TYPES = {"full_text", "legal_status", "rights"}
REVIEW_OUTCOMES = {"pass", "fail", "unknown"}
_REQUIRED_REVIEWS = ("full_text", "legal_status", "rights")


def _row_value(row, name, default=None):
    try:
        value = row[name]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def text_sha256(text: str | None) -> str:
    """يطابق دلالة بصمة documents.content_sha256 (نص نظيف بعد strip)."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _validate_evidence_url(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value)
        port = parsed.port  # يرفض منفذاً مشوهاً
    except ValueError as exc:
        raise ValueError("رابط الدليل غير صالح") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password):
        raise ValueError("رابط الدليل يجب أن يكون http/https صالحاً دون بيانات دخول")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("منفذ رابط الدليل خارج النطاق")
    return value


def document_subject_sha256(doc) -> str | None:
    clean = _row_value(doc, "clean_content")
    stored = _row_value(doc, "content_sha256")
    if not clean or not str(clean).strip():
        return None
    actual = text_sha256(clean)
    # بصمة مفقودة تاريخياً يمكن اشتقاقها، أما عدم التطابق فإشارة توقف.
    if stored and stored != actual:
        return None
    return stored or actual


def record_document_review(conn, document_id: int, review_type: str,
                           outcome: str, reviewer: str,
                           evidence_url: str | None = None,
                           note: str | None = None) -> int:
    """يسجل قراراً جديداً append-only مرتبطاً ببصمة المحتوى الحالي.

    لا تعدّل المراجعات السابقة؛ وأي تغيير في نص الوثيقة يجعلها غير صالحة
    للنسخة الجديدة عند استدعاء ``assess_current_law``.
    """
    if review_type not in REVIEW_TYPES:
        raise ValueError(f"نوع مراجعة غير معروف: {review_type}")
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError(f"نتيجة مراجعة غير معروفة: {outcome}")
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("اسم المراجع مطلوب")
    evidence_url = _validate_evidence_url(evidence_url)
    if outcome == "pass" and not evidence_url:
        raise ValueError("الدليل المرجعي مطلوب لأي مراجعة ناجحة")

    doc = conn.execute(
        "SELECT id, clean_content, content_sha256 FROM documents WHERE id=?",
        (document_id,)).fetchone()
    if doc is None:
        raise ValueError(f"الوثيقة غير موجودة: {document_id}")
    subject = document_subject_sha256(doc)
    if not subject:
        raise ValueError("تعذر تثبيت بصمة النص؛ راجع اختلاف clean_content/content_sha256")

    cur = conn.execute(
        "INSERT INTO document_reviews "
        "(document_id, review_type, outcome, reviewer, evidence_url, note, "
        " subject_sha256, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (document_id, review_type, outcome, reviewer,
         (evidence_url or "").strip() or None, note,
         subject, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return cur.lastrowid


def _latest_matching_review(conn, document_id: int, review_type: str,
                            subject_sha256: str):
    return conn.execute(
        "SELECT outcome, evidence_url, reviewer, reviewed_at, subject_sha256 "
        "FROM document_reviews WHERE document_id=? AND review_type=? "
        "AND subject_sha256=? ORDER BY id DESC LIMIT 1",
        (document_id, review_type, subject_sha256)).fetchone()


def assess_current_law(conn, doc) -> dict:
    """يفحص أهلية وثيقة لتصنيفها «نص تشريعي نافذ ومراجع».

    هذه بوابة تصدير اختيارية شديدة التحفظ، وليست حكماً قضائياً أو ضماناً
    مطلقاً للنفاذ. تتطلب صكاً، نصاً مكتمل البنية، حالة «ساري» محسوبة، هوية
    رقم/سنة، مواداً، وثلاث مراجعات بشرية ناجحة ذات أدلة وبصمة مطابقة.
    """
    reasons = []
    doc_id = _row_value(doc, "id")
    if doc_id is None:
        return {"eligible": False, "reasons": ["missing_document_id"]}

    if _row_value(doc, "status", "active") != "active":
        reasons.append("document_not_active")
    if _row_value(doc, "nature", "instrument") != "instrument":
        reasons.append("not_a_legal_instrument")
    if not bool(_row_value(doc, "is_complete_text", 0)):
        reasons.append("automated_full_text_check_failed")
    if _row_value(doc, "legal_status") != "ساري":
        reasons.append("computed_status_not_in_force_or_unknown")

    number, year = _row_value(doc, "number"), _row_value(doc, "year")
    identity = _row_value(doc, "identity_key")
    if not identity and (number is None or year is None):
        reasons.append("legal_identity_incomplete")
    if not (_row_value(doc, "source_url") or "").strip():
        reasons.append("source_url_missing")

    article_count = _row_value(doc, "_article_count")
    if article_count is None:
        article_count = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE doc_id=?", (doc_id,)
        ).fetchone()[0]
    if int(article_count or 0) < 1:
        reasons.append("no_article_text")

    subject = document_subject_sha256(doc)
    if not subject:
        reasons.append("content_fingerprint_missing_or_mismatched")
    else:
        for review_type in _REQUIRED_REVIEWS:
            review = _latest_matching_review(conn, doc_id, review_type, subject)
            if review is None:
                reasons.append(f"human_review_missing:{review_type}")
            elif review["outcome"] != "pass":
                reasons.append(f"human_review_not_pass:{review_type}")
            elif not (review["evidence_url"] or "").strip():
                reasons.append(f"human_review_evidence_missing:{review_type}")

    return {"eligible": not reasons, "reasons": reasons,
            "document_id": doc_id, "subject_sha256": subject,
            "policy": "current-law-gate-v1"}


def filter_current_laws(conn, docs):
    eligible, excluded = [], []
    for doc in docs:
        assessment = assess_current_law(conn, doc)
        if assessment["eligible"]:
            eligible.append((doc, assessment))
        else:
            excluded.append((doc, assessment))
    return eligible, excluded


def audit_current_laws(conn, limit: int | None = None) -> list[dict]:
    sql = "SELECT * FROM documents ORDER BY id"
    params = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (max(0, int(limit)),)
    rows = conn.execute(sql, params).fetchall()
    report = []
    for row in rows:
        result = assess_current_law(conn, row)
        report.append({
            "document_id": result["document_id"],
            "title": _row_value(row, "title"),
            "identity_key": _row_value(row, "identity_key"),
            "number": _row_value(row, "number"),
            "year": _row_value(row, "year"),
            "legal_status": _row_value(row, "legal_status"),
            "eligible": result["eligible"],
            "reasons": result["reasons"],
            "subject_sha256": result["subject_sha256"],
        })
    return report
