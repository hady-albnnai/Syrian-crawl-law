# -*- coding: utf-8 -*-
"""doc_nature.py — طبيعة الوثيقة: صكّ تشريعي أم شيء آخر؟ (ف٤ — 2026-09-19)

الدليل الذي أوجب هذه الوحدة: عيّنة «بلا هوية» الحقيقية من قاعدة المالك
(262 وثيقة، ملف unidentified.txt) لم تكن مشكلة استخراج هوية في أغلبها:

    208  «الأعمال التحضيرية للقانون المدني المتعلقة بالمادة N» — صفحة لكل
         مادة من المذكرة الإيضاحية للقانون المدني (مصدر واحد)
      4  «استشارات قانونية مجانية» — صفحات فهرس موقع
      4  «وثيقة قانونية سورية» — صفحات مقطّعة من قانون واحد (الجمارك 38)
      4  نسخ مكررة لمرسوم واحد
     42  صكوك حقيقية فعلاً بلا هوية

أي أن 80٪ منها **ليست صكوكاً** ولا يجوز أن تُطلب لها هوية ولا أن تُحقن في
مكتبة ميزان كأنها تشريعات، وإن كانت الأعمال التحضيرية ثمينة للذكاء
الاصطناعي لاحقاً (نية المشرّع لكل مادة) — بشرط تخزينها بطبيعتها.

القيم (documents.nature):
    instrument   صكّ تشريعي/تنظيمي (قانون، مرسوم، قرار، لائحة، نظام، تعليمات،
                 دستور، لائحة تنفيذية، قانون طائفي للأحوال الشخصية…) — الافتراضي
    travaux      أعمال تحضيرية / مذكرة إيضاحية / رأي فقهي مرتبط بمادة
    draft        مشروع قانون (لم يصدر — لا يُستشهد به كنافذ)
    index_page   صفحة فهرس/تصنيف/وسم بموقع، لا نصّ صك
    non_legal    خبر، رسالة جامعية، مقال، اتفاقية دولية غير سورية…

حدود صريحة: القواعد مأخوذة من عناوين حقيقية ظهرت بالقاعدة، لا من تخمين.
ما لا تطابقه قاعدة يبقى instrument (لا نُخرج صكاً من الحزمة بالشك) —
والوثائق المشكوك فيها ترفع للمراجعة بطرق أخرى (quality_score/review).
"""
import re
import unicodedata

NATURES = ("instrument", "travaux", "draft", "index_page", "non_legal")


def _nfkc(s: str) -> str:
    # حروف العرض (Presentation Forms) تظهر بعناوين PDF: «ﻗﺎﻧﻮﻥ» ≠ «قانون»
    return unicodedata.normalize("NFKC", s or "")


# --- travaux: أعمال تحضيرية / مذكرة إيضاحية / رأي فقهي ---------------------
TRAVAUX_TITLE_RE = re.compile(
    r"ال?أ?عمال\s+التحضيرية|المذكرة\s+الإيضاحية|المذكرة\s+الايضاحية|"
    r"الأسباب\s+الموجبة|الرأي\s+الفقهي|شرح\s+المادة")
TRAVAUX_BODY_RE = re.compile(
    r"^\W{0,5}(?:ال)?ا?[أا]عمال\s+التحضيرية\s*:|"
    r"وردت\s+(?:أحكام\s+)?هذه\s+المادة\s+في\s+المشروع\s+التمهيدي|"
    r"^\W{0,5}الرأي\s+الفقهي\s*:")
# رقم المادة الأم من العنوان «…المتعلقة بالمادة    70»
TRAVAUX_ARTICLE_RE = re.compile(r"بالمادة\s*[/(]?\s*(\d+)")

# --- draft: مشروع قانون -------------------------------------------------------
DRAFT_RE = re.compile(r"^\W*مشروع\s+(?:ال)?(?:قانون|مرسوم|نظام|لائحة)")

# --- index_page: صفحات فهرس/تصنيف بمواقع -------------------------------------
INDEX_TITLE_RE = re.compile(
    r"^استشارات\s+قانونية\s+مجانية$|^الصفحة\s+الرئيسية|^أرشيف|^جميع\s+المقالات")
INDEX_BODY_RE = re.compile(
    r"^\W{0,5}(?:تصنيف|وسم|القسم|الفئة)\s*:\s*.{0,120}\(\s*الصفحة\s+\d+\s+من\s+\d+\s*\)")

