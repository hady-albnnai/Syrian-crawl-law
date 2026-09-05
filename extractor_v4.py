# -*- coding: utf-8 -*-
"""extractor_v4.py — المستخرج v4 (التسليم 2).

فروقه عن v3 (الموثقة في DELIVERY/EXTRACTOR-V4-REPORT.md):
 1. تنظيف Unicode منهجي: تطويل/صفرية العرض/تحكم + ضغط مسافات + التصاق عام.
 2. حاوية محتوى بمؤشرات قابلة للتفسير: مرشحات معروفة + سقوط عام مُقيَّم
    (يحّل إخفاق no_suitable_element المثبت في الزحف الحي).
 3. أرقام غربية وعربية مشرقية وفارسية + صياغات لفظية حتى 99.
 4. المقدمة ككيان مستقل (is_preamble) بشروط واضحة — لا تُحشر «مادة 1».
 5. هرمية كتاب/باب/فصل/مبحث/مطلب تُتراكم وتُلصق بكل مادة.
 6. المكررة والمعدلة لا تُسقط صمتاً: is_duplicate / amendment_note.
 7. فقرات لكل مادة + quality_score بأسباب + مصدر موحد (عقد §6.2).
"""
import hashlib
import re

from bs4 import BeautifulSoup

from extractor import detect_branch, is_legal_content
from logging_setup import get_log

log = get_log("extractor4")

# ═══════════════════ 1) التنظيف المنهجي ═══════════════════

_TASHKEEL = "ً-ْٰ"
_ZW = "​-‏‪-‮﻿"

# ضجيج المنتديات (منقول من v3) — دون قاعدة v3 التي كانت تمزق اللفظيات
# («الأولى» ← «ال أو لى») لأن v4 يدعم اللفظيات صراحةً.
_NOISE = [
    r"منقول عن.*?$", r"مع تحياتي.*?$", r"تحياتي.*?$", r"^رد:\s.*?$",
    r"اقتباس:.*?$", r"التواقيع.*?$", r"-{10,}.*?$", r"مشاركة رقم.*?$",
    r"تاريخ التسجيل.*?$", r"عدد المشاركات.*?$", r"مواضيع مماثلة.*?$",
    r"صلاحيات هذا المنتدى.*?$", r"^.{0,40}شارك في.*?$", r"^حجم الخط.*?$",
    r"^\s*صفحة \d+.*?$",
]


def normalize_unicode(text: str) -> str:
    """إزالة التطويل والحركات والرموز صفرية العرض والمحارف المتحكمة،
    مع ضغط المسافات وضجيج المنتديات — دون مسّ اللفظيات القانونية."""
    if not text:
        return ""
    t = text.replace("ـ", "")
    t = re.sub(f"[{_TASHKEEL}{_ZW}]", "", t)
    t = t.replace("　", " ").replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    for pattern in _NOISE:
        t = re.sub(pattern, "", t, flags=re.MULTILINE | re.IGNORECASE)
    t = re.sub(r'^ل(?=مرسوم|قانون)', 'الم', t, flags=re.M)
    t = re.sub(r'^الممرسوم', 'المرسوم', t, flags=re.M)
    t = re.sub(r'^\s*[-–—•]\s*', '', t, flags=re.MULTILINE)
    # التصاق الأرقام/الواصلة بالحروف: «المادة1-يسري» ← «المادة 1- يسري»
    t = re.sub(r"([^\W\d_])(\d)", r"\1 \2", t)
    t = re.sub(r"(\d)([^\W\d_])", r"\1 \2", t)
    return t.strip()


# ═══════════════════ 3) الأرقام واللفظيات ═══════════════════

_UNITS = ["", "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة",
          "السادسة", "السابعة", "الثامنة", "التاسعة"]
_UNITS_M = ["", "الأول", "الثاني", "الثالث", "الرابع", "الخامس",
            "السادس", "السابع", "الثامن", "التاسع"]
