# -*- coding: utf-8 -*-
"""source_quality.py — معيارا التفريد + تقييم مرشّح المصدر.

في مقارنة نسخ التشريع يبقى ترتيب المالك الموثق كما هو:
  1. رسمية المصدر (domain_tier) — الأصغر رقماً أعلى رسمية.
  2. اكتمال النص الكامل (is_complete_text).

وتضيف `source_assessment_score` تقييماً تفسيرياً منفصلاً للمصدر المكتشف
(الرسمية، الصلة، البنية، الاكتمال، والوصول). كلا المسارين حتمي وشفاف؛
ولا تمنح درجة التقييم اعتماداً أو تغيّر قرار المراجعة.
"""
from urllib.parse import urlparse

from config import DEFAULT_DOMAIN_TIER, OFFICIAL_DOMAIN_TIERS

# عبارات اقتطاع شائعة بالمصادر الثانوية (منتديات/مدونات تنقل جزءاً فقط) —
# وجودها قرب نهاية النص المستخرَج مؤشر نص منقوص لا كامل.
_TRUNCATION_MARKERS = (
    "اقرأ المزيد", "المزيد...", "تتمة", "المصدر:", "يتبع", "...",
    "المصدر :", "انظر الرابط",
)


def domain_tier_for_url(url: str) -> int:
    """فئة رسمية المصدر لرابط معيّن، بمطابقة النطاق (host) على القائمة
    المحصورة يدوياً في config.OFFICIAL_DOMAIN_TIERS. أي نطاق غائب عنها
    (بما فيها نطاقات gov.sy غير المُدرَجة صراحة — لا نمنح رسمية تلقائية
    لكل ما ينتهي بـgov.sy، بعضها خدمي لا تشريعي) يُعامل بالفئة الافتراضية.
    """
    if not url:
        return DEFAULT_DOMAIN_TIER
    host = (urlparse(url).netloc or "").lower()
    host = host.split(":")[0]  # إسقاط المنفذ إن وُجد
    if host.startswith("www."):
        host = host[4:]
    return OFFICIAL_DOMAIN_TIERS.get(host, DEFAULT_DOMAIN_TIER)


def _articles_sequence_gapless(article_numbers: list) -> bool:
    """يتحقق أن أرقام المواد المستخرجة متسلسلة بلا فجوة (1..N) — إشارة
    اكتمال قوية. المدخل قد يحوي 0 (المقدمة is_preamble) فيُستبعد."""
    nums = sorted({n for n in article_numbers if isinstance(n, int) and n > 0})
    if len(nums) < 2:
        return True  # لا يكفي للحكم — لا نعاقب وثيقة بمادة واحدة فقط
    return nums == list(range(nums[0], nums[-1] + 1))


def is_complete_text(clean_text: str, articles: list) -> bool:
    """اكتمال النص الكامل (§4.2.2) — علم منطقي واحد من ثلاث علامات
    موضوعية، لا نسبة مئوية مركّبة (بساطة وقابلية تفسير مقصودتان).

    1. لا اقتطاع صريح قرب نهاية النص.
    2. تسلسل أرقام المواد متصل بلا فجوة.
    (العلامة الثالثة الموصوفة بالتصميم — مطابقة آخر مادة برقم مذكور
    صراحة بمكان آخر بالنص — نادرة الحدوث فعلياً وتحتاج استخراجاً إضافياً
    خارج نطاق هذا التسليم؛ العلامتان أعلاه كافيتان لقرار موضوعي اليوم
    وتُستكملان لاحقاً بلا تغيير بالعقد الخارجي لهذه الدالة.)
    """
    tail = (clean_text or "")[-200:]
    truncated = any(marker in tail for marker in _TRUNCATION_MARKERS)
    if truncated:
        return False

    real_numbers = [a.get("article_number") for a in (articles or [])
                    if not a.get("is_preamble")]
    return _articles_sequence_gapless(real_numbers)


# تقييم المصدر المكتشف نفسه — منفصل عن قرار اعتماده. الدرجة تفسيرية
# (0..100) وتجمع إشارات ثابتة؛ لا تمنح الاعتماد ولا تبدأ الزحف.
_AUTHORITY_POINTS = {0: 25, 1: 23, 2: 20, 3: 16, 4: 12}


def source_assessment_score(*, domain_tier: int, source_type: str,
                            accessible: bool, article_count: int = 0,
                            precedent_count: int = 0, legal_link_count: int = 0,
                            text_chars: int = 0, complete_text=None,
                            engine: str = "") -> dict:
    """درجة آلية شفافة لجودة مرشح المصدر، لا تعني اعتماداً.

    المحاور: رسمية النطاق (25)، الصلة القانونية (35)، بنية/أدلة المحتوى
    (25)، اكتمال النص (8)، وإمكانية الوصول المهذبة (15). تُقصّ المحاور
    إلى حدودها قبل الجمع، ثم تُقص الدرجة النهائية إلى 100.
    """
    tier = domain_tier if domain_tier in _AUTHORITY_POINTS else 4
    authority = _AUTHORITY_POINTS[tier]
    access = 15 if accessible else 0

    relevance_by_type = {
        "mixed": 35,
        "legislation": 33,
        "precedent": 33,
        "potential_legal": 18,
        "unknown": 0,
        "nonlegal": 0,
    }
    relevance = relevance_by_type.get(source_type, 0)

    article_points = min(12, max(0, int(article_count or 0)) * 3)
    precedent_points = min(12, max(0, int(precedent_count or 0)) * 4)
    link_points = min(8, max(0, int(legal_link_count or 0)) * 2)
    text_points = min(6, max(0, int(text_chars or 0)) // 500)
    engine_points = 3 if engine in {"phpbb", "wordpress", "generic"} else 0
    structure = min(25, article_points + precedent_points + link_points
                    + text_points + engine_points)

    if article_count and complete_text is True:
        completeness = 8
    elif article_count:
        completeness = 3
    elif precedent_count:
        completeness = 5
    else:
        completeness = 0

    components = {
        "authority": authority,
        "relevance": relevance,
        "structure": structure,
        "completeness": completeness,
        "accessibility": access,
    }
    score = min(100, sum(components.values()))
    return {"score": round(float(score), 1), "components": components}
