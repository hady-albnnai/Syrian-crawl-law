"""تنقيح ما بعد الزحف — الخبرة المكتسبة تُطبَّق آلياً داخل الزاحف.

قرار المالك 2026-09-19: «إذا كنت تنقّح القوانين التي نزّلها الزاحف، ضع هذه
الخبرة لدى الزاحف». كل ما كان يُشغَّل يدوياً بأوامر منفصلة (reidentify،
nature، parts --link، law-status --rebuild) يجري هنا بترتيبه الصحيح في
نهاية كل دورة زحف فعلية، وبأمر واحد `python -m cli refine` عند الحاجة.

الترتيب ملزِم (كل خطوة تعتمد على سابقتها):
  0. استبعادات المالك (قائمة بيانات) — توسم excluded وتُنسخ، لا تُحذف
  1. الطبيعة: صك / أعمال تحضيرية / فهرس … (ما ليس صكاً لا يُطلب له شيء)
  2. الهوية: رقم/سنة/مفتاح من العنوان والديباجة، ثم قاموس الصكوك المسمّاة
     (named_laws.py)، وتصحيح المفاتيح المتناقضة، ثم أرشفة النسخ المتصادمة
  2-ج. تاريخ الإصدار من ختام الصك/رأسه (ميلادي؛ الهجري لا يُحوَّل)
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
    # 0. استبعادات المالك (exclusions.py) — قبل كل شيء كي لا تُحسب
    from exclusions import apply_exclusions
    summary["excluded"] = apply_exclusions(conn)["excluded"]
    nat = reclassify_documents(conn)
    summary["nature"] = nat.get("distribution")
    ident = reidentify_documents(conn)
    summary["identity"] = {k: v for k, v in ident.items() if v}
    # 2-أ. الصكوك التابعة → قانونها الأم (parent_identity)
    from regulations import link_regulations
    summary["regulations"] = link_regulations(conn)
    # 2-ب. تصادمات الهوية بعد القاموس (نسختان لقانون العقوبات العسكري
    # #105/#145 تصيران 61/1950 معاً): الخاسر يُؤرشف نسخاً لا حذفاً.
    from dedup import dedupe_active_by_identity
    dd = dedupe_active_by_identity(conn)
    summary["dedup"] = {"collisions": dd.get("collisions", 0),
                        "archived": dd.get("archived", 0)}
    # 2-ج. تاريخ الإصدار (A-2) — بعد الهوية لأنه يُقارَن بسنتها
    from issue_date import extract_issue_dates
    summary["issue_date"] = extract_issue_dates(conn)
    parts = link_parts(conn)
    summary["parts"] = {"groups": parts["groups"],
                        "parts_linked": parts["parts_linked"]}
    summary["amendment_links"] = rebuild_links(conn)
    # A-4: التعديل على مستوى المادة → articles.amended_by/status
    from article_links import rebuild_article_links
    summary["article_links"] = rebuild_article_links(conn)
    summary["status"] = compute_legal_statuses(conn)
    conn.commit()
    return summary


def format_summary(s: dict) -> str:
    return (f"تنقيح: مستبعَد={s.get('excluded')} | طبيعة={s.get('nature')} | هوية={s.get('identity')} | "
            f"تاريخ الإصدار={s.get('issue_date')} | لوائح={s.get('regulations')} | تصادمات={s.get('dedup')} | أجزاء={s.get('parts')} | إحالات={s.get('amendment_links')} | مواد={s.get('article_links')} | "
            f"حالات={s.get('status')}")
