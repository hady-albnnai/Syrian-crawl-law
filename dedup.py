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
    # B-3 (قرار المالك 2026-09-20 بعد dedup1: 9 أزواج فيها شذرة أعلى طبقة
    # تهزم نسخة كاملة، مثل م.ت 222/1963: 3 مواد ط3 تهزم 76 مادة ط4):
    # الاكتمال الساحق يتقدم على الطبقة — ≥3× مواد الآخر و≥20 مادة زيادة.
    # الفارق الصغير يبقى للطبقة (الرسمي يفوز).
    n_new = int(new_candidate.get("article_count") or 0)
    n_old = int(existing_candidate.get("article_count") or 0)
    for a, b, who in ((n_new, n_old, "new"), (n_old, n_new, "existing")):
        if a >= 3 * max(b, 1) and a - b >= 20:
            return {"winner": who, "decisive_criterion": "article_count_overwhelming",
                    "new_value": n_new, "existing_value": n_old}
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


def _active_doc_row(cursor, doc_id: int):
    """صف documents بالأعمدة التي يحتاجها build_existing_candidate."""
    return cursor.execute(
        "SELECT id, doc_id, title, source_url, clean_content, "
        "quality_score, is_complete_text, source_domain_tier "
        "FROM documents WHERE id = ?", (doc_id,)).fetchone()


def dedupe_active_by_identity(conn) -> dict:
    """دمج الوثائق النشطة المتصادمة بالهوية — الخاسر يُؤرشف نسخاً لا حذفاً.

    تصادمات ما قبل الهوية (ف٢): وثائق حُفظت بلا هوية (عناوين بصيغ لم
    يكن المستخرج يلتقطها) ثم كسبتها لاحقاً بـlaw-status --reidentify —
    هذه لم تمر بميزان وقت الحفظ قط. هذا هو الميزان المؤجل: لكل هوية
    بأكثر من صف نشط، المنافسة بالترتيب بنفس compare_candidates،
    والخاسر superseded + نسخة بdocument_versions + قرار مدوَّن.
    المواد لا تُحذف — تاريخ الوثيقة محفوظ بالنسخة المؤرشفة.
    """
    rows = conn.execute(
        "SELECT id, identity_key FROM documents "
        "WHERE identity_key IS NOT NULL AND status = 'active' "
        "ORDER BY identity_key, id").fetchall()
    by_ident = {}
    for r in rows:
        by_ident.setdefault(r["identity_key"], []).append(r["id"])
    collisions = {k: ids for k, ids in by_ident.items() if len(ids) > 1}

    cursor = conn.cursor()
    archived = 0
    for key, ids in collisions.items():
        survivor = ids[0]                     # الأقدم إدراجاً يبدأ صاحباً
        for challenger in ids[1:]:
            s_row = _active_doc_row(cursor, survivor)
            c_row = _active_doc_row(cursor, challenger)
            if s_row is None or c_row is None:
                continue
            decision = compare_candidates(
                build_existing_candidate(cursor, c_row),   # الوافد لاحقاً
                build_existing_candidate(cursor, s_row))
            if decision["winner"] == "new":
                winner, loser = challenger, survivor
                l_row = s_row
            else:                             # existing أو تعادل: الأقدم تبقى
                winner, loser = survivor, challenger
                l_row = c_row
            reason = (f"دمج تصادم هوية — {decision['decisive_criterion']}"
                      if decision["decisive_criterion"] is not None
                      else "دمج تصادم هوية — تعادل (الأقدم تبقى)")
            archive_document_version(cursor, original_doc_id=loser,
                                     doc_row=dict(l_row), reason=reason)
            cursor.execute("UPDATE documents SET status='superseded' "
                           "WHERE id=?", (loser,))
            record_dedup_decision(cursor, key, winner, loser,
                                  decision["decisive_criterion"],
                                  decision["new_value"],
                                  decision["existing_value"])
            survivor = winner
            archived += 1
    conn.commit()
    return {"collisions": len(collisions), "archived": archived}


def audit_dedup(conn) -> list:
    """B-3: مراجعة كل زوج (فائز نشط / خاسر مستبدَل أو مصدر بديل) بنفس الهوية.

    يعيد صفوفاً {identity, winner_id, loser_id, winner_articles, loser_articles,
    winner_tier, loser_tier, suspicious} — suspicious حين يملك الخاسر مواد
    أكثر بوضوح (≥1.5× و≥10) من الفائز: مرشّح لإعادة الميزان.
    """
    rows = conn.execute(
        """SELECT l.id AS loser_id, l.identity_key, l.status AS loser_status,
                  l.source_domain_tier AS loser_tier, w.id AS winner_id,
                  w.source_domain_tier AS winner_tier,
                  (SELECT COUNT(*) FROM articles WHERE doc_id=l.id AND article_number!='0') AS la,
                  (SELECT COUNT(*) FROM articles WHERE doc_id=w.id AND article_number!='0') AS wa
           FROM documents l JOIN documents w ON w.identity_key=l.identity_key AND w.status='active'
           WHERE l.status IN ('superseded','alternate_source') AND l.identity_key IS NOT NULL
           ORDER BY l.identity_key""").fetchall()
    out = []
    for r in rows:
        la, wa = int(r["la"] or 0), int(r["wa"] or 0)
        out.append({"identity": r["identity_key"], "winner_id": r["winner_id"],
                    "loser_id": r["loser_id"], "loser_status": r["loser_status"],
                    "winner_articles": wa, "loser_articles": la,
                    "winner_tier": r["winner_tier"], "loser_tier": r["loser_tier"],
                    "suspicious": la >= 1.5 * max(wa, 1) and la - wa >= 10})
    return out


def rebalance_suspicious(conn) -> int:
    """يعيد الميزان للأزواج المشبوهة: الخاسر يعود نشطاً ثم dedupe يحسم
    بالمعايير الحالية (بما فيها الاكتمال الساحق). يعيد عدد المُعاد تنشيطهم."""
    n = 0
    for a in audit_dedup(conn):
        if a["suspicious"]:
            conn.execute("UPDATE documents SET status='active' WHERE id=?", (a["loser_id"],))
            n += 1
    conn.commit()
    if n:
        dedupe_active_by_identity(conn)
    return n
