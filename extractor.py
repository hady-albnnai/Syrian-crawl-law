# -*- coding: utf-8 -*-
"""
extractor.py — v3.4 (v3.3 المستقرة + legal_score المحسوبة — دفعة P0)
"""

import re
from bs4 import BeautifulSoup
from config import BRANCH_KEYWORDS


def clean_text(text: str) -> str:
    if not text:
        return ""

    txt = re.sub(r'[ \t\u00a0]+', ' ', text)
    txt = re.sub(r'\n{3,}', '\n\n', txt)

    noise = [
        r"منقول عن.*?$", r"مع تحياتي.*?$", r"تحياتي.*?$", r"^رد:\s.*?$",
        r"اقتباس:.*?$", r"التواقيع.*?$", r"-{10,}.*?$", r"مشاركة رقم.*?$",
        r"تاريخ التسجيل.*?$", r"عدد المشاركات.*?$", r"مواضيع مماثلة.*?$",
        r"صلاحيات هذا المنتدى.*?$", r"^.{0,40}شارك في.*?$", r"^حجم الخط.*?$",
        r"^\s*صفحة \d+.*?$",
    ]
    for pattern in noise:
        txt = re.sub(pattern, "", txt, flags=re.MULTILINE | re.IGNORECASE)

    txt = re.sub(r'^ل(?=مرسوم|قانون)', 'الم', txt, flags=re.M)
    txt = re.sub(r'^الممرسوم', 'المرسوم', txt, flags=re.M)
    txt = re.sub(r'^\s*[-–—•]\s*', '', txt, flags=re.MULTILINE)

    # تنظيف الالتصاق النهائي
    replacements = {
        "مسجلونفي": "مسجلون في",
        "ال من عقدة": "المنعقدة",
        "يست في د": "يستفيد",
        "جراءمنفة": "جراء لمنفعة",
        "جراً لمنفة": "جراء لمنفعة",
        "بال م عنى": "بالمعنى",
        "جن دالأعد": "جند الأعد",
        "في جدولال": "في جدول ال",
        "النقا بة": "النقابة",
    }
    for old, new in replacements.items():
        txt = txt.replace(old, new)

    txt = re.sub(r'(\w)(في|من|على|إلى|عن|أن|أو|مع|إذا|بأن)(\w)', r'\1 \2 \3', txt)
    return txt.strip()


def extract_title(soup) -> str:
    for tag in ['h1', 'h2', 'strong']:
        el = soup.find(tag)
        if el and len(el.get_text(strip=True)) > 15:
            title = el.get_text(strip=True)
            title = re.sub(r"\s*-\s*(مكتبة|منتدى|صفحة| Syrian|موضوع).*?$", "", title, flags=re.I)
            title = re.sub(r"^حجم الخط:?\s*", "", title, flags=re.I)
            return title.strip()

    if soup.title:
        t = soup.title.get_text(strip=True)
        t = re.sub(r"\s*-\s*(مكتبة|منتدى|صفحة| Syrian).*?$", "", t, flags=re.I)
        t = re.sub(r"^حجم الخط:?\s*", "", t, flags=re.I)
        if len(t) > 12:
            return t.strip()
    return "وثيقة قانونية سورية"


SELECTORS = ["td.row2.postbody", "div.postbody", "td.postbody", "div.message", "article"]

def score_element(el) -> float:
    txt = el.get_text(" ", strip=True)
    n = len(txt)
    if n < 250: return -1
    guillemets = txt.count("»") * 500
    link_penalty = sum(len(a.get_text(strip=True)) for a in el.find_all("a")) * 2.0
    article_bonus = len(re.findall(r"الماد[ةه]", txt)) * 500
    return n + article_bonus - guillemets - link_penalty


def pick_best_element(soup):
    best_el, best_sel, best_score = None, None, -1
    for sel in SELECTORS:
        for el in soup.select(sel):
            score = score_element(el)
            if score > best_score:
                best_el, best_sel, best_score = el, sel, score
    return best_sel, best_el, round(best_score, 1)


