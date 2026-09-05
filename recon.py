# -*- coding: utf-8 -*-
"""
recon.py — بوت الاستطلاع (المرحلة 0)
مشروع: نظام الأرشفة القانونية السورية
الهدف: فهم بنية الموقع قبل بناء الزاحف الحقيقي.
يزور عدداً محدوداً من الصفحات فقط، بأدب، ولا يخزن أي محتوى في قاعدة بيانات.
"""

import sys
import os
import re
import json
import time
import random
from collections import Counter
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# --- إصلاح طباعة العربية على ويندوز ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ══════════════════════════════════════════════════════════
#  1) الإعدادات  (كل شيء قابل للتعديل من هنا فقط)
# ══════════════════════════════════════════════════════════

BASE_URL   = "https://law-library.syriaforums.net/"
USER_AGENT = "SyrianLawResearchBot/0.1 (reconnaissance; academic legal archiving)"

DELAY_MIN, DELAY_MAX = 2.0, 4.0   # التأخير المهذب بين الطلبات (ثانية)
TIMEOUT              = 25         # مهلة انتظار الرد
RETRIES              = 3          # عدد المحاولات عند الفشل

SAMPLE_FORUMS = 3    # كم قسماً نعاين
SAMPLE_TOPICS = 3    # كم موضوعاً نعاين

OUT_DIR  = "recon_output"
HTML_DIR = os.path.join(OUT_DIR, "html")


# اختيار محرك تحليل HTML (lxml أسرع، وإن لم يوجد نستخدم المدمج)
try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"


# ══════════════════════════════════════════════════════════
#  2) أدوات الروابط
# ══════════════════════════════════════════════════════════

TRACKING_PARAMS = {
    "sid", "session_id", "s", "highlight", "ref", "fb_action_ids",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
}

def normalize_url(url: str) -> str:
    """تطبيع الرابط: حذف #، توحيد الحروف، حذف معاملات التتبع."""
    url, _ = urldefrag(url)                     # احذف ما بعد #
    p = urlparse(url)
    netloc = p.netloc.lower()
    query = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING_PARAMS]
    query.sort()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((p.scheme.lower(), netloc, path, "", urlencode(query), ""))


def url_signature(url: str) -> str:
    """بصمة الرابط: نستبدل كل رقم بحرف N لنكتشف الأنماط المتكررة.
    مثال: /t123-قانون  ->  /tN-*"""
    p = urlparse(url)
    path = re.sub(r"\d+", "N", p.path)
    path = re.sub(r"[^\x00-\x7F]+", "*", path)   # نستبدل العربي بـ * لتوحيد البصمة
    q = "?" + re.sub(r"\d+", "N", p.query) if p.query else ""
    return path + q


def classify_url(url: str) -> str:
    """تخمين نوع الصفحة من شكل الرابط (أنماط منتديات Forumotion)."""
    p = urlparse(url).path.lower()
    if re.search(r"/t\d+p\d+", p):     return "topic_page"     # صفحة داخل موضوع
    if re.search(r"/f\d+p\d+", p):     return "forum_page"     # صفحة داخل قسم
    if re.search(r"/t\d+", p):         return "topic"          # موضوع
    if re.search(r"/f\d+", p):         return "forum"          # قسم
    if re.search(r"/c\d+", p):         return "category"       # فئة
    if re.search(r"/u\d+", p):         return "user"           # عضو
    if p in ("", "/", "/index.htm", "/forum.htm"): return "home"
    if any(k in p for k in ("login", "register", "profile", "search", "post",
                            "privmsg", "memberlist", "calendar", "faq", "rules")):
        return "system"
    return "other"


# ══════════════════════════════════════════════════════════
#  3) الجالب المهذب
# ══════════════════════════════════════════════════════════

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "ar,en-US;q=0.8,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml",
})

def polite_sleep():
    t = random.uniform(DELAY_MIN, DELAY_MAX)
    time.sleep(t)


