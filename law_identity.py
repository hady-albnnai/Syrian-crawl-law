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
import unicodedata

from extractor_v4 import to_western_digits


def _nfkc(s: str) -> str:
    """يفكّ الحروف العربية الإبداعية (presentation forms) إلى حروفها العادية.

    قِيس على قاعدة المالك (2026-09-18): عنوان حيّ «ﻗﺎﻧﻮﻥ أﺻﻮﻝ ﺍﻟﻤﺤﺎﻛﻤﺎﺕ
    ﺍﻟﺴﻮﺭﻱ 2016» مكتوب بحروف U+FEFB… فلا «قانون» تُطابَق ولا «رقم» —
    الوثيقة تسقط بلا هوية وهي سليمة العنوان. التطبيع يردّها حروفاً عادية
    قبل أي نمط، ولا يمسّ الأرقام (to_western_digits يتكفّل بالمشرقية).
    """
    # الياء المقصورة مكان الياء (رسم مصري شائع بالمصادر): «المرسوم التشريعى»
    # (قِيس 2026-09-19: #277 «المرسوم التشريعى رقم/30» ×4 بلا هوية) — يُرَدّ
    # «ى» إلى «ي» فقط حين يليها حرف (لا في آخر الكلمة حيث الألف المقصورة حقيقية:
    # «إلى»، «على»).
    out = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"ى(?=[\u0621-\u064A])", "ي", out)

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
    "التعميم",  # ف١: تعاميم الوزارات (moj) صكوك يشار إليها بهاويتها
    "النظام الداخلي",
    "النظام",
    "التعليمات التنفيذية",
    "التعليمات",
]


def _type_pattern(doc_type: str) -> str:
    """نمط يتحمل أل التعريف الاختيارية على كل كلمة.

    اكتشف ف١ (2026-09-16) على وثائق حقيقية: العناوين الواقعية تكتب
    «قانون العمل رقم /17/ لعام 2010» و«قرار وزارة العدل رقم (349) ل
    لعام 2026» بلا أل التعريف — الأنماط السابقة تطلب «القانون» بأل
    فتفقد الهوية كاملة. التوحيد يتم في _normalize_type بعدها.
    """
    words = [w[2:] if w.startswith("ال") else w for w in doc_type.split()]
    return r"\s+".join(r"(?:ال)?" + re.escape(w) for w in words)


_TYPE_ALT = "|".join(_type_pattern(t) for t in DOC_TYPES)

# رقم الصك: يقبل فواصل شائعة بين "رقم" والرقم نفسه (شرطة مائلة/أقواس)،
# ويقبل الأرقام الغربية والعربية المشرقية (extractor_v4.to_western_digits
# يطبّعها بعد الاستخراج فلا حاجة لتكرار منطق الأرقام اللفظية هنا).
# السنة بصيغتين واقعيتين (ف١-ب): «رقم 17 لعام 2010» و«رقم 148/1949» —
# صيغة الإسناد المائلة الشائعة بعناوين ويبو ليكس الرسمية.
_NUM = r"\d+|[٠-٩]+|[۰-۹]+"

# الفجوة بين اسم الصك وكلمة «رقم»: كانت 15 حرفاً فقط، وهي تُسقط عناوين
# حقيقية طويلة. قِيس على قاعدة المالك (2026-09-18): «قانون منع التعامل مع
# اسرائيل رقم 286 لعام1956» فجوتها 24 حرفاً ⇒ هوية مسقطة رغم أن الرقم
# مكتوب صراحة. صارت 30، والحارس _gap_crosses_other_instrument يمنع أن
# يلتقط الرقم العائد لصكٍ آخر مذكور في الفجوة.
_TYPE_HEADS = tuple(dict.fromkeys(
    (w[2:] if w.startswith("ال") else w) for w in
    (t.split()[0] for t in DOC_TYPES)))