_TENS = ["", "العاشرة", "العشرون", "الثلاثون", "الأربعون", "الخمسون",
         "الستون", "السبعون", "الثمانون", "التسعون"]
_TENS_M = ["", "العاشر", "العشرون", "الثلاثون", "الأربعون", "الخمسون",
           "الستون", "السبعون", "الثمانون", "التسعون"]
_TEENS = ["العاشرة", "الحادية عشرة", "الثانية عشرة", "الثالثة عشرة",
          "الرابعة عشرة", "الخامسة عشرة", "السادسة عشرة", "السابعة عشرة",
          "الثامنة عشرة", "التاسعة عشرة"]

_VERBAL_VALUE = {}
for _i, _w in enumerate(_UNITS[1:], 1):
    _VERBAL_VALUE[_w] = _i
    _VERBAL_VALUE[_w.replace("ال", "ال", 1)] = _i
for _i, _w in enumerate(_TEENS, 10):
    _VERBAL_VALUE[_w] = _i
for _i in range(2, 10):
    _VERBAL_VALUE[_TENS[_i]] = _i * 10
for _u in range(1, 10):
    for _t in range(2, 10):
        _VERBAL_VALUE[f"{_UNITS[_u]} و{_TENS[_t]}"] = _t * 10 + _u

_VERBAL_ALT = "|".join(sorted(_VERBAL_VALUE, key=len, reverse=True))
_DIGITS = r"\d+|[٠-٩]+|[۰-۹]+"

ARTICLE_RE = re.compile(
    rf"الماد[ةه]\s*[/\(ـ-]?\s*(?:({_DIGITS})|({_VERBAL_ALT}))\s*(مكررة?|معدل[ةه]?)?",
    re.IGNORECASE)

HIERARCHY_RE = re.compile(
    r"(الكتاب|الباب|الفصل|المبحث|المطلب)\s+"
    r"((?:ال[أا]ولى?|الثاني[ةه]?|الثالث[ةه]?|الرابع[ةه]?|الخامس[ةه]?|"
    r"السادس[ةه]?|السابع[ةه]?|الثامن[ةه]?|التاسع[ةه]?|العاشر[ةه]?))",
    re.IGNORECASE)

_ORD_M = {}
for _i, _w in enumerate(_UNITS_M[1:], 1):
    _ORD_M[_w] = _i
_ORD_M.update({"الأولى": 1, "العاشر": 10})
for _i in (2, 3, 4, 5, 6, 7, 8, 9):
    _ORD_M[_TENS_M[_i]] = _i * 10

AMEND_RE = re.compile(r"(عد[لت]ت?|أ[ُu]لغيت|ألغيت|استبدلت)[^.\n]{0,80}")


def to_western_digits(s: str) -> str:
    return s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
                                     "0123456789" * 2))


def verbal_to_int(word: str) -> int:
    w = re.sub(r"\s+", " ", word.strip())
    return _VERBAL_VALUE.get(w, 0)


# ═══════════════════ 2) الحاوية القابلة للتفسير ═══════════════════

KNOWN_SELECTORS = ["td.row2.postbody", "div.postbody", "td.postbody",
                   "div.message", "article", "div.entry-content",
                   "div.content", "div.post", "main"]


def _score_el(el):
    txt = el.get_text(" ", strip=True)
    n = len(txt)
    if n < 200:
        return None
    link_mass = sum(len(a.get_text(strip=True)) for a in el.find_all("a"))
    link_density = link_mass / max(n, 1)
    hits = len(re.findall(r"الماد[ةه]", txt))
    score = n + hits * 600 - link_mass * 2.0 - txt.count("»") * 400
    return {"score": round(score, 1), "length": n,
            "article_hits": hits, "link_density": round(link_density, 2)}