def fetch(url: str) -> dict:
    """جلب صفحة مع إعادة محاولة تصاعدية واكتشاف الترميز."""
    for attempt in range(1, RETRIES + 1):
        try:
            t0 = time.time()
            r = SESSION.get(url, timeout=TIMEOUT)
            ms = int((time.time() - t0) * 1000)

            declared = r.encoding
            guessed  = r.apparent_encoding
            # requests يخمّن ISO-8859-1 خطأً كثيراً مع العربية
            if not declared or declared.lower() in ("iso-8859-1", "ascii"):
                r.encoding = guessed or "utf-8"

            return {
                "ok": True, "status": r.status_code, "html": r.text,
                "ms": ms, "bytes": len(r.content), "final_url": r.url,
                "encoding_declared": declared, "encoding_guessed": guessed,
                "encoding_used": r.encoding,
            }
        except Exception as e:
            wait = 2 ** attempt
            print(f"      [!] محاولة {attempt}/{RETRIES} فشلت ({type(e).__name__}) — انتظار {wait} ثانية")
            time.sleep(wait)
    return {"ok": False, "status": None, "html": "", "error": "failed_after_retries"}


# ══════════════════════════════════════════════════════════
#  4) تحليل المحتوى
# ══════════════════════════════════════════════════════════

NOISE_TAGS = ["script", "style", "noscript", "iframe", "svg", "form", "select"]

def strip_noise(soup):
    for t in soup.find_all(NOISE_TAGS):
        t.decompose()
    return soup


def describe(tag) -> str:
    """وصف مختصر للعنصر ليساعدنا في كتابة الـ selector لاحقاً."""
    name = tag.name
    idv = tag.get("id")
    cls = tag.get("class")
    s = name
    if idv:
        s += f"#{idv}"
    if cls:
        s += "." + ".".join(cls[:3])
    return s


def content_candidates(soup, top_n=6):
    """خوارزمية كثافة النص:
    كثافة = (عدد الحروف) / (عدد الوسوم بالداخل + 1)
    الحاوية التي تحوي نصاً كثيراً ووسوماً قليلة = هي المحتوى الحقيقي."""
    out = []
    for tag in soup.find_all(["div", "td", "article", "section", "main"]):
        text = tag.get_text(" ", strip=True)
        n_chars = len(text)
        if n_chars < 250:
            continue
        n_tags = len(tag.find_all(True))
        n_links = len(tag.find_all("a"))
        link_text = sum(len(a.get_text(strip=True)) for a in tag.find_all("a"))
        link_ratio = round(link_text / n_chars, 3) if n_chars else 1.0
        out.append({
            "selector_hint": describe(tag),
            "chars": n_chars,
            "inner_tags": n_tags,
            "density": round(n_chars / (n_tags + 1), 1),
            "links": n_links,
            "link_text_ratio": link_ratio,   # كلما قلّ = نص حقيقي وليس قائمة روابط
            "preview": text[:120],
        })
    out.sort(key=lambda x: x["density"], reverse=True)
    return out[:top_n]


LEGAL_PATTERNS = {
    "مواد_مرقمة":      r"الماد[ةه]\s*[\(]?\s*[\d\u0660-\u0669]",
    "مواد_بالحروف":    r"الماد[ةه]\s+(الأولى|الثانية|الثالثة|الرابعة|الخامسة)",
    "صيغة_إصدار":      r"(يرسم\s+ما\s+يلي|يصدر\s+القانون|على\s+أحكام\s+الدستور|أقره\s+مجلس\s+الشعب)",
    "تعريف_تشريع":     r"((القانون|المرسوم\s+التشريعي|المرسوم)\s+رقم\s*[\d\u0660-\u0669]+)",
    "جهات_رسمية":      r"(محكمة\s+النقض|مجلس\s+الشعب|الجريدة\s+الرسمية|رئيس\s+الجمهورية|وزارة\s+العدل)",
    "تقسيمات":         r"(الباب\s+ال|الفصل\s+ال|الكتاب\s+ال)",
    "اجتهاد":          r"(قرار\s+رقم|أساس\s+رقم|الغرفة\s+ال|قررت\s+المحكمة)",
    "نماذج":           r"(صيغة\s+|نموذج\s+|استدعاء\s+|لائحة\s+دعوى|عقد\s+)",
}