def _gap_crosses_other_instrument(gap: str) -> bool:
    """True إذا كانت الفجوة بين «القانون» و«رقم» تحمل اسم صكٍّ آخر.

    «قانون العقوبات المعدَّل بالمرسوم رقم 12 لعام 2001»: الرقم 12 للمرسوم
    لا للقانون — أخذُه سرقة هوية تُفقد المنقّح ثقةً لا تُستعاد، فيُرفض.
    """
    g = gap or ""
    return any(head in g for head in _TYPE_HEADS)


# السنة تُلتقط بإحدى صيغ رسمية واقعية (ف٣ — 2026-09-19، لتقليص «بلا
# هوية» 291/513 بقاعدة المالك؛ وثيقة بلا هوية لا يُستشهد بها ولا تُحسب
# لها حالة نفاذ):
#   «لعام 2010» / «للعام 2010» / «لسنة 2011» / «عام 2001» / «سنة 2001»
#   «تاريخ 22/6/1949» أو «تاريخ 1949/6/22»  ← السنة مقطع رباعي بالتاريخ
#   «148/1949»                               ← صيغة الإسناد المائلة
_YEAR_WORD = r"(?:لل?عام|لل?سنة|عام|سنة)"
_DATE_DMY = r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*(?P<year_dmy>\d{4})"
_DATE_YMD = r"(?P<year_ymd>\d{4})\s*/\s*\d{1,2}\s*/\s*\d{1,2}"
_YEAR_PART = (
    rf"(?:[^\d]{{0,20}}{_YEAR_WORD}\s*/?\s*(?P<year_full>{_NUM})"
    rf"|[^\d]{{0,20}}(?:ب?تاريخ|المؤرخ\s+في)\s*(?:{_DATE_DMY}|{_DATE_YMD})"
    rf"|/\s*(?P<year_slash>{_NUM}))"
)

LAW_ID_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"(?P<gap>[^\d]{{0,30}})رقم\s*[/\(]?\s*(?P<num>{_NUM})\s*[/\)]?"
    rf"{_YEAR_PART}",
)

# صيغة بلا كلمة «رقم» لكن بكلمة سنة صريحة — العنوان فقط: «الصادر
# بالمرسوم التشريعي 148 لعام 1949»، «القانون 10 لعام 2015».
LAW_ID_NO_RAQM_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"[^\d]{{0,20}}?(?P<num>{_NUM})\s*"
    rf"[^\d]{{0,6}}{_YEAR_WORD}\s*(?P<year_full>{_NUM})"
)

# صيغة مائلة بلا كلمة «رقم» — قِيس بعناوين أرشيف مجلس الشعب (ف٢):
# «قانون السلطة القضائية ـ المرسوم 98/1961» و«قانون مخالفات الأبنية
# 1/2003». تُجرَّب على العنوان فقط كاحتياط ثانٍ: النص قد يحمل إحالات
# صليبية بلا «رقم» (مثال: «يشير للقانون 10/2014») فتكون هوية زائفة.
LAW_ID_SLASH_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"[^\d]{{0,20}}(?P<num>{_NUM})\s*/\s*(?P<year_slash>{_NUM})"
)

# صيغة الشرطة «قانون قمع التهريب13 - 1974» و«قانون النقد الأساسي 23-2002»
# (قِيست على عيّنة المالك 2026-09-19، ف٦). العنوان فقط، بنفس منطق الصيغة
# المائلة: الرقم ≤ 4 خانات ملتصق أو مفصول، ثم شرطة بأشكالها، ثم سنة رباعية.
LAW_ID_DASH_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"(?P<gap>[^\d]{{0,30}}?)(?P<num>\d{{1,4}})\s*[-–—ـ]\s*(?P<year_slash>(?:19|20)\d\d)(?!\d)"
)


def _year_of(m) -> int:
    """سنة الصك من المطابقة: صيغة «لعام» أو الصيغة المائلة — مع أي من
    تعبيري الهوية (الاحتياطي بلا مجموعة year_full)."""
    d = m.groupdict()
    raw = (d.get("year_full") or d.get("year_dmy") or d.get("year_ymd")
           or d.get("year_slash"))
    return int(to_western_digits(raw))

