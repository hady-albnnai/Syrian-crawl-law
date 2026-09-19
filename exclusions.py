"""استبعاد وثائق بقرار المالك — قاعدة بيانات لا حذف صفوف (ف١٠).

قرار المالك 2026-09-19 على آخر 7 «بلا هوية» (WORKLOG §8-و): «حذف الكل».
التنفيذ وفق CONSTITUTION (نسخ لا حذف): الوثيقة تُنسخ إلى document_versions
بسبب الاستبعاد ثم تُوسم status='excluded' فتخرج من كل عدّ وتصدير، ولا يُمسّ
النص. القاعدة **بيانات** كي لا تعود الوثيقة عند إعادة الزحف: الزاحف يفحص
كل وثيقة جديدة على هذه القائمة عند الحفظ (crawler._handle_topic)، و`refine`
يطبّقها على المخزون.

المطابقة بجذع العنوان المطبَّع (named_laws._norm) — لا بالمعرّف الرقمي
لأن المعرّفات تختلف بين قواعد البيانات.
"""
from __future__ import annotations

from datetime import datetime

from named_laws import _norm

EXCLUSIONS: list[dict] = [
    {"title": "دستور الجمهورية العربية السورية",
     "reason": "ليس صكاً مرقّماً؛ ميزان يملك دستور 2012 أصلاً (constitution_2012)"},
    {"title": "الأحوال الشخصية للطائفة الدرزية",
     "reason": "قانون لبناني صادر 24/2/1948 — ليس صكاً سورياً"},
    {"title": "نظام سر الزواج للكنيسة الشرقية",
     "reason": "إرادة رسولية بابوية 22/2/1949 — ليست صكاً سورياً"},
    {"title": "بالترخيص لمصارف سورية خاصة أو مشتركة وفق النص المرفق",
     "reason": "شذرة بلا عنوان ولا رأس صك"},
    {"title": "نصوص و مواد قانون العقوبات السوري",
     "reason": "إعادة نشر منتدى (2017) لقانون العقوبات 148/1949 الموجود بالمتن"},
    {"title": "المادة 1 ـ أصول تسليم المجرمين العاديين والملاحقين",
     "reason": "مكرّر للقانون 53/1955 الموجود بالمتن بعنوانه الكامل"},
    {"title": "المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني",
     "reason": "ستة أجزاء بلا سنة ولا يمكن تعيين الصك؛ المصرف الزراعي 30/2005 وارد بالمتن بمصدره الرسمي"},
]


def exclusion_reason(title: str) -> str | None:
    nt = _norm(title)
    if not nt:
        return None
    for e in EXCLUSIONS:
        if _norm(e["title"]) in nt:
            return e["reason"]
    return None


def apply_exclusions(conn) -> dict:
    """يوسم المطابقات النشطة excluded بعد نسخها إلى document_versions."""
    from dedup import archive_document_version
    rows = conn.execute(
        "SELECT id, doc_id, title, source_url, clean_content, quality_score "
        "FROM documents WHERE status='active'").fetchall()
    n = 0
    cur = conn.cursor()
    for r in rows:
        reason = exclusion_reason(r["title"] or "")
        if not reason:
            continue
        archive_document_version(cur, r["id"], dict(r), "excluded: " + reason)
        cur.execute("UPDATE documents SET status='excluded', part_of=NULL,"
                    " legal_status=NULL WHERE id=?", (r["id"],))
        # أجزاء كانت مطوية تحت رأس مستبعَد تُستبعد معه (المصرف الزراعي)
        cur.execute("UPDATE documents SET status='excluded' WHERE part_of=?",
                    (r["id"],))
        n += 1
    conn.commit()
    return {"excluded": n, "at": datetime.now().isoformat(timespec="seconds")}
