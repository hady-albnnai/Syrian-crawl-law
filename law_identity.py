# -*- coding: utf-8 -*-
"""law_identity.py — هوية القانون (نوع + رقم + سنة) — التسليم الأول من
خطة الاكتشاف الذاتي للمصادر (DELIVERY/DESIGN-SELF-DISCOVERY.md §2).

المشكلة التي يحلّها: `documents.number` و`documents.year` موجودان بمخطط
قاعدة البيانات منذ البداية لكن لا شيء يملأهما فعلياً — كل وثيقة تُحفظ
اليوم بـ`number=NULL, year=NULL`. هذا الملف يستخرجهما من نص الوثيقة نفسه
(العنوان + الديباجة)، ويبني منهما `identity_key` مستقراً يُستخدم لاحقاً
لمطابقة النسخ المكررة عبر مصادر مختلفة (§4 من وثيقة التصميم).

قرار مقصود (موثّق بالتصميم §2.3): الاعتماد على (نوع + رقم + سنة) لا على
تشابه نصي كامل ولا على source_url — هذا هو المعرّف القانوني الفعلي
المستخدم في الجريدة الرسمية والنصوص السورية نفسها، لا اختراع تقني.
"""
import re

from extractor_v4 import to_western_digits

# أنواع الصكوك القانونية السورية بترتيب الأكثر تحديداً أولاً — «المرسوم
# التشريعي» يجب أن يُطابَق قبل «المرسوم» و«القانون» وإلا يُقتطع جزئياً.
DOC_TYPES = [
    "المرسوم التشريعي",
    "المرسوم الاشتراعي",  # تسمية تاريخية مرادفة، تظهر بنصوص قديمة
    "القانون الأساسي",
    "القانون",
    "المرسوم",
    "القرار الجمهوري",
    "القرار",
    "النظام الداخلي",
    "النظام",
    "التعليمات التنفيذية",
    "التعليمات",
]

_TYPE_ALT = "|".join(re.escape(t) for t in DOC_TYPES)

# رقم الصك: يقبل فواصل شائعة بين "رقم" والرقم نفسه (شرطة مائلة/أقواس)،
# ويقبل الأرقام الغربية والعربية المشرقية (extractor_v4.to_western_digits
# يطبّعها بعد الاستخراج فلا حاجة لتكرار منطق الأرقام اللفظية هنا).
_NUM = r"\d+|[٠-٩]+|[۰-۹]+"

LAW_ID_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"[^\d]{{0,15}}رقم\s*[/\(]?\s*({_NUM})\s*[/\)]?"
    rf"[^\d]{{0,20}}لعام\s*({_NUM})",
)

# نطاق سنوات معقول للتشريع السوري الحديث — يستبعد مطابقات زائفة (مثلاً
# "رقم 5 لعام 12" من عبارة غير قانونية التقطها التعبير عرضاً).
_MIN_YEAR, _MAX_YEAR = 1920, 2100


def _normalize_type(raw: str) -> str:
    """يوحّد تسميات مرادفة قبل بناء المفتاح (مثال: المرسوم الاشتراعي
    والمرسوم التشريعي صك واحد فعلياً بتسميتين تاريخيتين مختلفتين)."""
    t = raw.strip()
    if t == "المرسوم الاشتراعي":
        return "المرسوم التشريعي"
    return t


def extract_law_identity(title: str, text: str) -> dict:
    """يستخرج هوية القانون من العنوان أولاً ثم من أول 500 حرف من النص
    (حيث تُذكر الديباجة عادة). يعيد عقداً صريحاً لا يدّعي يقيناً غائباً:

    - وُجد رقم وسنة صالحان → identity_confidence='number_year'
    - لم يُعثر على شيء → identity_key=None, identity_confidence=None
    """
    haystacks = []
    if title:
        haystacks.append(title)
    if text:
        haystacks.append(text[:500])

    for haystack in haystacks:
        m = LAW_ID_RE.search(haystack)
        if not m:
            continue
        doc_type = _normalize_type(m.group(1))
        try:
            number = int(to_western_digits(m.group(2)))
            year = int(to_western_digits(m.group(3)))
        except ValueError:
            continue
        if number <= 0:
            continue
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            continue
        return {
            "doc_type": doc_type,
            "law_number": number,
            "law_year": year,
            "identity_key": build_identity_key(doc_type, number, year),
            "identity_confidence": "number_year",
        }

    return {
        "doc_type": None,
        "law_number": None,
        "law_year": None,
        "identity_key": None,
        "identity_confidence": None,
    }


def build_identity_key(doc_type: str, number: int, year: int) -> str:
    """مفتاح مستقر لمطابقة نفس القانون عبر مصادر مختلفة.

    التطبيع هنا مقصود وضيّق (لا تطبيع عام للنص): يوحّد فقط تسميات الصك
    المرادفة (عبر _normalize_type التي يجب استدعاؤها قبل هذا) — لا يمسّ
    الرقم أو السنة لأنهما مستخرجان أصلاً كأعداد صحيحة.
    """
    return f"{doc_type}:{number}:{year}"


def extract_law_references(text: str) -> list:
    """يستخرج كل إشارات القوانين الأخرى المذكورة **نصياً** داخل متن
    الوثيقة (لا كروابط hyperlink) — القطعة الثانية من التصميم (§3).

    يعيد قائمة عناصر فريدة (بلا تكرار بنفس identity_key) كل عنصر:
    {doc_type, law_number, law_year, identity_key, context}
    السياق = 60 حرفاً حول الإشارة، يفيد لاحقاً بتمييز «عدّل» عن «ألغى» عن
    «استند إلى» — هذا الملف يستخرج السياق الخام فقط، بلا تصنيف دلالي
    (يُترك لاستهلاك لاحق كي لا يُقاس هذا الملف بمعيارين مختلفين معاً).
    """
    if not text:
        return []

    seen = set()
    out = []
    for m in LAW_ID_RE.finditer(text):
        doc_type = _normalize_type(m.group(1))
        try:
            number = int(to_western_digits(m.group(2)))
            year = int(to_western_digits(m.group(3)))
        except ValueError:
            continue
        if number <= 0 or not (_MIN_YEAR <= year <= _MAX_YEAR):
            continue
        key = build_identity_key(doc_type, number, year)
        if key in seen:
            continue
        seen.add(key)
        start = max(0, m.start() - 60)
        end = min(len(text), m.end() + 60)
        out.append({
            "doc_type": doc_type,
            "law_number": number,
            "law_year": year,
            "identity_key": key,
            "context": text[start:end].strip(),
        })
    return out


def reference_to_search_query(ref: dict) -> str:
    """يحوّل إشارة نصية مستخرَجة لاستعلام بحث آلي (§3.3 من التصميم) —
    لا نزحف مباشرة (الإشارة مالها URL)، فنولّد استعلاماً يُمرَّر لنفس
    مزوّدي البحث الموجودين أصلاً في discovery.py."""
    return (f"{ref['doc_type']} رقم {ref['law_number']} "
            f"لعام {ref['law_year']} سوريا نص كامل")