# نطاق سنوات معقول للتشريع السوري الحديث — يستبعد مطابقات زائفة (مثلاً
# "رقم 5 لعام 12" من عبارة غير قانونية التقطها التعبير عرضاً).
_MIN_YEAR, _MAX_YEAR = 1920, 2100


def _normalize_type(raw: str) -> str:
    """يوحّد تسميات مرادفة قبل بناء المفتاح. مرادفان يهمّان:

    - «المرسوم الاشتراعي» و«المرسوم التشريعي»: صك واحد بتسميتين
      تاريخيتين.
    - «قانون» و«القانون» (وأل التعريف عموماً، ف١): نفس الصك — حتى لا
      يتفاوت المفتاح باختلاف صياغة العنوان بين المصادر.
    """
    t = (raw or "").strip()
    if t == "المرسوم الاشتراعي":
        return "المرسوم التشريعي"

    def _bare(phrase):
        return " ".join(w[2:] if w.startswith("ال") else w
                        for w in phrase.split())

    bare = _bare(t)
    for canon in DOC_TYPES:
        if canon != "المرسوم الاشتراعي" and _bare(canon) == bare:
            return canon
    return t


_ISSUED_BY_RE = re.compile(r"الصادرة?\s+ب(?:ال)?$|الصادرة?\s+بموجب\s+(?:ال)?$")
# «الصادر بالمرسوم التشريعي رقم» في ذيل ما قبل الرقم — صيغة إصدار لا إحالة
_ISSUED_BY_TYPE_RE = re.compile(
    rf"الصادرة?\s+(?:بموجب\s+)?ب?(?:{_TYPE_ALT})\s*(?:ذي\s+)?(?:(?:ال)?رقم\s*[\u200f/(\[]?)?\s*$")
_TITLE_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
_TITLE_NUM_RE = re.compile(rf"رقم\s*[\u200f/(\[]?\s*(?P<n>{_NUM})")
# «قانون البينات 359 تاريخ 10» — رقم بلا كلمة «رقم» تليه «تاريخ» (عيّنة المالك
# 2026-09-19). يُقبل للعمود الجزئي فقط، ولا يبني مفتاح هوية.
_TITLE_NUM_DATE_RE = re.compile(rf"(?<!\d)(?P<n>\d{{1,4}})\s+(?:ب?تاريخ|المؤرخ)\b")


_LEAD_RES = [(re.compile(_type_pattern(t).lstrip()), t) for t in DOC_TYPES]


def _leading_type(title: str) -> str | None:
    """اسم الصك الوارد في صدر العنوان (أول 20 حرفاً)، مطبَّعاً.

    العنوان السوري يذكر صكّه أولاً: «قانون العقوبات…»، «المرسوم التشريعي
    رقم 6». والاختيار للأطول عند تساوي الموضع — «المرسوم التشريعي» تسبق
    «المرسوم»، وإلا قُرئت كل تشريعية بصفتها مرسوماً عادياً. أما اسم صك وارداً
    لاحقاً في العنوان فهو إحالة لا هوية: «قانون العقوبات المعدَّل بالمرسوم
    رقم 12 لعام 2001» رقمُها لمرسوم التعديل، ومنحه للقانون يبدّل هوية قانون
    كامل بنصف صفحة.
    """
    head = (title or "")[:20]
    best = None
    for rx, t in _LEAD_RES:
        m = rx.search(head)
        if not m:
            continue
        key = (m.start(), -len(m.group(0)))
        if best is None or key < best[0]:
            best = (key, _normalize_type(t))
    return best[1] if best else None


