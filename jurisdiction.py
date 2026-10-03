# -*- coding: utf-8 -*-
"""jurisdiction.py — هل المصدر المكتشف سوري؟ (على مستوى المصدر لا الوثيقة).

التقييم البنيوي (مواد مرقمة، كلمات قانونية) لا يفرّق بين موقع سوري وموقع
مصري أو لبناني يستعمل الصياغة نفسها. هذه الوحدة تجمع علامات نصية ورابطية
مفسَّرة وتعيد حكماً من أربعة:

  syrian   علامات سورية صريحة تغلب الأجنبية
  foreign  علامات دولة أخرى تغلب — لا يُوصى بالمصدر
  mixed    علامات سورية وأجنبية معاً (بوابة قانونية إقليمية) — مراجعة بشرية
  unknown  لا علامات كافية — لا يُوصى بالمصدر آلياً

القاعدة: غياب الدليل ليس دليلاً على السورية. المصدر يُوصى به آلياً فقط إن
كان الحكم syrian أو كان نطاقه في القائمة الرسمية الصريحة (فئة ≤ 2).
كل الأوزان أدناه تقديرية ومفسَّرة، وتُعاير على مصادر معروفة لاحقاً.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ── علامات سورية ──────────────────────────────────────────────
# (نمط، وزن، وصف). التكرار داخل النص يُحسب حتى سقف لكل نمط كي لا يطغى.
_SYRIAN_PATTERNS = [
    (r"الجمهورية\s+العربية\s+السورية", 3, "الجمهورية العربية السورية"),
    (r"الجريدة\s+الرسمية\s+(?:ل\S+\s+)?(?:الجمهورية\s+العربية\s+)?السورية", 3,
     "الجريدة الرسمية السورية"),
    (r"محكمة\s+النقض\s+السورية|نقض\s+سوري", 3, "محكمة النقض السورية"),
    (r"(?:قانون|القانون|قوانين|القوانين|مرسوم|محكمة|قضاء|القضاء|التشريع|"
     r"التشريعات|الدستور)\s+(?:\S+\s+){0,3}(?:السوري|السورية)", 2,
     "قانون/قضاء سوري"),
    # «المرسوم التشريعي» (بأل) كان يفلت من النمط فصُنّف مرسوم سوري 7/1978 أجنبياً
    # لأن نصه يذكر السعودية (بلد إقامة المكلفين). الصيغة سورية الاصطلاح.
    (r"مرسوم\s+(?:ال)?تشريعي", 2, "مرسوم تشريعي"),
    (r"نقابة\s+المحامين\s*(?:[–\-—]\s*)?(?:فرع\s+)?(?:ال|في\s+|ب)?(?:سوري|دمشق|حلب|حمص|حماة|"
     r"اللاذقية|طرطوس|دير\s+الزور|السويداء|درعا|إدلب|الرقة|الحسكة)", 2, "نقابة محامين سورية"),
    (r"(?:الموسوعة|المكتبة|المجموعة|الموسوعات|المدونة|مدونة)\s+(?:ال)?"
     r"(?:قانونية|تشريعية|قضائية|حقوقية)\s+السورية", 2, "موسوعة/مكتبة قانونية سورية"),
    (r"وزارة\s+العدل\s+(?:ال)?سورية|وزارة\s+العدل\s+في\s+سوري", 2, "وزارة العدل السورية"),
    (r"جامعة\s+(?:دمشق|حلب|تشرين|البعث)", 1, "جامعة سورية"),
    (r"السورية|السوري|سورية|سوريا", 0.5, "ذكر سوريا"),
]

# ── علامات دول أخرى ──────────────────────────────────────────
_FOREIGN = {
    "مصر": [r"جمهورية\s+مصر\s+العربية", r"(?:القانون|القوانين|قانون)\s+المصري(?:ة)?",
            r"محكمة\s+النقض\s+المصرية", r"الوقائع\s+المصرية", r"مجلس\s+الدولة\s+المصري",
            r"المحكمة\s+الدستورية\s+العليا\s+المصرية"],
    "لبنان": [r"الجمهورية\s+اللبنانية", r"(?:القانون|القوانين|قانون)\s+اللبناني(?:ة)?",
              r"مرسوم\s+اشتراعي", r"محكمة\s+التمييز\s+اللبنانية"],
    "الأردن": [r"المملكة\s+الأردنية\s+الهاشمية", r"(?:القانون|القوانين|قانون)\s+الأردني(?:ة)?",
               r"محكمة\s+التمييز\s+الأردنية"],
    "العراق": [r"جمهورية\s+العراق", r"(?:القانون|القوانين|قانون)\s+العراقي(?:ة)?",
               r"الوقائع\s+العراقية"],
    "السعودية": [r"المملكة\s+العربية\s+السعودية", r"(?:النظام|الأنظمة)\s+السعودي(?:ة)?",
                 r"ديوان\s+المظالم"],
    "الكويت": [r"دولة\s+الكويت", r"(?:القانون|قانون)\s+الكويتي"],
    "الإمارات": [r"دولة\s+الإمارات", r"(?:القانون|قانون)\s+الإماراتي"],
    "قطر": [r"دولة\s+قطر", r"(?:القانون|قانون)\s+القطري"],
    "البحرين": [r"مملكة\s+البحرين", r"(?:القانون|قانون)\s+البحريني"],
    "عُمان": [r"سلطنة\s+عمان|سلطنة\s+عُمان", r"(?:القانون|قانون)\s+العماني"],
    "اليمن": [r"الجمهورية\s+اليمنية", r"(?:القانون|قانون)\s+اليمني"],
    "فلسطين": [r"دولة\s+فلسطين", r"(?:القانون|قانون)\s+الفلسطيني"],
    "ليبيا": [r"(?:القانون|قانون)\s+الليبي", r"دولة\s+ليبيا"],
    "السودان": [r"جمهورية\s+السودان", r"(?:القانون|قانون)\s+السوداني"],
    "المغرب": [r"المملكة\s+المغربية", r"(?:القانون|القوانين|قانون)\s+المغربي(?:ة)?",
               r"الجريدة\s+الرسمية\s+المغربية"],
    "الجزائر": [r"الجمهورية\s+الجزائرية", r"(?:القانون|قانون)\s+الجزائري"],
    "تونس": [r"الجمهورية\s+التونسية", r"(?:القانون|قانون)\s+التونسي"],
}

_FOREIGN_TLDS = {
    "eg": "مصر", "lb": "لبنان", "jo": "الأردن", "iq": "العراق", "sa": "السعودية",
    "kw": "الكويت", "ae": "الإمارات", "qa": "قطر", "bh": "البحرين", "om": "عُمان",
    "ye": "اليمن", "ps": "فلسطين", "ly": "ليبيا", "sd": "السودان",
    "ma": "المغرب", "dz": "الجزائر", "tn": "تونس",
}

_PER_PATTERN_CAP = 3          # أقصى تكرارات محسوبة لكل نمط
_HOST_SYRIAN_RE = re.compile(r"syria|syrian|(?:^|[-.])sy(?:[-.]|$)", re.I)

SYRIAN_MIN = 4.0              # حد أدنى للحكم syrian
FOREIGN_MIN = 3.0             # حد أدنى للحكم foreign
DOMINANCE = 2.0               # نسبة الغلبة بين الجهتين


def _count(pattern: str, text: str) -> int:
    return min(len(re.findall(pattern, text)), _PER_PATTERN_CAP)


def assess_jurisdiction(url: str = "", title: str = "", text: str = "",
                        snippet: str = "") -> dict:
    """يعيد {verdict, syrian_score, foreign_score, foreign_country, reasons}."""
    blob = " ".join(x for x in (title, snippet, (text or "")[:60_000]) if x)
    reasons: list[str] = []

    syrian = 0.0
    for pattern, weight, label in _SYRIAN_PATTERNS:
        n = _count(pattern, blob)
        if n:
            syrian += n * weight
            if weight >= 2:
                reasons.append(f"علامة سورية: {label} ×{n}")

    foreign_by_country: dict[str, float] = {}
    for country, patterns in _FOREIGN.items():
        total = 0.0
        for pattern in patterns:
            total += _count(pattern, blob) * 3
        if total:
            foreign_by_country[country] = total

    host = ""
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        pass
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld == "sy":
        syrian += 4
        reasons.append("نطاق .sy")
    elif host and _HOST_SYRIAN_RE.search(host):
        syrian += 2
        reasons.append("اسم المضيف يدل على سوريا")
    # «بنود» تفرز تشريعاتها بمسار الدولة (/sy/laws/…): المصدر نفسه يصنّف الوثيقة سورية.
    # قِيس 2026-10-03: 330 وثيقة bunud.ai/sy كانت «unknown» بلا أي دليل أجنبي.
    path = ""
    try:
        path = (urlparse(url).path or "").lower()
    except ValueError:
        pass
    if host == "bunud.ai" and path.startswith("/sy/laws/"):
        syrian += 4
        reasons.append("مسار المصدر /sy/ (تصنيف المصدر)")
    if tld in _FOREIGN_TLDS:
        country = _FOREIGN_TLDS[tld]
        foreign_by_country[country] = foreign_by_country.get(country, 0) + 2
        reasons.append(f"نطاق دولة أخرى (.{tld} — {country})")

    foreign = sum(foreign_by_country.values())
    top_country = (max(foreign_by_country, key=foreign_by_country.get)
                   if foreign_by_country else None)
    if top_country:
        reasons.append(f"علامات {top_country}: {foreign_by_country[top_country]:.0f}")

    if syrian >= SYRIAN_MIN and syrian >= DOMINANCE * foreign:
        verdict = "syrian"
    elif foreign >= FOREIGN_MIN and foreign >= DOMINANCE * syrian:
        verdict = "foreign"
    elif syrian >= SYRIAN_MIN and foreign >= FOREIGN_MIN:
        verdict = "mixed"
    else:
        verdict = "unknown"
    return {"verdict": verdict, "syrian_score": round(syrian, 1),
            "foreign_score": round(foreign, 1),
            "foreign_country": top_country, "reasons": reasons}
