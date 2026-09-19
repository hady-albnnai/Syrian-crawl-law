"""تنقيح ما بعد الزحف — الخبرة المكتسبة تُطبَّق آلياً داخل الزاحف.

قرار المالك 2026-09-19: «إذا كنت تنقّح القوانين التي نزّلها الزاحف، ضع هذه
الخبرة لدى الزاحف». كل ما كان يُشغَّل يدوياً بأوامر منفصلة (reidentify،
nature، parts --link، law-status --rebuild) يجري هنا بترتيبه الصحيح في
نهاية كل دورة زحف فعلية، وبأمر واحد `python -m cli refine` عند الحاجة.

الترتيب ملزِم (كل خطوة تعتمد على سابقتها):
  1. الطبيعة: صك / أعمال تحضيرية / فهرس … (ما ليس صكاً لا يُطلب له شيء)
  2. الهوية: رقم/سنة/مفتاح من العنوان والديباجة، ثم قاموس الصكوك المسمّاة
     (named_laws.py)، وتصحيح المفاتيح المتناقضة، ثم أرشفة النسخ المتصادمة
  3. الأجزاء: طيّ الصك المشتّت على عدة وثائق تحت رأس واحد (part_of)
  4. الإحالات + حالة النفاذ: ملغى / معدَّل / ساري

لا خطوة تحذف نصاً أو تدمجه؛ كلها تكتب أعمدة وصفية قابلة لإعادة الحساب.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def refine_all(conn) -> dict:
    """يشغّل خطوات التنقيح الأربع بالترتيب ويعيد ملخصاً رقمياً."""
    from doc_nature import reclassify_documents
    from law_identity import reidentify_documents
    from law_parts import link_parts
    from law_status import compute_legal_statuses, rebuild_links

    summary: dict = {}
    nat = reclassify_documents(conn)
    summary["nature"] = nat.get("distribution")
    ident = reidentify_documents(conn)
    summary["identity"] = {k: v for k, v in ident.items() if v}
    # 2-ب. تصادمات الهوية بعد القاموس (نسختان لقانون العقوبات العسكري
    # #105/#145 تصيران 61/1950 معاً): الخاسر يُؤرشف نسخاً لا حذفاً.
    from dedup import dedupe_active_by_identity
    dd = dedupe_active_by_identity(conn)
    summary["dedup"] = {"collisions": dd.get("collisions", 0),
                        "archived": dd.get("archived", 0)}
    parts = link_parts(conn)
    summary["parts"] = {"groups": parts["groups"],
                        "parts_linked": parts["parts_linked"]}
    summary["amendment_links"] = rebuild_links(conn)
    summary["status"] = compute_legal_statuses(conn)
    conn.commit()
    return summary


def format_summary(s: dict) -> str:
    return (f"تنقيح: طبيعة={s.get('nature')} | هوية={s.get('identity')} | "
            f"تصادمات={s.get('dedup')} | أجزاء={s.get('parts')} | إحالات={s.get('amendment_links')} | "
            f"حالات={s.get('status')}")