def _number_belongs_to_other_instrument(title: str, num_start: int,
                                        leading: str | None) -> bool:
    """True إذا سبق «رقم» اسمُ صكٍ غير صكّ العنوان — فالرقم لغيرنا.

    المقارنة على الكلمة الأولى المجردة لا على التسمية كاملة: «المرسوم
    التشريعي رقم 6» ليست إحالة — «مرسوم» رأس «المرسوم التشريعي» نفسه.
    النافذة = كل ما قبل الرقم (كانت 22 حرفاً؛ قِيس 2026-09-19: «التعليمات
    التنفيذية لقانون الضريبة على الدخل رقم /24/ لعام 2003» أخذت رقم القانون
    الأم لنفسها لأن «قانون» أبعد من 22 حرفاً). صيغة الإصدار «الصادر ب…»
    مستثناة: رقم صك الإصدار هو رقم القانون نفسه.
    """
    before = (title or "")[:num_start]
    if _ISSUED_BY_TYPE_RE.search(before):
        # «قانون الأحوال الشخصية الصادر بالمرسوم التشريعي رقم 59»: المرسوم
        # هو صك القانون نفسه لا إحالة — الرقم رقمنا (نفس استثناء الهوية الكاملة).
        return False
    lead_head = (leading or "").split()[0] if leading else None
    lead_head = lead_head[2:] if lead_head and lead_head.startswith("ال") \
        else lead_head
    for head in _TYPE_HEADS:
        if head in before and head != lead_head:
            return True
    return False


_GENERIC_TITLE_RE = re.compile(r"^\W*وثيقة\s+قانونية(?:\s+سورية)?\W*$")


def generic_title_preamble_number(title: str, text: str) -> dict | None:
    """عنوان عام («وثيقة قانونية سورية») + مطلع النص يبدأ بـ«<صك> رقم N».

    قِيس 2026-09-19: #177/#178/#179 شذرات قانون الجمارك نصها يبدأ «القانون
    رقم 38 المادة 77…». الرقم يُقبل جزئياً (لا مفتاح هوية: السنة غائبة) ليدخل
    في تجميع الأجزاء (law_parts). مطلع النص = أول 40 حرفاً فقط: أبعد من ذلك
    قد يكون إحالة.
    """
    if not _GENERIC_TITLE_RE.search(_nfkc(title or "")):
        return None
    head = _nfkc(text or "")[:40]
    m = _PREAMBLE_NUM_RE.match(head.lstrip())
    if not m:
        return None
    try:
        n = int(to_western_digits(m.group("num")))
    except ValueError:
        return None
    if not 0 < n < 10000:
        return None
    return {"doc_type": _normalize_type(m.group(1)), "law_number": n,
            "law_year": None, "identity_confidence": "preamble_number"}


def title_only_identity(title: str) -> dict:
    """احتياط أضعف: رقم مذكور بلفظ «رقم N» و/أو سنة رباعية — من العنوان وحده.

    لا يبني `identity_key`: التطابق بين نسخ القانون الواحدة يبقى مشروطاً
    بالرقم والسنة معاً، فلا تُنسَخ هوية ناقصة فوق هوية كاملة. يُستعمل لملء
    العمودين الفارغين فقط (الصيانة)، والعنوان لا يحمل إحالات لغيره — وهذا
    ما يفرّقه عن المتن، الذي رُفض توسيعه في ف١ لأنه سرق هوية قانون المحاماة
    من إحالة إلى قانون الشركات.
    """
    t = _nfkc(title)
    number = None
    # حيث انتهى حقّنا بالعنوان: ما بعد «رقم» العائد لصكٍّ مذكور فيه ليس
    # رقمنا ولا سنتنا — «قانون العقوبات المعدَّل بالمرسوم رقم 12 لعام 2001»
    # سنةُ 2001 للمرسوم.
    limit = len(t)
    m = _TITLE_NUM_RE.search(t) or _TITLE_NUM_DATE_RE.search(t)
    if m:
        if _number_belongs_to_other_instrument(t, m.start(), _leading_type(t)):
            limit = m.start()
        else:
            try:
                n = int(to_western_digits(m.group("n")))
                number = n if 0 < n < 10000 else None
            except ValueError:
                number = None
    year = None
    ym = _TITLE_YEAR_RE.search(t[:limit])
    if ym:
        y = int(ym.group(1))
        year = y if _MIN_YEAR <= y <= _MAX_YEAR else None
    return {"law_number": number, "law_year": year,
            "identity_confidence": "title_only" if (number or year) else None}