# --- non_legal: أخبار ورسائل ومقالات واتفاقيات غير سورية -----------------------
NON_LEGAL_TITLE_RE = re.compile(
    r"رسالة\s+ماجستير|رسالة\s+دكتوراه|أطروحة|ﺭﺳﺎﻟﺔ\s+ﻣﺎﺟﺴﺘﻴﺮ|ﺭﺳﺎﻟﺔ\s+ﺩﻛﺘﻮﺭﺍﻩ|"
    r"^توتر\s|^عاجل|^بالفيديو|^بالصور|^تعرف\s+على|^ما\s+هي\s|^كيف\s|"
    r"نظام\s+بودابست|معاهدة\s+التعاون\s+بشأن\s+البراءات|اتفاقية\s+مدريد|"
    r"اتفاقية\s+باريس\s+لحماية|اتفاقية\s+برن\b")
# سطر «تاريخ / كاتب / لا تعليقات» = مقال منشور بمنصة، لا صك — يُقبل كمؤشر
# فقط إذا لم يكن العنوان يبدأ باسم صك (المقال قد يعيد نشر نص قانون كامل:
# «نصوص و مواد قانون العقوبات السوري» بقي instrument لأن متنه مواد)
BLOG_META_RE = re.compile(
    r"\d{1,2}\s+(?:يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|"
    r"سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)،?\s+\d{4}\s*/\s*[^/]{2,40}/\s*لا\s+تعليقات")
INSTRUMENT_HEAD_RE = re.compile(
    r"^\W*(?:نصوص\s+و?\s*مواد\s+)?(?:ال)?(?:قانون|مرسوم|قرار|نظام|لائحة|تعليمات|"
    r"دستور|تعميم|بلاغ|أصول|الأحوال\s+الشخصية|مكافحة)")
ARTICLE_RE = re.compile(r"(?:^|\s)(?:ال)?مادة\s*[/(]?\s*\d+")


def classify_nature(title: str, text: str) -> dict:
    """يعيد {nature, parent_hint, article_no}.

    parent_hint: للأعمال التحضيرية — اسم القانون الأم كما ورد بالعنوان
    («القانون المدني»)؛ article_no: رقم المادة المشروحة. كلاهما None لغير
    travaux. التصنيف لا يدّعي أكثر من العنوان + أول 300 حرف.
    """
    t = _nfkc(title).strip()
    head = _nfkc(text or "")[:300]

    # 1) أعمال تحضيرية — الأكثر عدداً بالقاعدة، ويُحسم بالعنوان أو بمطلع النص
    if TRAVAUX_TITLE_RE.search(t) or TRAVAUX_BODY_RE.search(head):
        art = TRAVAUX_ARTICLE_RE.search(t)
        parent = None
        m = re.search(r"لل?(قانون\s+\S+|مرسوم\s+\S+)", t)
        if m:
            parent = "ال" + m.group(1) if not m.group(1).startswith("ال") \
                else m.group(1)
        return {"nature": "travaux", "parent_hint": parent,
                "article_no": int(art.group(1)) if art else None}

    # 2) مشروع قانون — لم يصدر
    if DRAFT_RE.search(t):
        return {"nature": "draft", "parent_hint": None, "article_no": None}

    # 3) صفحة فهرس بموقع
    if INDEX_TITLE_RE.search(t) or INDEX_BODY_RE.search(head):
        return {"nature": "index_page", "parent_hint": None,
                "article_no": None}

    # 4) غير قانوني: عنوان خبري/أكاديمي/اتفاقية دولية، أو مقال منصة بلا
    #    رأس صك ولا مواد في مطلعه
    if NON_LEGAL_TITLE_RE.search(t):
        return {"nature": "non_legal", "parent_hint": None,
                "article_no": None}
    if BLOG_META_RE.search(head) and not INSTRUMENT_HEAD_RE.search(t) \
            and not ARTICLE_RE.search(head):
        return {"nature": "non_legal", "parent_hint": None,
                "article_no": None}

    return {"nature": "instrument", "parent_hint": None, "article_no": None}


def reclassify_documents(conn) -> dict:
    """صيانة: تصنيف كل الوثائق المخزَّنة وكتابة documents.nature.

    يكتب دائماً (التصنيف حتمي من العنوان+المطلع، لا حكم بشري يُداس).
    يعيد توزيعاً {nature: count} + travaux_by_parent.
    """
    rows = conn.execute(
        "SELECT id, title, substr(clean_content, 1, 400) AS head "
        "FROM documents").fetchall()
    dist = {n: 0 for n in NATURES}
    parents = {}
    for r in rows:
        c = classify_nature(r["title"] or "", r["head"] or "")
        dist[c["nature"]] += 1
        if c["nature"] == "travaux":
            parents[c["parent_hint"] or "?"] = \
                parents.get(c["parent_hint"] or "?", 0) + 1
        conn.execute(
            "UPDATE documents SET nature=?, travaux_article=? WHERE id=?",
            (c["nature"], c["article_no"], r["id"]))
    conn.commit()
    return {"distribution": dist, "travaux_by_parent": parents,
            "total": len(rows)}
