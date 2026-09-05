# -*- coding: utf-8 -*-
"""dedup.py — مطابقة القاعدة وتنقيح التكرار (DELIVERY/DESIGN-SELF-DISCOVERY.md
§4). عند وصول وثيقة جديدة بنفس identity_key لقانون محفوظ سابقاً (من مصدر
مختلف)، يقرر هذا الملف أيهما "الأفضل" ويسجّل القرار للتدقيق — بلا حذف
صامت لأي نسخة (§4.2: نسخ لا استبدال).

معيار المقارنة (محدَّد صراحة من المالك بالأولوية، ثم بحث فعلي للباقي):
  1. رسمية المصدر (domain_tier) — الأصغر رقماً يفوز فوراً.
  2. اكتمال النص الكامل (is_complete_text) — True يفوز على False.
  3. quality_score (الأعلى يفوز).
  4. عدد المواد الحقيقية (الأعلى يفوز).
  5. وجود هرمية مكتشفة (غير فارغة تفوز على فارغة).
  6. طول النص الكامل (الأطول يفوز).
كل معيار يُفحص فقط عند تعادل تام بالمعيار السابق.
"""
from datetime import datetime

CRITERIA_ORDER = (
    "domain_tier", "is_complete_text", "quality_score",
    "article_count", "has_hierarchy", "text_length",
)


def _candidate_value(candidate: dict, criterion: str):
    if criterion == "domain_tier":
        # الأصغر أفضل — نعكس الإشارة كي تبقى دالة المقارنة "الأكبر يفوز"
        # موحّدة لكل المعايير (تبسيط منطق واحد بدل استثناء خاص).
        return -int(candidate.get("domain_tier", 4))
    if criterion == "is_complete_text":
        return 1 if candidate.get("is_complete_text") else 0
    if criterion == "quality_score":
        return float(candidate.get("quality_score") or 0.0)
    if criterion == "article_count":
        return int(candidate.get("article_count") or 0)
    if criterion == "has_hierarchy":
        return 1 if candidate.get("has_hierarchy") else 0
    if criterion == "text_length":
        return int(candidate.get("text_length") or 0)
    raise ValueError(f"معيار غير معروف: {criterion}")  # لا سقوط صامت


def compare_candidates(new_candidate: dict, existing_candidate: dict) -> dict:
    """يقارن وثيقتين تحملان نفس identity_key ويعيد قرار صريح:

    {"winner": "new" | "existing" | "tie", "decisive_criterion": str|None,
     "new_value": ..., "existing_value": ...}

    "tie" فقط إذا تطابقت كل المعايير الستة تماماً (نادر عملياً، ونادراً
    ما يعني نسخة مطابقة حرفياً) — القاعدة الآمنة عند tie: القديمة تبقى
    (لا استبدال بلا سبب حاسم فعلي).
    """
    for criterion in CRITERIA_ORDER:
        new_val = _candidate_value(new_candidate, criterion)
        old_val = _candidate_value(existing_candidate, criterion)
        if new_val > old_val:
            return {"winner": "new", "decisive_criterion": criterion,
                    "new_value": new_val, "existing_value": old_val}
        if old_val > new_val:
            return {"winner": "existing", "decisive_criterion": criterion,
                    "new_value": new_val, "existing_value": old_val}
    return {"winner": "tie", "decisive_criterion": None,
            "new_value": None, "existing_value": None}


def record_dedup_decision(cursor, identity_key: str, winner_doc_id: int,
                          loser_doc_id: int, decisive_criterion: str,
                          winner_value, loser_value) -> None:
    """يسجّل قرار التنقيح للتدقيق (§4.2: «من لا سجل له لا يُصدَّق أنه لم
    يحدث» — نفس مبدأ خطة الذكاء الاصطناعي بميزان)."""
    cursor.execute('''
        INSERT INTO dedup_decisions
        (identity_key, winner_doc_id, loser_doc_id, decisive_criterion,
         winner_value, loser_value, decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (identity_key, winner_doc_id, loser_doc_id, decisive_criterion,
          winner_value, loser_value, datetime.now().isoformat()))


def archive_document_version(cursor, original_doc_id: int, doc_row: dict,
                             reason: str) -> None:
    """ينقل نسخة وثيقة (الخاسرة أو المستبدَلة) لجدول document_versions —
    نسخ لا حذف، حسب القاعدة الدستورية."""
    cursor.execute('''
        INSERT INTO document_versions
        (original_doc_id, doc_id, title, source_url, clean_content,
         quality_score, superseded_at, superseded_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (original_doc_id, doc_row.get("doc_id"), doc_row.get("title"),
          doc_row.get("source_url"), doc_row.get("clean_content"),
          doc_row.get("quality_score"), datetime.now().isoformat(), reason))


def build_new_candidate(domain_tier: int, is_complete: bool,
                        quality_score: float, real_article_count: int,
                        has_hierarchy: bool, text_length: int) -> dict:
    """يبني قاموس المرشح الجديد بالشكل الذي تتوقعه compare_candidates —
    نقطة واحدة موثّقة بدل تكرار أسماء المفاتيح بكل موضع استدعاء."""
    return {
        "domain_tier": domain_tier, "is_complete_text": is_complete,
        "quality_score": quality_score, "article_count": real_article_count,
        "has_hierarchy": has_hierarchy, "text_length": text_length,
    }


def build_existing_candidate(cursor, existing_row) -> dict:
    """يبني قاموس المرشح من صف documents موجود فعلياً + استعلام articles
    المرتبطة به (عدد المواد الحقيقية بلا المقدمة، ووجود هرمية).

    ملاحظة دقة مقصودة: جدول articles لا يخزّن is_preamble صراحة — المقدمة
    تُحفظ بـ article_number='0' (extract_articles_v4 يعطيها الرقم 0)،
    فيُستبعد هذا الرقم تحديداً كتقريب مطابق لمنطق real_articles بالزحف
    الحي، لا تخميناً عشوائياً.
    """
    doc_id = existing_row["id"]
    real_count = cursor.execute(
        "SELECT COUNT(*) FROM articles WHERE doc_id = ? AND article_number != '0'",
        (doc_id,)).fetchone()[0]
    hierarchy_count = cursor.execute(
        "SELECT COUNT(*) FROM articles WHERE doc_id = ? AND hierarchy_path "
        "IS NOT NULL AND hierarchy_path NOT IN ('', '[]')",
        (doc_id,)).fetchone()[0]
    tier = existing_row["source_domain_tier"]
    return {
        "domain_tier": tier if tier is not None else 4,
        "is_complete_text": bool(existing_row["is_complete_text"]),
        "quality_score": existing_row["quality_score"] or 0.0,
        "article_count": real_count,
        "has_hierarchy": hierarchy_count > 0,
        "text_length": len(existing_row["clean_content"] or ""),
    }


def find_existing_by_identity(cursor, identity_key: str):
    """يبحث عن وثيقة نشطة بنفس identity_key. status='active' فقط — نسخة
    مستبدَلة (superseded) لا تُقارَن بها وثيقة جديدة، فقط النشطة الحالية."""
    if not identity_key:
        return None
    cursor.execute('''
        SELECT id, doc_id, title, source_url, clean_content, quality_score,
               is_complete_text, source_domain_tier
        FROM documents
        WHERE identity_key = ? AND status = 'active'
        ORDER BY id LIMIT 1
    ''', (identity_key,))
    return cursor.fetchone()