def _accept(m, gap_guard: bool = False) -> dict | None:
    """يتحقق من مطابقة واحدة ويردّ عقدها، أو None إذا كانت مغلوطة."""
    if gap_guard and m.groupdict().get("gap") is not None:
        if _gap_crosses_other_instrument(m.group("gap")):
            return None
    d = m.groupdict()
    doc_type = _normalize_type(m.group(1))
    try:
        number = int(to_western_digits(d["num"]))
        year = _year_of(m)
    except (ValueError, KeyError):
        return None
    if number <= 0 or not (_MIN_YEAR <= year <= _MAX_YEAR):
        return None
    return {
        "doc_type": doc_type,
        "law_number": number,
        "law_year": year,
        "identity_key": build_identity_key(doc_type, number, year),
        "identity_confidence": "number_year",
    }


_NO_IDENTITY = {
    "doc_type": None, "law_number": None, "law_year": None,
    "identity_key": None, "identity_confidence": None,
    "provenance": None,
}


def extract_law_identity(title: str, text: str) -> dict:
    """يستخرج هوية القانون من العنوان أولاً ثم من أول 500 حرف من النص
    (حيث تُذكر الديباجة عادة). يعيد عقداً صريحاً لا يدّعي يقيناً غائباً:

    - وُجد رقم وسنة صالحان → identity_confidence='number_year'
    - لم يُعثر على شيء → identity_key=None, identity_confidence=None
    """
    title, text = _nfkc(title), _nfkc(text)
    haystacks = [h for h in (title, text[:500] if text else "") if h]

    for idx, haystack in enumerate(haystacks):
        where = "title" if idx == 0 else "preamble"
        lead = _leading_type(haystack) if idx == 0 else None
        for m in LAW_ID_RE.finditer(haystack):
            if idx == 0 and lead and lead != _normalize_type(m.group(1)) \
                    and not _ISSUED_BY_RE.search(haystack[max(0, m.start() - 14):m.start()]):
                # اسم الصك في الصدر غير المطابقة ⇒ المطابقة إحالة — إلا
                # صيغة الإصدار «قانون X (الصادر بالمرسوم التشريعي رقم N)»:
                # المرسوم هو هوية القانون نفسه لا إحالة (قِيس 2026-09-19:
                # قانون الإعلام 108/2011 فقد هويته فأخذ هوية القانون الذي
                # يلغيه من متنه، فسقط الإلغاء الحقيقي كإشارة ذاتية).
                continue
            got = _accept(m, gap_guard=True)
            if got:
                got["provenance"] = where
                return got
        if idx == 0:
            # احتياط الصيغة المائلة بلا «رقم» — العنوان حصراً (النص يحمل
            # إحالات صليبية فتكون هوية زائفة)
            # نفس حارس الصدر: «قانون العقوبات المعدل بالمرسوم 12 لعام
            # 2001» صكّه القانون، والمرسوم إحالة — لا يسرق هويته.
            m = next((mm for mm in LAW_ID_NO_RAQM_RE.finditer(haystack)
                      if not lead or lead == _normalize_type(mm.group(1))),
                     None) or LAW_ID_SLASH_RE.search(haystack) \
                or next((mm for mm in LAW_ID_DASH_RE.finditer(haystack)
                         if (not lead or lead == _normalize_type(mm.group(1)))
                         and not _gap_crosses_other_instrument(mm.group("gap"))),
                        None)
            if m:
                got = _accept(m)
                if got:
                    got["provenance"] = where
                    return got

    return dict(_NO_IDENTITY)


