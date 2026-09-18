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
    return unicodedata.normalize("NFKC", s or "")

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


LAW_ID_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"(?P<gap>[^\d]{{0,30}})رقم\s*[/\(]?\s*(?P<num>{_NUM})\s*[/\)]?"
    rf"(?:[^\d]{{0,20}}لعام\s*/?\s*(?P<year_full>{_NUM})|/\s*(?P<year_slash>{_NUM}))",
)

# صيغة مائلة بلا كلمة «رقم» — قِيس بعناوين أرشيف مجلس الشعب (ف٢):
# «قانون السلطة القضائية ـ المرسوم 98/1961» و«قانون مخالفات الأبنية
# 1/2003». تُجرَّب على العنوان فقط كاحتياط ثانٍ: النص قد يحمل إحالات
# صليبية بلا «رقم» (مثال: «يشير للقانون 10/2014») فتكون هوية زائفة.
LAW_ID_SLASH_RE = re.compile(
    rf"({_TYPE_ALT})"
    rf"[^\d]{{0,20}}(?P<num>{_NUM})\s*/\s*(?P<year_slash>{_NUM})"
)


def _year_of(m) -> int:
    """سنة الصك من المطابقة: صيغة «لعام» أو الصيغة المائلة — مع أي من
    تعبيري الهوية (الاحتياطي بلا مجموعة year_full)."""
    d = m.groupdict()
    return int(to_western_digits(d.get("year_full") or d.get("year_slash")))

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


_TITLE_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
_TITLE_NUM_RE = re.compile(rf"رقم\s*[\u200f/(\[]?\s*(?P<n>{_NUM})")


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
    """
    before = (title or "")[max(0, num_start - 22):num_start]
    lead_head = (leading or "").split()[0] if leading else None
    lead_head = lead_head[2:] if lead_head and lead_head.startswith("ال") \
        else lead_head
    for head in _TYPE_HEADS:
        if head in before and head != lead_head:
            return True
    return False


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
    m = _TITLE_NUM_RE.search(t)
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
        lead = _leading_type(haystack) if idx == 0 else None
        for m in LAW_ID_RE.finditer(haystack):
            if idx == 0 and lead and lead != _normalize_type(m.group(1)):
                continue  # اسم الصك في الصدر غير المطابقة ⇒ المطابقة إحالة
            got = _accept(m, gap_guard=True)
            if got:
                return got
        if idx == 0:
            # احتياط الصيغة المائلة بلا «رقم» — العنوان حصراً (النص يحمل
            # إحالات صليبية فتكون هوية زائفة)
            m = LAW_ID_SLASH_RE.search(haystack)
            if m:
                got = _accept(m)
                if got:
                    return got

    return dict(_NO_IDENTITY)


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
             "partial": 0}
    for r in rows:
        ident = extract_law_identity(r["title"] or "",
                                     r["clean_content"] or "")
        if ident["identity_key"] is None:
            # لا هوية كاملة: يُجرَّب احتياط العنوان لملء العمود الفارغ فقط.
            # هوية قائمة لا تُمسّ، وidentity_key لا يُمسّ إطلاقاً هنا.
            fb = title_only_identity(r["title"] or "")
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
        })
    return out


def reference_to_search_query(ref: dict) -> str:
    """يحوّل إشارة نصية مستخرَجة لاستعلام بحث آلي (§3.3 من التصميم) —
    لا نزحف مباشرة (الإشارة مالها URL)، فنولّد استعلاماً يُمرَّر لنفس
    مزوّدي البحث الموجودين أصلاً في discovery.py."""
    return (f"{ref['doc_type']} رقم {ref['law_number']} "
            f"لعام {ref['law_year']} سوريا نص كامل")
