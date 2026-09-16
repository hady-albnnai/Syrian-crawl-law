# -*- coding: utf-8 -*-
"""
wipo_source.py — مصدر ويبو ليكس: تشريعات سورية بنص كامل من إيداعات رسمية
دولية (ف١-ب من ميثاق التوسعة).

لماذا هذا المصدر: الجريدة الرسمية الإلكترونية غير موجودة (ف٠)، وويبو
ليكس يستضيف نصوصاً تشريعية سورية كاملة بالعربية بصفته وديعة رسمية لدى
منظمة دولية — إسناد «مصدر معتمد» بعقد التغطية، فوق أي مصدر مجتمعي.

المسار المقيس فعلياً (ف١-ب، 2026-09-16):
  صفحة التفاصيل العربية ← iframe برابط PDF موقّع قصير العمر ← جلبه
  بترويسة Referer (بدونها يُرجَع غلاف HTML لا الملف) ← استخراج النص
  بPyMuPDF (قياساً: 810 أنماط مادة مقابل 24 لـpypdf) ← تطبيع NFKC
  (أشكال العرض العربية) ← HTML مصنّع يمشي بنفس أنبوب الزحف وبواباته
  (درجة قانونية، هوية، منقّح، سلسلة تعديلات) — لا مسار خاص يتجاوز بوابة.
"""
import html
import re
import unicodedata

import requests

from config import USER_AGENT
from extractor_v4 import extract_main_content, to_western_digits
from logging_setup import get_log

log = get_log("wipo")

_WIPO_DETAILS_RE = re.compile(
    r"wipo\.int/wipolex/(?:ar|en)/legislation/details/\d+", re.IGNORECASE)
_SIGNED_PDF_RE = re.compile(
    r'(?:src|href)="(https://wipolex-res\.wipo\.int/edocs/lexdocs/'
    r'laws/ar/[^"]+?\.pdf[^"]*)"')
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)

PDF_HTTP_TIMEOUT = 90  # ملفات تشريع كاملة — مهلة أطول من صفحة HTML


def is_wipo_details(url: str) -> bool:
    """هل المهمة صفحة تفاصيل تشريع بويبو ليكس؟"""
    return bool(url and _WIPO_DETAILS_RE.search(url))


_INDEX_LINK_RE = re.compile(r'href="(/wipolex/ar/legislation/details/\d+)"')


def extract_index_links(index_html: str) -> list:
    """روابط تفاصيل التشريعات العربية من صفحة فهرس ويبو (عضوية الدولة).

    المصدر المقيس: صفحة عضوية سوريا (WIPO_INDEX_URL) — الصكوك معروضة
    بروابط نسبية /wipolex/ar/legislation/details/N. تُعاد مطلقة، مرتبة
    بظهورها، بلا تكرار. النسخ الأخرى (en/zh/...) وقوائم التصفح تُهمل.
    """
    out, seen = [], set()
    for m in _INDEX_LINK_RE.finditer(index_html or ""):
        url = "https://www.wipo.int" + m.group(1)
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_title(details_html: str) -> str:
    """عنوان التشريع من صفحة التفاصيل (عنوان الصفحة عربي بنسخة /ar)."""
    m = _TITLE_RE.search(details_html or "")
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    t = re.sub(r",?\s*WIPO Lex\s*$", "", t).strip()
    return t


def extract_signed_pdf_url(details_html: str) -> str:
    """الرابط الموقّع القصير العمر من الـiframe — يُقرأ من الصفحة وقتها.

    فك كيانات HTML قياسي (html.unescape): المصدر يحمل «&#x3D;» و«&amp;»
    معاً، وأي كيان يبقى يعني رابطاً مكسوراً يرفضه CloudFront بـ403 —
    اكتُشف بالزحف الحي ف١-ب (الاختبارات المحقونة لا تمر من الشبكة
    فلم تمسكه، ولهذا يوجد اختبار يفحص الكيانات صراحة)."""
    m = _SIGNED_PDF_RE.search(details_html or "")
    if not m:
        return ""
    return html.unescape(m.group(1))