_ENACTING_HEAD_RE = re.compile(
    r"رئيس\s+الجمهورية.{0,80}?(?:يرسم|يصدر|يقرر)\s+ما\s+يلي")
_PREAMBLE_NUM_RE = re.compile(
    rf"({_TYPE_ALT})\s*(?:ذي\s+)?(?:ال)?رقم\s*[\u200f/(\[]?\s*(?P<num>{_NUM})")


def merge_title_preamble_identity(title: str, text: str) -> dict | None:
    """هوية مركّبة آمنة: السنة من العنوان + الرقم من ديباجة النص (ف٤).

    الحالة المقيسة (قاعدة المالك، #4): العنوان «قانون تنظيم مهنة المحاماة
    لعام 2010» بلا رقم، والديباجة «الجمهورية العربية السورية القانون رقم 30
    رئيس الجمهورية…» بلا سنة. كلٌّ وحده ناقص؛ معاً هوية كاملة.

    شروط القبول — كلها وإلا None (لا هوية أفضل من هوية مركّبة خاطئة):
    - العنوان يبدأ باسم صك (_leading_type) ويحمل سنة، ولا يحمل رقم صك.
    - أول 300 حرف من النص تذكر «<نفس نوع الصك> رقم N» — النوع مطابق لصكّ
      العنوان (ديباجة «المرسوم التشريعي رقم 3» لا تُكمل عنوان «القانون…»).
    - لا تناقض: إن حمل العنوان رقماً مخالفاً لرقم الديباجة (قِيس #19:
      عنوان «المرسوم التشريعي رقم 6» وديباجة «رقم (3)») يُرفض ويُترك
      للمراجعة البشرية.
    """
    t = _nfkc(title or "")
    head = _nfkc(text or "")[:300]
    lead = _leading_type(t)
    if not lead or not head:
        return None
    tm = _TITLE_NUM_RE.search(t)
    fb = title_only_identity(t)
    year = fb["law_year"]
    if year is None:
        return None
    pm = None
    for m in _PREAMBLE_NUM_RE.finditer(head):
        if _normalize_type(m.group(1)) == lead:
            pm = m
            break
    if pm is None:
        return None
    try:
        number = int(to_western_digits(pm.group("num")))
    except ValueError:
        return None
    if number <= 0:
        return None
    if tm:
        try:
            tnum = int(to_western_digits(tm.group("n")))
        except ValueError:
            tnum = None
        if tnum is not None and tnum != number:
            # تناقض عنوان/ديباجة. يُحسم للديباجة فقط حين تكون رأس إصدارٍ
            # رسمياً («رئيس الجمهورية … يرسم/يصدر ما يلي») — العنوان يكتبه
            # الناشر والديباجة نص الصك نفسه (قرار المالك 2026-09-19 على #19:
            # عنوان «المرسوم التشريعي رقم 6» وديباجة «رقم (3)» → 3/2010 مع
            # وسم المخالفة). بغير ذلك لا حسم آلي.
            if not _ENACTING_HEAD_RE.search(head):
                return None
            return {
                "doc_type": lead, "law_number": number, "law_year": year,
                "identity_key": build_identity_key(lead, number, year),
                "identity_confidence": "preamble_over_title",
                "provenance": "merged",
                "title_number_conflict": tnum,
            }
    return {
        "doc_type": lead, "law_number": number, "law_year": year,
        "identity_key": build_identity_key(lead, number, year),
        "identity_confidence": "title_year+preamble_number",
        "provenance": "merged",
    }


