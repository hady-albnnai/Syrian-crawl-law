# -*- coding: utf-8 -*-
"""source_quality.py — فئة رسمية المصدر + اكتمال النص (التسليم الثالث من
خطة الاكتشاف الذاتي للمصادر، DELIVERY/DESIGN-SELF-DISCOVERY.md §4.2).

يطبّق معياري المقارنة اللذين حددهما المالك صراحة بترتيب الأولوية:
  1. رسمية المصدر (domain_tier) — الأصغر رقماً أعلى رسمية.
  2. اكتمال النص الكامل (is_complete_text).

كلا المعيارين حتمي وشفاف بالكامل (بلا نموذج احتمالي) — قرار مقصود موثّق
بالتصميم: حجم المتن السوري صغير نسبياً، والمعيار الحاسم (الرسمية) معرَّف
يدوياً أصلاً بقائمة محصورة، فلا داعٍ لتعقيد إحصائي إضافي.
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
