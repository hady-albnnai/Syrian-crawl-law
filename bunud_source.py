"""bunud_source.py — مصدر «بنود» (bunud.ai/sy/laws): تشريعات سورية مرتّبة
بالمادة، بهوية صريحة (نوع/رقم/سنة) وحالة معلنة.

لماذا (B-2، 2026-09-19): قائمة الفجوات `missing1.txt` (100 صك مستهدَف غير
محصود، أعلاها م.ت 115/1953) لم تجد نصوصها في المصادر الحالية؛ أول بحث عن
115/1953 أعاد bunud.ai بنص كامل 122 مادة وهوية «القانون:115:1953».
خريطة الموقع تعلن ~1486 تشريعاً سورياً. robots.txt يسمح بالمسارات العامة.

الأسلوب كأسلوب ويبو: نحوّل الصفحة إلى HTML مصنّع يمشي بمسار الأنبوب
القياسي (نفس مستخرج المواد والبوابات) — لا مسار خاص. حالة الموقع
(«ملغى/ساري») تُحفظ كإشارة خارجية فقط (`source_status`) ولا تُكتب في
legal_status: حالتنا تُحسب من أدلتنا (المعيار الذهبي 5 ملغاة).
"""
import html as _html
import re

from law_identity import build_identity_key, _normalize_type

HOST = "www.bunud.ai"
SITEMAP_INDEX = "https://www.bunud.ai/sitemap.xml"
SECTION = "بنود — التشريعات السورية"
_LAW_URL_RE = re.compile(r"^https://www\.bunud\.ai/sy/laws/(?!categories/)[a-z0-9-]+/?$")
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
# صف «N · المادة N» ثم «#» ثم نص المادة حتى الصف التالي
# «N · المادة N» أو «N · مادة 1» (قِيس crawl_bunud 2026-09-19: النظام المحاسبي
# يكتبها بلا أل — كانت الصفحة تُرفض bunud_not_a_law_page). تُوحَّد إلى «المادة».
_ART_ROW_RE = re.compile(r"(\d+)\s*·\s*(?:ال)?(ماد[ةه]\s+[^\n]+)")
_HIER_RE = re.compile(r"^(الكتاب|الباب|الفصل|المبحث|المطلب)\s")
_TYPE_MAP = {"قانون": "القانون", "مرسوم تشريعي": "المرسوم التشريعي",
             "مرسوم": "المرسوم", "قرار": "القرار", "تعميم": "التعميم"}


def is_bunud_law(url: str) -> bool:
    return bool(_LAW_URL_RE.match((url or "").split("?")[0]))


def sitemap_law_urls(index_xml: str, http_get) -> list:
    """كل روابط /sy/laws/<slug> من خرائط الموقع الفرعية (laws/sy/N)."""
    urls = []
    for sm in _LOC_RE.findall(index_xml or ""):
        if "/sitemaps/laws/sy/" not in sm:
            continue
        try:
            body = http_get(sm)
        except Exception:
            continue
        urls.extend(u for u in _LOC_RE.findall(body or "") if is_bunud_law(u))
    return sorted(set(urls))


def _text_lines(page_html: str) -> list:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page_html, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = _html.unescape(t)
    return [ln.strip() for ln in t.split("\n") if ln.strip()]