def reidentify_documents(conn) -> dict:
    """إعادة استخراج هوية الوثائق المخزَّنة — صيانة بعد تحسّن الاستخراج.

    الحالة النموذجية: قاعدة بُنيت نسخها بكود أقدم (مثلاً قبل قبول أل
    التعريف الاختيارية بف١) فوثائق عناوينها سليمة حُفظت بلا identity_key.
    هذه الدالة تعيد الفحص بالكود الحالي وتكتب ما وجدته فقط:

    - لا تُمحى هوية قائمة إذا لم يُعثر على بديل (تكتب ما وجد، لا تمسح).
    - تحدّث identity_key/identity_confidence/number/year حصراً — عمود
      doc_type تصنيفُ وثائقٍ آخر (law/decision/…) لا يُمس.

    قرار مجاور موثَّق (ف١، قياس على وثائق حية): لا توسيع لنافذة البحث
    بأول 500 حرف — عينة حية أثبتت أن أول مطابقة بالمتن العميق قد تكون
    إحالة لقانون آخر (قانون المحاماة: أول مطابقة بنصه إحالة لقانون
    الشركات 3/2008) فيكون التوسيع اختطافاً للهوية وإفساداً للمنقّح.
    """
    rows = conn.execute(
        "SELECT id, title, clean_content, identity_key, number, year"
        " FROM documents"
    ).fetchall()
    stats = {"gained": 0, "updated": 0, "unchanged": 0, "no_match": 0,
             "partial": 0, "kept_existing": 0, "merged": 0}
    for r in rows:
        ident = extract_law_identity(r["title"] or "",
                                     r["clean_content"] or "")
        if ident["identity_key"] is None and r["identity_key"] is None:
            merged = merge_title_preamble_identity(r["title"] or "",
                                                   r["clean_content"] or "")
            if merged:
                conn.execute(
                    "UPDATE documents SET identity_key=?, "
                    "identity_confidence=?, number=?, year=? WHERE id=?",
                    (merged["identity_key"], merged["identity_confidence"],
                     merged["law_number"], merged["law_year"], r["id"]))
                stats["merged"] = stats.get("merged", 0) + 1
                continue
        if ident["identity_key"] is None:
            # لا هوية كاملة: يُجرَّب احتياط العنوان لملء العمود الفارغ فقط.
            # هوية قائمة لا تُمسّ، وidentity_key لا يُمسّ إطلاقاً هنا.
            fb = title_only_identity(r["title"] or "")
            if fb["law_number"] is None and fb["law_year"] is None:
                g = generic_title_preamble_number(r["title"] or "",
                                                  r["clean_content"] or "")
                if g:
                    fb = g
            set_num = fb["law_number"] if r["number"] is None else None
            set_year = fb["law_year"] if r["year"] is None else None
            if set_num is None and set_year is None:
                stats["no_match"] += 1
                continue
            conn.execute(
                "UPDATE documents SET number=COALESCE(number,?),"
                " year=COALESCE(year,?),"
                " identity_confidence=COALESCE(identity_confidence,?)"
                " WHERE id=?",
                (set_num, set_year, fb["identity_confidence"], r["id"]))
            stats["partial"] += 1
            continue
        if r["identity_key"] == ident["identity_key"]:
            stats["unchanged"] += 1
            continue
        if r["identity_key"] and ident.get("provenance") == "preamble":
            # هوية محفوظة لا تُبدَّل بمطابقة من أول 500 حرف: الديباجة قد
            # تذكر صكاً مجاوراً (قِيس على قاعدة المالك: «قانون أصول تسريح
            # العمال الصادر بالمرسوم…» بدّلت «المرسوم التشريعي:49:1962»
            # إلى «القانون:91:1959» لمرسومٍ ورد في ديباجتها).
            stats["kept_existing"] += 1
            continue
        if r["identity_key"] is None:
            stats["gained"] += 1
        else:
            stats["updated"] += 1
        conn.execute(
            "UPDATE documents SET identity_key=?, identity_confidence=?, "
            "number=?, year=? WHERE id=?",
            (ident["identity_key"], ident["identity_confidence"],
             ident["law_number"], ident["law_year"], r["id"]))
    conn.commit()
    return stats


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
            number = int(to_western_digits(m.group("num")))
            year = _year_of(m)
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
            # ف٥: ما قبل الإشارة وما بعدها منفصلَين — فعل الإلغاء يجب أن
            # يسبق الصك المستهدَف؛ جملة ختامية لاحقة لا تلغيه.
            # before أوسع (160) من السياق المعروض (60): قائمة مرقّمة تحكمها
            # جملة قبل بنود عدة («ويلغى أيضا:\n1- …\n2- …»)
            "before": text[max(0, m.start() - 160):m.start()],
            "after": text[m.end():end],
        })
    return out