def legal_signals(text: str) -> dict:
    res = {}
    for name, pat in LEGAL_PATTERNS.items():
        res[name] = len(re.findall(pat, text))
    return res


def collect_links(soup, page_url):
    """جمع كل الروابط الداخلية + نصوصها."""
    host = urlparse(BASE_URL).netloc.lower()
    links = []
    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if raw.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = normalize_url(urljoin(page_url, raw))
        if urlparse(full).netloc.lower() != host:
            continue
        links.append({
            "url": full,
            "text": " ".join(a.get_text(" ", strip=True).split())[:90],
            "type": classify_url(full),
            "signature": url_signature(full),
        })
    return links


# ══════════════════════════════════════════════════════════
#  5) البرنامج الرئيسي
# ══════════════════════════════════════════════════════════

def save_html(name, html):
    os.makedirs(HTML_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80]
    path = os.path.join(HTML_DIR, safe + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def analyze_page(url, label):
    print(f"\n  → [{label}] {url}")
    polite_sleep()
    r = fetch(url)
    if not r["ok"] or r["status"] != 200:
        print(f"      [X] فشل — الحالة: {r.get('status')}")
        return {"url": url, "label": label, "ok": False, "status": r.get("status")}

    soup = strip_noise(BeautifulSoup(r["html"], PARSER))
    text = soup.get_text(" ", strip=True)
    links = collect_links(soup, url)
    cands = content_candidates(soup)
    signals = legal_signals(text)
    saved = save_html(f"{label}_{urlparse(url).path or 'home'}", r["html"])

    print(f"      [OK] {r['status']} | {r['ms']} ms | {r['bytes']//1024} KB "
          f"| ترميز: {r['encoding_used']} | نص: {len(text)} حرف | روابط: {len(links)}")
    print(f"      إشارات قانونية: " +
          ", ".join(f"{k}={v}" for k, v in signals.items() if v > 0) or "      لا توجد إشارات")
    if cands:
        print(f"      أفضل حاوية محتوى: {cands[0]['selector_hint']} "
              f"(كثافة {cands[0]['density']}، {cands[0]['chars']} حرف)")

    return {
        "url": url, "label": label, "ok": True,
        "status": r["status"], "response_ms": r["ms"], "size_bytes": r["bytes"],
        "encoding_declared": r["encoding_declared"],
        "encoding_guessed": r["encoding_guessed"],
        "encoding_used": r["encoding_used"],
        "title": (soup.title.get_text(strip=True) if soup.title else ""),
        "text_length": len(text),
        "links_count": len(links),
        "legal_signals": signals,
        "content_candidates": cands,
        "saved_html": saved,
        "_links": links,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 70)
    print("  بوت الاستطلاع — مشروع الأرشفة القانونية السورية")
    print(f"  الهدف: {BASE_URL}")
    print(f"  محرك التحليل: {PARSER} | التأخير: {DELAY_MIN}-{DELAY_MAX}s")
    print("=" * 70)

    profile = {
        "base_url": BASE_URL,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parser": PARSER,
    }

    # ---- (1) robots.txt ----
    print("\n[1/4] فحص robots.txt ...")
    robots_url = urljoin(BASE_URL, "/robots.txt")
    rr = fetch(robots_url)
    robots_txt = rr["html"] if rr["ok"] and rr["status"] == 200 else ""
    print(f"      الحالة: {rr.get('status')}")
    if robots_txt.strip():
        print("      --- محتوى robots.txt ---")
        for line in robots_txt.strip().splitlines()[:25]:
            print("      " + line)
    else:
        print("      لا يوجد robots.txt أو فارغ (نعتبره مسموحاً مع بقاء الأدب في الزحف)")

    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    can_home = rp.can_fetch(USER_AGENT, BASE_URL) if robots_txt.strip() else True
    profile["robots"] = {"raw": robots_txt[:3000], "allowed_home": can_home}

    # ---- (2) الصفحة الرئيسية ----
    print("\n[2/4] تحليل الصفحة الرئيسية ...")
    home = analyze_page(BASE_URL, "home")
    if not home.get("ok"):
        print("\n[X] تعذّر الوصول للصفحة الرئيسية. أوقفنا الاستطلاع.")
        with open(os.path.join(OUT_DIR, "site_profile.json"), "w", encoding="utf-8") as f:
            json.dump({**profile, "home": home}, f, ensure_ascii=False, indent=2)
        return

    all_links = home.pop("_links")
    profile["home"] = home

    # ---- (3) أنماط الروابط + أقسام المنتدى ----
    print("\n[3/4] استخراج أنماط الروابط وأقسام المنتدى ...")
    sig_counter = Counter(l["signature"] for l in all_links)
    type_counter = Counter(l["type"] for l in all_links)

    print("      توزيع أنواع الروابط:")
    for t, c in type_counter.most_common():
        print(f"        - {t:12s} : {c}")

    print("      أكثر 12 نمط رابط تكراراً:")
    for sig, c in sig_counter.most_common(12):
        print(f"        {c:4d} × {sig}")

    # أقسام المنتدى = ذهب للتصنيف لاحقاً
    seen = set()
    forum_sections = []
    for l in all_links:
        if l["type"] in ("forum", "category") and l["url"] not in seen and l["text"]:
            seen.add(l["url"])
            forum_sections.append({"title": l["text"], "url": l["url"], "type": l["type"]})

    print(f"\n      عدد الأقسام المكتشفة: {len(forum_sections)}")
    for s in forum_sections[:30]:
        print(f"        • {s['title']}  ->  {urlparse(s['url']).path}")

    profile["link_type_distribution"] = dict(type_counter)
    profile["top_url_signatures"] = sig_counter.most_common(25)
    profile["forum_sections"] = forum_sections

    # ---- (4) عيّنات من الأقسام والمواضيع ----
    print("\n[4/4] معاينة عيّنات (أقسام ثم مواضيع) ...")
    samples = []
    topic_urls = []

    for s in forum_sections[:SAMPLE_FORUMS]:
        res = analyze_page(s["url"], "forum")
        if res.get("ok"):
            for l in res.pop("_links", []):
                if l["type"] == "topic":
                    topic_urls.append(l["url"])
            samples.append(res)

    # لو لم نجد مواضيع داخل الأقسام، نبحث في روابط الصفحة الرئيسية
    if not topic_urls:
        topic_urls = [l["url"] for l in all_links if l["type"] == "topic"]

    uniq_topics, seen_t = [], set()
    for u in topic_urls:
        if u not in seen_t:
            seen_t.add(u)
            uniq_topics.append(u)

    print(f"\n      عدد المواضيع المكتشفة: {len(uniq_topics)}")

    for u in uniq_topics[:SAMPLE_TOPICS]:
        res = analyze_page(u, "topic")
        res.pop("_links", None)
        samples.append(res)

    profile["samples"] = samples

    # ---- التوصية بالـ selector ----
    topic_samples = [s for s in samples if s.get("label") == "topic" and s.get("ok")]
    hint_counter = Counter()
    for s in topic_samples:
        for c in s["content_candidates"][:3]:
            hint_counter[c["selector_hint"]] += 1
    profile["recommended_content_selectors"] = hint_counter.most_common(8)

    print("\n" + "=" * 70)
    print("  التوصية الأولية لحاوية نص الموضوع:")
    for h, c in hint_counter.most_common(8):
        print(f"    {c} × {h}")
    print("=" * 70)

    # ---- الحفظ ----
    out_json = os.path.join(OUT_DIR, "site_profile.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"\n[✓] انتهى الاستطلاع.")
    print(f"    ملف الملف التعريفي : {out_json}")
    print(f"    نسخ HTML المحفوظة  : {HTML_DIR}")
    print(f"    إجمالي الصفحات المزارة: {1 + len([s for s in samples if s.get('ok')])}")


if __name__ == "__main__":
    main()