def parse_law_page(page_html: str) -> dict:
    """{title, doc_type, number, year, source_status, articles:[(label,text)]}
    أو {} إن لم تكن صفحة تشريع."""
    m = _TITLE_RE.search(page_html or "")
    if not m:
        return {}
    title = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
    lines = _text_lines(page_html)
    meta = {}
    for i in range(1, len(lines)):
        if lines[i] in ("الدولة", "نوع التشريع", "الرقم", "السنة", "الحالة"):
            meta[lines[i]] = lines[i - 1]
    try:
        start = lines.index("المواد")
    except ValueError:
        return {}
    arts, cur = [], None
    for ln in lines[start + 1:]:
        if ln in ("#",):
            continue
        if ln.startswith("منصة تجمع المعرفة القانونية"):
            break
        r = _ART_ROW_RE.fullmatch(ln)
        if r:
            cur = ["ال" + r.group(2).strip(), []]
            arts.append(cur)
            continue
        if _HIER_RE.match(ln):
            # عنوان هرمي بين المواد: يُحفظ كمادة-عنوان فيلتقطه scan_hierarchy
            arts.append([ln, []])
            cur = None
            continue
        if cur is not None:
            cur[1].append(ln)
    if not any(not _HIER_RE.match(a[0]) for a in arts):
        return {}
    doc_type = _TYPE_MAP.get(meta.get("نوع التشريع", ""), None)
    # قِيس missing3: بنود يصنّف م.ت 115/1953 «قانون» بينما نصه يقول «هذا
    # المرسوم التشريعي» — النص أصدق من بطاقة الموقع؛ الإحالات تطلبه م.ت.
    # الدليل: المادة الأولى («يطلق على هذا المرسوم التشريعي اسم…») أو مادة
    # النشر الأخيرة («ينشر هذا المرسوم التشريعي») — لا وسط النص حيث يقول
    # «هذا القانون» بمعنى الاسم.
    edges = " ".join(arts[0][1][:2] + arts[-1][1][:2])
    if doc_type == "القانون" and re.search(
            r"(?:يطلق على|ينشر|يصدر) هذا المرسوم التشريعي", edges):
        doc_type = "المرسوم التشريعي"
        # العنوان يُصحَّح أيضاً وإلا قرأ مستخرج الهوية النوع الخاطئ منه
        title = re.sub(r"^(?:ال)?قانون\b", "المرسوم التشريعي", title, count=1)
    num = int(meta["الرقم"]) if meta.get("الرقم", "").isdigit() else None
    year = int(meta["السنة"]) if meta.get("السنة", "").isdigit() else None
    return {"title": title, "doc_type": doc_type, "number": num, "year": year,
            "source_status": meta.get("الحالة"),
            "articles": [(lab, "\n".join(body)) for lab, body in arts]}


def identity_of(parsed: dict) -> str | None:
    if parsed.get("doc_type") and parsed.get("number") and parsed.get("year"):
        return build_identity_key(_normalize_type(parsed["doc_type"]),
                                  parsed["number"], parsed["year"])
    return None


def to_pipeline_html(parsed: dict) -> str:
    """HTML مصنّع بنفس عقد ويبو: عنوان + ديباجة هوية + مادة لكل فقرة."""
    head = parsed["title"]
    if parsed.get("doc_type") and parsed.get("number") and parsed.get("year"):
        # سطر هوية صريح يقرأه مستخرج الهوية من الديباجة
        head_line = f"{parsed['doc_type']} رقم {parsed['number']} لعام {parsed['year']}"
    else:
        head_line = ""
    paras = []
    if head_line:
        paras.append(f"<p>{_html.escape(head_line)}</p>")
    for label, body in parsed["articles"]:
        if _HIER_RE.match(label):
            paras.append(f"<h3>{_html.escape(label)}</h3>")
            continue
        paras.append(f"<p>{_html.escape(label)}</p>")
        for ln in body.split("\n"):
            paras.append(f"<p>{_html.escape(ln)}</p>")
    # علامة لمستخرج المواد: المواد على أول السطر دائماً (لا قطع عند ذكر داخلي)
    return (f'<html><body data-articles="line-anchored"><article><div class="entry-content">'
            f"<h1>{_html.escape(head)}</h1>\n" + "\n".join(paras) +
            "\n</div></article></body></html>")


def as_pipeline_result(url: str, page_html: str) -> dict:
    parsed = parse_law_page(page_html)
    if not parsed:
        return {"ok": False, "error": "bunud_not_a_law_page"}
    if len(parsed["articles"]) < 1:
        return {"ok": False, "error": "bunud_no_articles"}
    return {"ok": True, "html": to_pipeline_html(parsed), "status": 200,
            "final_url": url, "source_status": parsed.get("source_status"),
            "identity_key": identity_of(parsed)}