def reference_to_search_query(ref: dict) -> str:
    """يحوّل إشارة نصية مستخرَجة لاستعلام بحث آلي (§3.3 من التصميم) —
    لا نزحف مباشرة (الإشارة مالها URL)، فنولّد استعلاماً يُمرَّر لنفس
    مزوّدي البحث الموجودين أصلاً في discovery.py."""
    return (f"{ref['doc_type']} رقم {ref['law_number']} "
            f"لعام {ref['law_year']} سوريا نص كامل")


# --- ف٦: فرز «بلا هوية» إلى فئات قابلة للعلاج (عيّنة المالك 2026-09-19) -----
_REGULATION_TITLE_RE = re.compile(
    r"^\W*(?:ال)?(?:لائحة|اللائحة|تعليمات|التعليمات)\s+(?:ال)?(?:تنفيذية|توضيحية)")
_DUPLICATE_HINT_RE = re.compile(r"^\W*(?:نصوص\s+و?\s*مواد\s+|المادة\s+1\s*[ـ\-–]\s*)")
_FRAGMENT_TITLE_RE = re.compile(
    r"^وثيقة\s+قانونية\s+سورية$|^\W*(?:ب|و)?ال?ترخيص\s+ل|^\W*بالترخيص\s")


def triage_unidentified(title: str, text: str) -> dict:
    """يصنّف وثيقةً بلا هوية إلى فئة علاج، من العنوان ومطلع النص فقط.

    الفئات (قِيست على 46 صكاً بلا هوية من قاعدة المالك):
      partial_number_year  عنوان يحمل رقماً أو سنة (لا كليهما) — يُكمَل بمصدر ثانٍ
      regulation           لائحة/تعليمات تنفيذية — صك تابع، يُربط بقانونه الأم
      title_preamble_clash العنوان يذكر رقماً والديباجة رقماً آخر — مراجعة بشرية
      likely_duplicate     إعادة نشر لنص صك مُعرَّف على الأرجح («نصوص ومواد…»)
      fragment             عنوان عام أو شذرة — مراجعة بشرية
      named_law            صك مشهور بلا رقم بالعنوان («قانون مجلس الدولة») — قاموس مرجعي
    كل ما هنا اقتراحُ فرزٍ لا هوية؛ لا يُكتب في identity_key.
    """
    t = _nfkc(title or "").strip()
    head = _nfkc(text or "")[:300]
    fb = title_only_identity(t)
    if _REGULATION_TITLE_RE.search(t):
        return {"category": "regulation", "hint": fb}
    if _FRAGMENT_TITLE_RE.search(t) or len(t) < 8:
        return {"category": "fragment", "hint": fb}
    tm = _TITLE_NUM_RE.search(t)
    lead = _leading_type(t)
    if tm and lead:
        for m in _PREAMBLE_NUM_RE.finditer(head):
            if _normalize_type(m.group(1)) == lead:
                try:
                    if int(to_western_digits(m.group("num"))) != \
                            int(to_western_digits(tm.group("n"))):
                        return {"category": "title_preamble_clash",
                                "hint": {"title_number": tm.group("n"),
                                         "preamble_number": m.group("num")}}
                except ValueError:
                    pass
                break
    if _DUPLICATE_HINT_RE.search(t) or _DUPLICATE_HINT_RE.search(head):
        return {"category": "likely_duplicate", "hint": fb}
    if fb["law_number"] or fb["law_year"]:
        return {"category": "partial_number_year", "hint": fb}
    return {"category": "named_law", "hint": fb}