ARTICLE_START = re.compile(
    r'(?:^|\n|\n\s{0,6}|:\s*|يلي:\s*|التالي:\s*|يصدر\s*\n*)'
    r'(?:الماد[ةه]|ماد[ةه]|المـادة)'
    r'\s*[/\(]?\s*'
    r'(\d+|[\u0660-\u0669]+|الأول|الاول|الثان|الثالث|الرابع|الخامس|'
    r'السادس|السابع|الثامن|التاسع|العاشر|الأولى|الاولى|الثانية|الثالثة)'
    r'(?:[ىة])?'
    r'\s*[\)\s/]*'
    r'(مكرر|مكررة|ثاني|ثالث|معدل)?',
    re.IGNORECASE | re.MULTILINE
)

ARABIC_ORDINALS = {k: str(v) for k, v in {
    "الأول": 1, "الاول": 1, "الأولى": 1, "الاولى": 1,
    "الثان": 2, "الثانية": 2, "الثالث": 3, "الثالثة": 3,
    "الرابع": 4, "الرابعة": 4, "الخامس": 5, "الخامسة": 5,
    "السادس": 6, "السادسة": 6, "السابع": 7, "السابعة": 7,
    "الثامن": 8, "الثامنة": 8, "التاسع": 9, "التاسعة": 9,
    "العاشر": 10, "العاشرة": 10,
}.items()}


def _to_western(s: str) -> str:
    table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return s.translate(table)


def extract_articles(text: str) -> list:
    if not text or len(text) < 150:
        return []

    text = clean_text(text)
    matches = list(ARTICLE_START.finditer(text))
    articles_dict = {}

    for match in matches:
        num_raw = match.group(1)
        suffix = (match.group(2) or "").strip()
        number_str = ARABIC_ORDINALS.get(num_raw, _to_western(num_raw))
        article_num = int(number_str)
        label = f"{article_num} {suffix}".strip()

        start = match.end()
        next_match = next((m for m in matches if m.start() > start), None)
        end = next_match.start() if next_match else len(text)

        body = clean_text(text[start:end].strip())

        if len(body) >= 20 and article_num not in articles_dict:
            articles_dict[article_num] = {
                "article_number": article_num,
                "label": label,
                "text": body,
                "char_count": len(body),
            }

    # منطق المادة الأولى (إذا بدأ النص بالمادة 2)
    if 1 not in articles_dict and 2 in articles_dict:
        first_match = next((m for m in matches if int(ARABIC_ORDINALS.get(m.group(1), _to_western(m.group(1)))) == 2), None)
        if first_match:
            preamble = clean_text(text[:first_match.start()].strip())
            if len(preamble) > 50:
                articles_dict[1] = {
                    "article_number": 1,
                    "label": "1",
                    "text": preamble,
                    "char_count": len(preamble),
                }

    articles = list(articles_dict.values())
    articles.sort(key=lambda x: x["article_number"])
    
    return articles


def extract_main_content(html: str, url: str = "") -> dict:
    if not html or len(html) < 400:
        return {"success": False, "error": "html_too_short"}

    soup = BeautifulSoup(html, "lxml")
    title = extract_title(soup)

    selector, element, score = pick_best_element(soup)
    if not element:
        return {"success": False, "error": "no_suitable_element", "title": title}

    for tag in ["script", "style", "iframe", "form", "button", "nav", "header", "footer"]:
        for junk in element.find_all(tag):
            junk.decompose()

    raw_text = element.get_text(separator="\n", strip=True)
    clean = clean_text(raw_text)

    print(f"   [DEBUG] أول 180 حرف:\n{clean[:180]}\n")

    if len(clean) < 300:
        return {"success": False, "error": "content_too_short", "title": title}

    articles = extract_articles(clean)

    return {
        "success": True,
        "title": title,
        "clean_text": clean,
        "articles": articles,
        "article_count": len(articles),
        "used_selector": selector,
        "element_score": score,
        "text_length": len(clean),
        "error": None,
    }


def is_legal_content(text: str, title: str = "") -> bool:
    if not text or len(text) < 180: return False
    full = (title + " " + text).lower()
    if re.search(r"الماد[ةه]\s*[/\d]", text): return True
    strong = ["يرسم ما يلي", "المرسوم التشريعي", "القانون رقم", "مجلس الشعب",
              "الجريدة الرسمية", "رئيس الجمهورية", "بناء على أحكام الدستور"]
    hits = sum(1 for s in strong if s in full)
    return hits >= 1 or len(text) > 1000