def pick_container(soup):
    """يعيد (selector, element, info) مع أسباب مفسرة؛ والسقوط العام يجرّب
    كل div/td/section كبير عند فشل المرشحات المعروفة."""
    best = None
    for sel in KNOWN_SELECTORS:
        for el in soup.select(sel):
            info = _score_el(el)
            if info and (best is None or info["score"] > best[2]["score"]):
                best = (sel, el, info)
    if best and best[2]["score"] > 800:
        return best

    generic_best = None
    for el in soup.find_all(["div", "td", "section"]):
        info = _score_el(el)
        if info and info["length"] < 200_000:
            if generic_best is None or info["score"] > generic_best[2]["score"]:
                generic_best = (f"generic:{el.name}", el, info)
    return generic_best or best


# ═══════════════════ 5) الهرمية ═══════════════════

def scan_hierarchy(text: str) -> list:
    """قائمة (موضع، مسار) — المسار يتراكم: كتاب ← باب ← فصل ← مبحث ← مطلب."""
    levels = ["الكتاب", "الباب", "الفصل", "المبحث", "المطلب"]
    stack = {}
    out = []
    for m in HIERARCHY_RE.finditer(text):
        kind, ord_word = m.group(1), m.group(2)
        kind = kind if kind in levels else kind
        lvl = levels.index(kind)
        label = f"{kind} {_ORD_M.get(ord_word.rstrip('ة'), 0) or ord_word}"
        stack[lvl] = label
        for deeper in range(lvl + 1, 5):
            stack.pop(deeper, None)
        out.append((m.start(), [stack[i] for i in range(5) if i in stack]))
    return out


def hierarchy_at(nodes, pos):
    path = []
    for start, p in nodes:
        if start < pos:
            path = p
        else:
            break
    return path


# ═══════════════════ 4/6/7) الاستخراج الكامل ═══════════════════

def extract_articles_v4(text: str):
    """يعيد (preamble, articles) — المكررة/المعدلة محفوظة، الفقرات مقسمة."""
    nodes = scan_hierarchy(text)
    matches = list(ARTICLE_RE.finditer(text))
    articles, seen = [], set()
    preamble = None

    for i, m in enumerate(matches):
        num_raw = m.group(1)
        verbal = m.group(2)
        suffix = (m.group(3) or "").strip()
        number = int(to_western_digits(num_raw)) if num_raw else verbal_to_int(verbal)
        if number <= 0:
            continue
        label_src = f"{number}{' ' + suffix if suffix else ''}"

        start, end = m.end(), matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = normalize_unicode(text[start:end].strip())
        if len(body) < 10:   # مواد الدستور الحقيقية قصيرة — لا نرفع الحد تعسفاً
            continue

        is_dup = bool(suffix) and ("مكرر" in suffix)
        key = (number, suffix)
        if key in seen:            # نفس الرقم والتاج مرتين = تكرار فعلي
            is_dup = True
        seen.add(key)

        amendment = None
        am = AMEND_RE.search(body)
        if am:
            amendment = am.group(0).strip()[:120]

        paragraphs = [p.strip() for p in re.split(r"\n+", body) if len(p.strip()) > 8]
        if len(paragraphs) <= 1:
            paragraphs = [p.strip() for p in re.split(r"(?<=\w)\s*[-–]\s*(?=\S)", body)
                          if len(p.strip()) > 8] or [body]

        articles.append({
            "article_number": number,
            "label": label_src,
            "text": body,
            "char_count": len(body),
            "paragraphs": paragraphs,
            "hierarchy_path": hierarchy_at(nodes, m.start()),
            "is_duplicate": is_dup,
            "amendment_note": amendment,
            "is_preamble": False,
        })

    # المقدمة بشروط واضحة: نص ≥100 حرف قبل أول مادة ويحوي عبارة افتتاحية
    if matches:
        head = normalize_unicode(text[:matches[0].start()].strip())
        openers = ["يرسم ما يلي", "رئيس الجمهورية", "مجلس الشعب",
                   "بناء على أحكام الدستور", "يهدف هذا", "صدر هذا"]
        if len(head) >= 100 and any(o in head for o in openers):
            preamble = {"article_number": 0, "label": "المقدمة", "text": head,
                        "char_count": len(head),
                        "paragraphs": [p for p in head.split("\n") if p.strip()],
                        "hierarchy_path": [], "is_duplicate": False,
                        "amendment_note": None, "is_preamble": True}

    articles.sort(key=lambda a: (a["is_preamble"] and -1 or a["article_number"]))
    return preamble, articles