def _real_get_bytes(url: str, referer: str = None):
    """جلب بايتات (PDF) بأدب الزحف الكامل: فحص robots والتأخير المهذب
    من fetcher (نفس قواعد باقي الأنبوب)، ثم الطلب بترويسة Referer —
    شرط اكتُشف بالقياس: بدونه يُرجَع غلاف HTML بدل الملف."""
    import fetcher  # محلياً لتفادي استيراد دائري عند الاختبارات

    if not fetcher.is_allowed(url):
        return None, b""
    fetcher.polite_sleep()
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, timeout=PDF_HTTP_TIMEOUT, headers=headers)
    return r.status_code, r.content


def pdf_to_text(pdf_bytes: bytes) -> str:
    """نص الـPDF: PyMuPDF + تطبيع NFKC (أشكال العرض ← حروف قياسية) +
    توحيد الأرقام غربية. غياب المكتبة خطأ مهمة (RuntimeError) لا
    SystemExit — ذاك كان يقتل الدورة كلها فوراً ويترك المهمة عالقة
    running بلا سبيل للعودة (أرض زُرعت بف١-ب؛ نُزعت بعد قياس المالك)."""
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError(
            "wipo_pdf_module_missing — ثبّت المكتبة: pip install pymupdf")
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    raw = "\n".join(page.get_text() for page in doc)
    doc.close()
    t = unicodedata.normalize("NFKC", raw)
    return to_western_digits(t)