def legal_score(text: str, title: str = "") -> float:
    """درجة قانونية شفافة 0..100 تُحفظ في documents.legal_score.

    أضيفت في دفعة P0 (2026-09-05) لتحل محل الرقم الثابت الوهمي 85.0 الذي كان
    يُحفظ لكل وثيقة — مخالفة صريحة لقاعدة «لا رقم بلا قياس» في الدستور.
    المركبات: إشارات «المادة» (+40)، عبارات تشريعية قوية (حتى +30)،
    طول النص (حتى +20)، تكرار المواد (حتى +10).
    """
    if not text:
        return 0.0
    full = (title + " " + text).lower()
    score = 0.0
    if re.search(r"الماد[ةه]\s*[/\d٠-٩]", text):
        score += 40.0
    strong = ["يرسم ما يلي", "المرسوم التشريعي", "القانون رقم", "مجلس الشعب",
              "الجريدة الرسمية", "رئيس الجمهورية", "بناء على أحكام الدستور"]
    score += min(30.0, 10.0 * sum(1 for s in strong if s in full))
    score += min(20.0, len(text) / 1000.0 * 20.0)
    score += min(10.0, 2.0 * len(re.findall(r"الماد[ةه]\s*[/\d٠-٩]+", text)))
    return round(min(score, 100.0), 1)


def detect_branch(text: str, section_name: str = "") -> tuple:
    tl = text.lower()
    sec = (section_name or "").lower()
    scores = {b: 0 for b in BRANCH_KEYWORDS.keys()}

    for branch, kws in BRANCH_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in tl: scores[branch] += 2
            if kw.lower() in sec: scores[branch] += 5

    if re.search(r"عقوب|جناي|جنح|جريم|خطف|إرهاب|عقوبات", tl):
        scores["penal_law"] += 15
    if re.search(r"مدني|عقد|التزام|ملكية|حقوق عينية", tl):
        scores["civil_law"] += 10
    if re.search(r"زواج|طلاق|نسب|حضانة|وراثة|أحوال شخصية", tl):
        scores["personal_status"] += 12

    best = max(scores, key=scores.get)
    confidence = round(min(0.95, scores[best] / 4.0), 2) if scores[best] > 0 else 0.45
    return best, confidence


# ====================== الاختبار ======================
if __name__ == "__main__":
    from fetcher import fetch
    print("🚀 اختبار extractor.py v3.3 (النسخة النهائية)\n" + "="*95)

    tests = [
        ("https://law-library.syriaforums.net/t25-قانون-العقوبات-السوري", "القانون الجزائي"),
        ("https://law-library.syriaforums.net/t1950-المرسوم-التشريعي-رقم-20-لعام-2013", "القانون الجزائي"),
        ("https://law-library.syriaforums.net/t292-قانون-تنظيم-مهنة-المحاماة-لعام-2010", "القانون المدني"),
    ]

    for url, sec in tests:
        print(f"\n{'─'*130}")
        r = fetch(url)
        if not r.get("ok", False):
            print("❌ فشل الجلب")
            continue

        result = extract_main_content(r["html"], url)
        if not result["success"]:
            print(f"❌ فشل الاستخراج: {result.get('error')}")
            continue

        branch, conf = detect_branch(result["clean_text"], sec)
        legal = is_legal_content(result["clean_text"], result["title"])

        print(f"العنوان     : {result['title']}")
        print(f"Selector     : {result['used_selector']} (score={result['element_score']})")
        print(f"الطول        : {result['text_length']} حرف")
        print(f"عدد المواد   : {result['article_count']}")
        print(f"الفرع        : {branch} (ثقة: {conf})")
        print(f"قانوني؟      : {'✅ نعم' if legal else '❌ لا'}")

        if result["articles"]:
            print(f"\nأول 8 مواد:")
            for art in result["articles"][:8]:
                preview = art['text'][:75].replace('\n', ' ')
                print(f"   ▸ المادة {art['label']:6} ({art['char_count']} حرف) | {preview}...")