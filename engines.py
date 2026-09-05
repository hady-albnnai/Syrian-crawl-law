# -*- coding: utf-8 -*-
"""engines.py — كشف محركات المواقع واستخراج الروابط حسب المحرك.

وحدة محايدة (بلا استيراد من crawler/discovery — تتفادى الاستيراد الدائري):
الزاحف والاستكشاف والطيار الآلي يستوردون منها. دوال نقية قابلة للاختبار
بلا شبكة.

المحركات المدعومة:
  phpbb     — منتدى: الموضوعات /t\\d+، وترقيم الصفحات start=
  wordpress — المقالات /YYYY/MM/ أو ?p= أو /archives/، والترقيم paged= أو /page/N/
  generic   — عام: نص الرابط القانوني هو الإشارة، وترقيم عام page=/start=

«التعامل مع المصادر المكتشفة» = الزاحف يكشف المحرك لكل صفحة أثناء الزحف
ويختار مستخرج الروابط المناسب — لا أنماط منتدى محجوزة في الكود.
"""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# إشارة قانونية في نص الرابط أو في مساره — بوابة المرشحين للمصادر العامة.
# (البوابة النهائية تبقى legal_score في الاستخراج — هذه للترشيح فقط.)
LEGAL_ANCHOR_RE = re.compile(
    r"قانون|مرسوم|تشريعي|تشريع|قرار|تعليمات|نظام|لائحة|دستور|أصول|"
    r"الجريدة الرسمية|مواد|نافذ")
LEGAL_HREF_RE = re.compile(
    r"law|qanoon|qanun|marsom|decree|legal|tashri|jareeda", re.IGNORECASE)

_PHPBB_TOPIC = re.compile(r"/t\d+|viewtopic\.php\?.*t=\d+")
_PHPBB_PAGINATION = re.compile(r"start=")
_WP_POST = re.compile(r"/\d{4}/\d{2}/|[?&]p=\d+|/archives/")
_PAGINATION = re.compile(r"[?&](?:start|page|paged|pagenum|pg)=\d+|/page/\d+/")


def detect_engine(html: str) -> str:
    """يكشف محرك الموقع ليختار الزاحف مستخرج الروابط المناسب."""
    low = (html or "").lower()
    if "postbody" in low or "viewtopic" in low or "fa_ticker_content" in low:
        return "phpbb"
    if "wp-content" in low or "entry-content" in low or "wordpress" in low:
        return "wordpress"
    return "generic"


def is_legal_anchor(text: str, href: str = "") -> bool:
    """هل الرابط مرشح تشريعي بالنص أو بالمسار؟

    فحص المسار على path+query فقط — لا على المضيف («laws-blog.example» يحوي
    «law» وكان يسحب كل روابط الموقع: عطل كشفه الاختبار وأُصلح).
    """
    if LEGAL_ANCHOR_RE.search(text or ""):
        return True
    pr = urlparse(href or "")
    tail = (pr.path or "") + (f"?{pr.query}" if pr.query else "")
    return bool(LEGAL_HREF_RE.search(tail))


def same_host(url_a: str, url_b: str) -> bool:
    """نفس المضيف مع تجاهل www — الروابط الخارجية لا تُزحف ضمن المصدر."""
    na = urlparse(url_a).netloc.lower().removeprefix("www.")
    nb = urlparse(url_b).netloc.lower().removeprefix("www.")
    return bool(na) and na == nb


def _dedupe_cap(links: list, cap: int = 30) -> list:
    out = []
    for u in links:
        if u not in out:
            out.append(u)
        if len(out) >= cap:
            break
    return out


def extract_topic_links(html: str, base_url: str, engine: str = None) -> list:
    """روابط الوثائق/الموضوعات داخل صفحة قائمة — حسب المحرك."""
    engine = engine or detect_engine(html)
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        if engine == "phpbb":
            if _PHPBB_TOPIC.search(href):
                links.append(full)
        else:
            # روابط الترقيم ليست وثائق — تعالجها extract_pagination_links.
            if _PAGINATION.search(full):
                continue
            if engine == "wordpress":
                hit = _WP_POST.search(full) or is_legal_anchor(
                    a.get_text(" ", strip=True), href)
            else:  # generic وأي محرك غير معروف — الإشارة قانونية فقط
                hit = is_legal_anchor(a.get_text(" ", strip=True), href)
            if hit and same_host(full, base_url):
                links.append(full)
    return _dedupe_cap(links)


def extract_pagination_links(html: str, base_url: str, engine: str = None,
                             limit: int = 3) -> list:
    """روابط صفحات القائمة التالية — حسب المحرك."""
    engine = engine or detect_engine(html)
    soup = BeautifulSoup(html, "lxml")
    out = []

    if engine == "wordpress":
        nxt = soup.find("link", rel="next")
        if nxt and nxt.get("href"):
            out.append(urljoin(base_url, nxt["href"]))

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if engine == "phpbb":
            if _PHPBB_PAGINATION.search(href) and re.search(r"/f\d+|[?&]f=\d+", href):
                full = urljoin(base_url, href)
            else:
                continue
        else:
            if not _PAGINATION.search(href):
                continue
            full = urljoin(base_url, href)
            if not same_host(full, base_url):
                continue
        if full not in out:
            out.append(full)
        if len(out) >= limit:
            break
    return out