def clean_pdf_text(text: str, title: str) -> str:
    """تنظيف بقايا الطباعة البصرية لملفات ويبو المقيسة فعلياً:

    - ترويسة الصفحة المكررة (عنوان التشريع بأعلى كل صفحة).
    - «المادة» ينتهي بها سطر ويليها سطر/أسطر أرقام: أول رقم = رقم
      المادة والباقي أرقام صفحات تُهمل (قيست: «المادة»/«1 1»).
    - **انعكاس خانات الأرقام**: أثر مقيس بصرياً — تسلسل المواد 166-170
      يظهر خاماً 661/761/861/961/071، أي أن كل سلسلة أرقام متعددة
      الخانات مخزنة بترتيبها البصري المعكوس، فتُعاد قلبها خانةً خانة.
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]

    title_words = set((title or "").split())
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln:
            i += 1
            continue
        # ترويسة صفحة = سطر يطابق العنوان أو مجموع كلماته
        if ln == (title or "").strip() or (
                len(title_words) >= 2 and set(ln.split()) == title_words):
            i += 1
            continue
        # التصاق رقم المادة: كل الأسطر الرقمية التالية لأول سطر
        # «المادة» — أولها رقم المادة والباقي أرقام صفحات تُهمل (يشمل
        # حواف مقيسة: «ـ 1 05» و«/» ثم الرقم)
        if ln.rstrip().endswith("المادة"):
            j = i + 1
            tokens = []
            while j < len(lines):
                cand = lines[j]
                if cand and re.fullmatch(r"[ـ\-/ ]{0,3}\d[ \d]{0,10}", cand):
                    tokens.extend(x for x in re.split(r"[ـ\-/ ]", cand) if x)
                    j += 1
                    continue
                if cand and re.fullmatch(r"[ـ\-/]{1,3}", cand):
                    j += 1
                    continue
                break
            if tokens:
                out.append(f"{ln.rstrip()} {tokens[0]}")
                i = j
                continue
        # رقم صفحة منفرد (لم يتبع «المادة») يُحذف
        if re.fullmatch(r"\d{1,4}", ln):
            i += 1
            continue
        # خط شرطات زخرفي فاصل (قياس ف١-ب: نمط ضجيج الأنبوب -{10,}
        # يمسح ما بعده بنفس السطر إن لم يكن سطراً مستقلاً) — زخرفة
        # طباعة بلا قيمة قانونية فتُحذف هنا صراحة
        if re.fullmatch(r"[-–—ـ]{3,}", ln):
            i += 1
            continue
        out.append(ln)
        i += 1

    t = "\n".join(out)
    # قلب سلاسل الأرقام متعددة الخانات (خانةً خانة) — عكس الانعكاس البصري
    t = re.sub(r"\d{2,}", lambda m: m.group(0)[::-1], t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def to_pipeline_html(title: str, clean_text: str) -> str:
    """HTML مصنّع يمشي بمسار الأنبوب القياسي: نفس مستخرج المواد، نفس
    الهرمية (كتاب/باب/فصل تُلتقط من النص)، نفس البوابات — بلا مسار خاص.

    كل سطر نصي يصير عنصراً مستقلاً: بنية الأسطر هي نفسها بنية المصدر،
    فيبقى سلوك أنماط ضجيج المنتديات (المسؤولة عن مسح التواقيع) محصوراً
    بسطر واحد — كما صُممت له — ولا يبتلع بلوكاً كاملاً (قياس ف١-ب)."""
    paras = []
    for ln in (clean_text or "").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if re.match(r"(الكتاب|الباب|الفصل|المبحث|المطلب)\s", ln):
            paras.append(f"<h3>{ln}</h3>")
        else:
            paras.append(f"<p>{ln}</p>")
    body = "\n".join(paras)
    return (f'<html><body><article><div class="entry-content">'
            f"<h1>{title}</h1>\n{body}\n</div></article></body></html>")


def as_pipeline_result(details_url: str, details_html: str,
                       get_bytes=None) -> dict:
    """تحويل مهمة صفحة تفاصيل ويبو إلى نتيجة أنبوب قياسية.

    يعيد {ok, html, status, final_url} للنجاح أو {ok: False, error} —
    والفاشل يعامَل بدورة الزحف كأي فشل جلب (تصنيف خطأ وتمييز مهمة).

    مصدران مرشحان ويفوز الأفضل بالقياس (ف٢): الإيداع الرسمي (الـPDF)
    يُفضَّل عند التكافؤ، لكن قياس دفعة سوريا كشف أن بعض الإيداعات مسح
    ضوئي بلا طبقة نص (جمارك: 78 حرفاً من 2.4MB) أو بخطوط بترميز مخصص
    يخرج خردة محارف تحكم (مدني) أو بنص معكوس بصرياً (دستور) — بينما متن
    صفحة التفاصيل نفسها نظيف وكامل لديها (149/368 مادة). والعكس عند
    العقوبات: متن هزيل (11 مادة) مقابل PDF كامل (775). فبوابات الصلاحية
    (طول، عربية، جودة، مواد) تطبَّق على المرشحَين ويفوز صاحب المواد
    الأكثر — بلا افتراض أن الإيداع دائماً الأفضل.
    """
    get_bytes = get_bytes or _real_get_bytes
    title = extract_title(details_html)
    if not title:
        return {"ok": False, "error": "wipo_no_title"}
    signed = extract_signed_pdf_url(details_html)
    if not signed:
        return {"ok": False, "error": "wipo_no_pdf"}

    # ── المرشح 1: الـPDF الموقّع (الإيداع الرسمي) ──
    pdf_html, n_pdf, pdf_error = None, -1, None
    text = ""
    status, content = get_bytes(signed, referer=details_url)
    if status is None:
        pdf_error = "wipo_blocked_robots"
    elif status != 200 or not content.startswith(b"%PDF"):
        pdf_error = f"wipo_pdf_fetch_{status}"
    else:
        try:
            text = clean_pdf_text(pdf_to_text(content), title)
        except Exception as exc:  # غياب مكتبة، PDF معطوب — فشل مرشح لا دورة
            pdf_error = f"wipo_pdf_transform_failed: {exc}"
        if not pdf_error and len(text) < 1000:
            pdf_error = "wipo_text_too_short"
        if not pdf_error and _junk_ratio(text) >= 0.05:
            pdf_error = "wipo_pdf_junk_text"
        if not pdf_error and _arabic_ratio(text) < 0.25:
            pdf_error = "wipo_no_arabic_text"
        if not pdf_error:
            pdf_html = to_pipeline_html(title, text)
            n_pdf = _real_article_count(pdf_html, details_url)
            if n_pdf < 1:
                pdf_html, pdf_error = None, "wipo_text_quality"

    # ── عطل جلب/بنية بالـPDF: فشل المهمة نفسها — يُعاد لاحقاً فيُجلب
    # الإيداع كاملاً؛ بديل الصفحة يقتصر على الإيداعات الرديئة جوهرياً
    # (مسح ضوئي/خردة ترميز/معكوس/أجنبي) حيث لا PDF صالح يُنتظر. ──
    if pdf_error and not pdf_error.startswith(
            ("wipo_text_too_short", "wipo_pdf_junk_text",
             "wipo_no_arabic_text", "wipo_text_quality")):
        return {"ok": False, "error": pdf_error}

    # ── المرشح 2: متن صفحة التفاصيل نفسها (كما هي — أصالة مثبتة) ──
    # بوابته أشد قليلاً (مواد ≥5): صفحات التفاصيل تحمل دائماً نصاً
    # عربياً تمهيدياً (بويلربليت ويبو) قد يجتاز بوابات القلة الصغرى.
    page_html, n_page = None, -1
    ext = extract_main_content(details_html, details_url)
    page_arabic = (ext["success"]
                   and _arabic_ratio(ext["clean_text"]) >= 0.25)
    if page_arabic and len(ext["clean_text"]) >= 1000:
        n_page = len([a for a in ext["articles"]
                      if not a.get("is_preamble")])
        if n_page >= 5:
            page_html = details_html

    # ── الحكم: الأكثر مواداً يفوز؛ التعادل للـPDF (الإيداع الرسمي) ──
    if pdf_html is not None or page_html is not None:
        if page_html is not None and (pdf_html is None or n_page > n_pdf):
            log.info(f"   [wipo] {title[:55]} — فاز متن صفحة التفاصيل "
                     f"({n_page} مادة؛ إيداع الـPDF غير صالح أو أفقر)")
            return {"ok": True, "status": 200, "html": page_html,
                    "final_url": details_url, "encoding": "utf-8"}
        log.info(f"   [wipo] {title[:55]} — نص الـPDF "
                 f"({len(text)//1000}k حرف، {n_pdf} مادة)")
        return {"ok": True, "status": 200, "html": pdf_html,
                "final_url": details_url, "encoding": "utf-8"}

    # ── لا صالح: تشخيص صادق يميز الحالات ──
    if pdf_error and not (pdf_error == "wipo_no_arabic_text"
                          and page_arabic):
        return {"ok": False, "error": pdf_error}
    return {"ok": False, "error": "wipo_text_quality"}


# نسبة الحروف العربية من مجموع الحروف — يميز الإيداعات الإنجليزية فقط
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


def _arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _ARABIC_RE.match(c)) / len(letters)


def _junk_ratio(text: str) -> float:
    """محارف التحكم (عدا الأسطر) من الطول — بصمة ترميز الخطوط المخصصة
    التي تخرج خردة (قِيس مدني: \\u0002\\u0003 بأعلى النص)."""
    if not text:
        return 0.0
    junk = sum(1 for c in text if ord(c) < 32 and c not in "\t\n\r")
    return junk / len(text)


def _real_article_count(html_str: str, url: str) -> int:
    ext = extract_main_content(html_str, url)
    if not ext["success"]:
        return 0
    return len([a for a in ext["articles"] if not a.get("is_preamble")])