def quality_report(selector_info, articles, preamble, skipped) -> tuple:
    """درجة جودة 0..1 مع أسباب — لا إسقاط صامت."""
    score, reasons = 0.35, []
    if selector_info:
        conf = min(0.25, selector_info["score"] / 8000)
        score += conf
        reasons.append(f"حاوية: {selector_info['length']} حرفاً و"
                       f"{selector_info['article_hits']} إشارة مادة")
    real = [a for a in articles if not a["is_preamble"]]
    if len(real) >= 3:
        score += 0.2; reasons.append(f"{len(real)} مواد")
    if any(a["hierarchy_path"] for a in real):
        score += 0.1; reasons.append("هرمية مكتشفة")
    if all(a["paragraphs"] for a in real[:5]):
        score += 0.1; reasons.append("فقرات مقسمة")
    if preamble:
        score += 0.05; reasons.append("مقدمة مستخرجة بشروطها")
    if skipped:
        score -= 0.1; reasons.append(f"{skipped} مقاطع skipped")
    if not any(a["article_number"] for a in articles):
        score -= 0.2; reasons.append("لا إشارة مواد في الحاوية")
    return round(min(max(score, 0.0), 1.0), 2), reasons


def extract_main_content(html: str, url: str = "") -> dict:
    """نفس توقيع v3 مع عقد أغنى — بلا أي print (سجلات فقط)."""
    if not html or len(html) < 400:
        return {"success": False, "error": "html_too_short"}

    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    picked = pick_container(soup)
    if not picked:
        return {"success": False, "error": "no_suitable_element", "title": title}

    selector, element, info = picked
    for tag in ("script", "style", "iframe", "form", "button", "nav",
                "header", "footer"):
        for junk in element.find_all(tag):
            junk.decompose()

    clean = normalize_unicode(element.get_text(separator="\n", strip=True))
    if len(clean) < 300:
        return {"success": False, "error": "content_too_short", "title": title}

    raw_matches = len(ARTICLE_RE.findall(clean))
    preamble, articles = extract_articles_v4(clean)
    skipped = max(0, raw_matches - len([a for a in articles if not a["is_preamble"]]))
    quality, reasons = quality_report(info, articles, preamble, skipped)

    if preamble:
        articles = [preamble] + articles
    html_hash = "sha256:" + hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()
    return {
        "success": True, "title": title, "clean_text": clean,
        "articles": articles, "article_count": len(articles),
        "used_selector": selector, "selector_info": info,
        "hierarchy_nodes": [p for _, p in scan_hierarchy(clean)],
        "quality_score": quality, "quality_reasons": reasons,
        "source_locator": {"url": url, "html_hash": html_hash},
        "text_length": len(clean), "error": None,
    }


def article_key(doc_key: str, art: dict) -> str:
    seed = f"{doc_key}|{art['article_number']}|{art['label']}|{art['text']}"
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _extract_title(soup) -> str:
    for tag in ("h1", "h2", "strong"):
        el = soup.find(tag)
        if el and len(el.get_text(strip=True)) > 15:
            return re.sub(r"\s*[-–]\s*(مكتبة|منتدى|صفحة).*?$", "",
                          el.get_text(strip=True), flags=re.I)
    if soup.title and len(soup.title.get_text(strip=True)) > 12:
        return re.sub(r"\s*[-–]\s*(مكتبة|منتدى|صفحة).*?$", "",
                      soup.title.get_text(strip=True), flags=re.I)
    return "وثيقة قانونية سورية"
