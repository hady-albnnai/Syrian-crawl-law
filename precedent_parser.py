"""precedent_parser.py — محلل استشهادات الاجتهاد القضائي السوري (ف٣ / أ-2).

بلا شبكة. يحوّل نصاً (صفحة/خيط/ملف) إلى قائمة `Citation` كل منها:
هوية القرار (المحكمة/الدائرة/الغرفة/نوع الدعوى/رقم القرار/الأساس/الطعن/التاريخ)
+ نص المبدأ إن وُجد + الإسناد (المنشور/السنة/العدد/الصفحة/رقم القاعدة)
+ السطر الأصلي حرفياً + ثقة التحليل.

الأشكال المدعومة مأخوذة حرفياً من نصوص حقيقية قِيست 2026-09-21
(docs/PRECEDENTS-RESEARCH-2026-09-21.md §3):
  1 مجلة المحامون البنيوية:  «القاعدة: 52 / القضية : 2106 أساس لعام 2008 / قرار : 1904 لعام 2008 / تاريخ : 30/6/2008 / المبدأ: …»
  2 الاستشهاد السطري:        «نقض سوري – الغرفة المدنية الثالثة – قرار 1890 – أساس 2914 – تاريخ 9/11/1997 – سجلات محكمة النقض»
                              «نقض سوري هيئة عامة أساس 328 قرار 167 تاريخ 6/11/1994 – المصدر : مجلة المحامون العددان 11 – 12 لعام 1994»
  3 الموسوعات:               «قرار 1582 / 2002 – أساس 1916 – محكمة النقض – الدوائر المدنية – سورية قاعدة 137 – م. القانون 2002»
  6 الإدارية العليا:          «(القرار رقم 671 في الطعن 1391 لعام 1995 مجموعة المبادئ القانونية التي قررتها المحكمة الإدارية العليا صفحة 57 لعام 1995)»
  7 التبويب بالمادة:          «(جنحة أساس 2215 / 980 قرار 293 تاريخ 8 / 2 / 1981)»
                              «(نقض سوري ـ عسكرية أساس 1807 قرار 3 تاريخ 10 / 6 / 1981)»

القواعد:
- لا يُخترع شيء: حقل لم يرد = None. الثقة تُحسب من اكتمال (رقم قرار، أساس/تاريخ، جهة).
- «القاعدة/قاعدة N» رقم تحريري (المحامون/الموسوعات) ⇒ إسناد فقط، لا هوية.
- سنة الأساس المختصرة «980» ⇒ 1980 (قرن 20 إن < 100 وأكبر من 30، وإلا 2000+).
- اسم الغرفة يُطبَّع إلى الدائرة الأم (مدنية/جزائية/شرعية) مع حفظ الاسم كما ورد.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict

from extractor_v4 import to_western_digits

# ---------------------------------------------------------------- تطبيع
_DASH = r"[-–—ـ]"
_SEP = r"\s*[/\\\-ـ.]\s*"


def _norm(s: str) -> str:
    """تطبيع **حافظ للطول** (حرف ↔ حرف) حتى تصلح مواضع المطابقة لقصّ النص الأصلي.
    النص المخزَّن (المبدأ/السطر الحرفي) يبقى أصلياً؛ التطبيع للمطابقة فقط."""
    s = to_western_digits(s or "")
    s = s.replace("\u200f", " ").replace("\u200e", " ").replace("\xa0", " ")
    s = re.sub(r"[إأآ]", "ا", s)
    s = s.replace("ى", "ي")
    return s


# الغرفة → الدائرة الأم (§8-4)
CHAMBER_DIVISION = {
    "المدنية": "مدنية", "الايجارية": "مدنية", "العمالية": "مدنية", "التجارية": "مدنية",
    "الجزائية": "جزائية", "الجنائية": "جزائية", "الجنحية": "جزائية", "الجمركية": "جزائية",
    "الاقتصادية": "جزائية", "العسكرية": "جزائية", "الاحداث": "جزائية",
    "الشرعية": "شرعية", "الروحية": "شرعية", "المذهبية": "شرعية",
}
_ORDINAL = r"(?:الاولي|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة)"
_CHAMBER_RE = re.compile(
    rf"(?:الغرفة|الدوائر|الدائرة)\s+(?P<name>{'|'.join(map(re.escape, CHAMBER_DIVISION))})?\s*(?P<ord>{_ORDINAL})?")
# نوع الدعوى بدل الغرفة (الشكل 7)
CASE_KIND_DIVISION = {
    "جنحة": "جزائية", "جناية": "جزائية", "احداث": "جزائية", "عسكرية": "جزائية",
    "امن اقتصادي": "جزائية", "جمركية": "جزائية", "مخاصمة": "مدنية", "شرعية": "شرعية",
    "ايجارية": "مدنية", "عمالية": "مدنية", "مدنية": "مدنية", "تجارية": "مدنية",
}
_CASE_KIND_RE = re.compile(
    r"(?<![\u0621-\u064A])(?P<k>" + "|".join(sorted(map(re.escape, CASE_KIND_DIVISION), key=len, reverse=True))
    + r")(?![\u0621-\u064A])")

_HAYA_RE = re.compile(r"هيئة\s+عامة|الهيئة\s+العامة")
_ADMIN_RE = re.compile(r"(?:المحكمة\s+)?الادارية\s+العليا")
_UNIFY_RE = re.compile(r"دائرة\s+توحيد\s+المبادئ")
_CONST_RE = re.compile(r"المحكمة\s+الدستورية")
_NAQD_RE = re.compile(r"نقض\s+سوري|محكمة\s+النقض|محاكم\s+النقض|النقض")
_MUKHASAMA_RE = re.compile(r"مخاصمة")

# أرقام
_NUM = r"(?P<{n}>\d{{1,6}})"
_YR = r"(?P<{n}>\d{{2,4}})"
_DEC_RE = re.compile(rf"(?:(?:ال)?قرار\s+(?:جنحي|جنائي|مدني|شرعي|عسكري)\s+(?:رقم\s+)?|(?:ال)?قرار\s+رقم|قرار\s*:?|القرار|قرر)\s*/?\s*{_NUM.format(n='dn')}\s*/?\s*(?:{_SEP}|لعام|لسنة|/)?\s*{_YR.format(n='dy')}?(?!\d)")
# «نقض سوري رقم 483 أساس 486» (سجلات النقض) — الرقم قبل «أساس» هو رقم القرار
_DEC_BEFORE_BASIS_RE = re.compile(rf"(?:رقم|نقض(?:\s+(?:مدني|جزائي|شرعي|جنحي|جنائي|تجاري|عمالي|ايجاري))?(?:\s+سوري)?)\s+{_NUM.format(n='dn')}\s+(?:رقم\s+)?اساس")
_BASIS_RE = re.compile(rf"(?:القضية\s*:?\s*)?(?:{_NUM.format(n='bn0')}\s+)?(?:رقم\s+)?اساس\s*:?\s*/?\s*(?:{_NUM.format(n='bn')}|بدون)?\s*(?:{_SEP}|لعام|لسنة)?\s*{_YR.format(n='by')}?(?!\d)")
_APPEAL_RE = re.compile(rf"في\s+الطعن\s*/?\s*{_NUM.format(n='an')}\s*/?\s*(?:لعام|لسنة)?\s*{_YR.format(n='ay')}?(?!\d)")
_DATE_RE = re.compile(rf"(?:ب?تاريخ|المؤرخ\s+في)\s*:?\s*(?P<d>\d{{1,2}}){_SEP}(?P<m>\d{{1,2}}){_SEP}(?P<y>\d{{3,4}})(?!\d)")
# تاريخ بترتيب سنة/شهر/يوم («تاريخ 2025/07/22» — مجلة التحكيم السورية)
_DATE_YMD_RE = re.compile(rf"(?:ب?تاريخ|المؤرخ\s+في)\s*:?\s*(?P<y>\d{{4}}){_SEP}(?P<m>\d{{1,2}}){_SEP}(?P<d>\d{{1,2}})(?!\d)")
_BARE_DATE_RE = re.compile(rf"(?<!\d)(?P<d>\d{{1,2}}){_SEP}(?P<m>\d{{1,2}}){_SEP}(?P<y>\d{{4}})(?!\d)")

# الإسناد
_PUBS = [
    ("المحامون", re.compile(r"مجلة\s+المحامون|محامون\s+العدد|المحامون\s+(?:العدد|\d{4})|م\.\s*المحامون")),
    ("القانون", re.compile(r"مجلة\s+القانون|م\.?\s*القانون|\{\s*قانون\s+\d{4}")),
    ("سجلات النقض", re.compile(r"سجلات\s+(?:محكمة\s+)?النقض")),
    ("مجموعة المبادئ الإدارية", re.compile(r"مجموعة\s+المبادئ\s+القانونية")),
    ("عطري", re.compile(r"عطري")),
    ("كيلاني", re.compile(r"كيلاني")),
    ("سنان", re.compile(r"عبد\s+الناصر\s+سنان|جرائم\s+الامن\s+الاقتصادي")),
    ("طعمة", re.compile(r"شفيق\s+طعمة")),
    ("دركزلي", re.compile(r"دركزلي")),
    ("حمورابي", re.compile(r"حمورابي")),
    ("مجموعة الاجتهادات الجزائية", re.compile(r"مجموعة\s+الاجتهادات\s+الجزائية")),
]
_RULE_RE = re.compile(r"(?:القاعدة|قاعدة)\s*:?\s*(?P<r>\d{1,5})")
_PAGE_RE = re.compile(r"(?:الصفحة|صفحة|ص)\s*:?\s*(?P<p>\d{1,4})")
_ISSUE_RE = re.compile(r"العدد(?:ان|ين)?\s*/?\s*(?P<i>\d{1,2}(?:\s*[-–ـ]\s*\d{1,2})?)\s*/?")
_PUBYEAR_RE = re.compile(r"(?:لعام|لسنة|عام)\s*(?P<y>\d{4})")
_PRINCIPLE_LINE_RE = re.compile(r"المبدا\s*:?\s*(?P<t>[^\n]+)")


@dataclass
class Citation:
    court: str | None = None          # نقض | هيئة_عامة_نقض | ادارية_عليا | توحيد_مبادئ | دستورية
    division: str | None = None       # مدنية | جزائية | شرعية
    chamber_raw: str | None = None
    case_kind: str | None = None
    decision_number: str | None = None
    decision_year: int | None = None
    basis_number: str | None = None
    basis_year: int | None = None
    appeal_number: str | None = None
    decision_date: str | None = None  # ISO
    publication: str | None = None
    pub_year: int | None = None
    pub_issue: str | None = None
    pub_page: str | None = None
    rule_number: str | None = None
    title_keywords: str | None = None
    principle_text: str | None = None
    citation_raw: str = ""
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def identity_key(self) -> str | None:
        """محكمة|رقم القرار|السنة|الأساس — None إن نقصت الهوية الدنيا."""
        if not (self.court and self.decision_number):
            return None
        year = self.decision_year or (int(self.decision_date[:4]) if self.decision_date else None)
        if not year and not self.basis_number:
            return None
        return f"{self.court}|{self.decision_number}|{year or ''}|{self.basis_number or ''}"

    def is_exportable(self) -> bool:
        return self.identity_key() is not None and _principle_ok(self)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["identity_key"] = self.identity_key()
        return d


MIN_PRINCIPLE = 40          # مبدأ حر
MIN_PRINCIPLE_TITLED = 15   # مبدأ تحت سطر كلمات مفتاحية (المحامون: «الشك يفسر لمصلحة المتهم .»)


def _principle_ok(c: "Citation") -> bool:
    t = (c.principle_text or "").strip()
    return len(t) >= (MIN_PRINCIPLE_TITLED if c.title_keywords else MIN_PRINCIPLE)


def _year(v: str | None) -> int | None:
    if not v:
        return None
    y = int(v)
    if y >= 1000:
        return y if 1920 <= y <= 2100 else None
    if y < 100:                       # «980» لا تصل هنا؛ «08» نادرة
        return 2000 + y if y <= 30 else 1900 + y
    return 1000 + y if y >= 900 else None  # «980» ⇒ 1980


def _iso(d: str, m: str, y: str) -> str | None:
    dd, mm, yy = int(d), int(m), int(y)
    if 900 <= yy <= 999:   # ترميز كيلاني «965» = 1965
        yy += 1000
    if not (1 <= dd <= 31 and 1 <= mm <= 12 and 1920 <= yy <= 2100):
        return None
    return f"{yy:04d}-{mm:02d}-{dd:02d}"


def parse_citation(raw: str) -> Citation:
    """يحلل سطراً/مقطعاً واحداً يُفترض أنه استشهاد واحد."""
    c = Citation(citation_raw=raw.strip())
    t = _norm(raw)

    # الجهة
    if _UNIFY_RE.search(t):
        c.court = "توحيد_مبادئ"
    elif _ADMIN_RE.search(t) or _APPEAL_RE.search(t):
        c.court = "ادارية_عليا"
    elif _CONST_RE.search(t):
        c.court = "دستورية"
    elif _HAYA_RE.search(t):
        c.court = "هيئة_عامة_نقض"
    elif _NAQD_RE.search(t) or re.search(r"اساس", t):
        c.court = "نقض"
    elif re.search(r"^\(?\s*سورية\s+قرار\s+(?:جنحي|جنائي|مدني|شرعي)", t):
        # موسوعة كيلاني: «سورية قرار جنحي 322 تاريخ … قق 1273» — قرارات النقض السورية
        # بترميز الموسوعة؛ نُثبت الجهة مع تحذير حتى يراجعها المالك.
        c.court = "نقض"
        c.warnings.append("court_inferred_kilani")

    # الغرفة / نوع الدعوى
    orig = to_western_digits(raw)
    m = _CHAMBER_RE.search(t)
    if m and (m.group("name") or m.group("ord")):
        name = m.group("name") or ""
        parts = [orig[m.start(g):m.end(g)] for g in ("name", "ord") if m.group(g)]
        c.chamber_raw = " ".join(parts) or None
        c.division = CHAMBER_DIVISION.get(name) or ("مدنية" if m.group("ord") and not name else None)
        if not name and m.group("ord"):
            c.warnings.append("chamber_ordinal_without_name")
    if _MUKHASAMA_RE.search(t) and c.court in ("نقض", None):
        c.case_kind = "مخاصمة"
        c.court = c.court or "نقض"
        c.division = c.division or "مدنية"
    if not c.chamber_raw and c.court in ("نقض", None):
        # «(جنحة أساس …)» / «نقض سوري ـ عسكرية أساس …» / «الدوائر المدنية»
        head = t[: t.find("اساس")] if "اساس" in t else t[:60]
        k = _CASE_KIND_RE.search(head)
        if k:
            kind = k.group("k")
            if kind not in ("مدنية", "شرعية", "تجارية"):
                c.case_kind = c.case_kind or kind
            c.division = c.division or CASE_KIND_DIVISION[kind]
            c.court = c.court or "نقض"

    # الأرقام
    m = _DEC_RE.search(t)
    if m:
        c.decision_number = m.group("dn")
        c.decision_year = _year(m.group("dy"))
    else:
        m = _DEC_BEFORE_BASIS_RE.search(t)
        if m:
            c.decision_number = m.group("dn")
    m = _BASIS_RE.search(t)
    if m:
        c.basis_number = m.group("bn") or m.group("bn0")
        c.basis_year = _year(m.group("by"))
        if m.group("bn") is None and m.group("bn0") is None and "بدون" in m.group(0):
            c.basis_number = None
    m = _APPEAL_RE.search(t)
    if m:
        c.appeal_number = m.group("an")
        c.decision_year = c.decision_year or _year(m.group("ay"))
    m = _DATE_RE.search(t) or _DATE_YMD_RE.search(t)
    if m:
        c.decision_date = _iso(m.group("d"), m.group("m"), m.group("y"))
    if c.decision_date and c.decision_year and c.decision_year != int(c.decision_date[:4]):
        c.warnings.append("year_date_mismatch")

    # الإسناد
    for name, rx in _PUBS:
        if rx.search(t):
            c.publication = name
            break
    m = _RULE_RE.search(t)
    if m:
        c.rule_number = m.group("r")
    m = _PAGE_RE.search(t)
    if m:
        c.pub_page = m.group("p")
    m = _ISSUE_RE.search(t)
    if m:
        c.pub_issue = re.sub(r"\s*[-–ـ]\s*", "-", m.group("i"))
    if "المصدر" in t:
        tail = t[t.find("المصدر"):]
    elif "الصفحة" in t:                       # سطر «الصفحة : N محامون العدد … لعام Y» (المحامون)
        tail = t[t.find("الصفحة"):]
        tail = re.split(r"\n|القاعدة|القضية", tail, maxsplit=1)[0]
    else:
        tail = t
    ys = [_year(y) for y in _PUBYEAR_RE.findall(tail)]
    ys = [y for y in ys if y]
    if ys and c.publication:
        c.pub_year = ys[-1]
    elif c.publication and c.publication == "القانون":
        mm = re.search(r"قانون\s+(\d{4})|القانون\s+(\d{4})", t)
        if mm:
            c.pub_year = int(mm.group(1) or mm.group(2))

    c.confidence = _confidence(c)
    return c


def _confidence(c: Citation) -> float:
    s = 0.0
    if c.court:
        s += 0.25
    if c.decision_number:
        s += 0.3
    if c.basis_number:
        s += 0.15
    if c.decision_date:
        s += 0.2
    elif c.decision_year:
        s += 0.1
    if c.publication:
        s += 0.1
    if "year_date_mismatch" in c.warnings:
        s -= 0.2
    return round(max(0.0, min(1.0, s)), 2)


# ------------------------------------------------- تقسيم نص كامل إلى استشهادات
# مرساة البلوك البنيوي (الشكل 1): سطر «القضية :» أو «القاعدة:»؛ الشكل السطري:
# سطر يبدأ بـ«نقض سوري» أو «قرار N» أو «(القرار رقم» أو «(جنحة/جناية/… أساس».
_BLOCK_START_RE = re.compile(
    r"(?m)^\s*(?:القاعدة\s*:|القضية\s*:|نقض\s+سوري|قرار\s+\d|\(?\s*القرار\s+رقم|"
    r"\(\s*(?:جنحة|جناية|احداث|عسكرية|امن اقتصادي|هيئة عامة|مخاصمة)\s+اساس|"
    r"\(?\s*(?:هيئة\s+عامة|الهيئة\s+العامة)\s*[،,]?\s*اساس)")
_INLINE_RE = re.compile(
    r"\(\s*(?:نقض\s+سوري|جنحة|جناية|احداث|عسكرية|امن\s+اقتصادي|هيئة\s+عامة|القرار\s+رقم)[^()\n]{8,240}\)")


_REASONING_RE = re.compile(
    r"\n\s*(?:أسباب\s+(?:ال)?طعن|اسباب\s+(?:ال)?طعن|في\s+القضاء\s+والقانون|النظر\s+في\s+الطعن|"
    r"(?:ال)?وقائع|من\s+حيث\s+الشكل|في\s+الشكل)")
_PAGE_LINE_RE = re.compile(r"(?m)^\s*الصفحة\s*:[^\n]*$")


def _block_spans(t: str) -> list[tuple[int, int]]:
    has_rule = re.search(r"(?m)^\s*القاعدة\s*:", t) is not None   # الكلمة وحدها قد ترد داخل مبدأ
    starts = []
    for m in _BLOCK_START_RE.finditer(t):
        if has_rule and m.group(0).strip().startswith("القضية"):
            continue
        s = m.start()
        if m.group(0).strip().startswith("القاعدة"):
            # سطر «الصفحة : N محامون العدد … لعام …» يسبق «القاعدة» — إسناد المنشور، يُضم
            prev = t[:s].rstrip()
            pm = None
            for pm in _PAGE_LINE_RE.finditer(prev[-300:]):
                pass
            if pm and prev[len(prev) - 300 + pm.end():].strip() == "":
                s = max(0, len(prev) - 300) + pm.start()
        starts.append(s)
    return [(s, starts[i + 1] if i + 1 < len(starts) else len(t)) for i, s in enumerate(starts)]


def split_blocks(text: str) -> list[str]:
    """يقطع نصاً كاملاً إلى مقاطع كل منها استشهاد (+ مبدؤه إن تبعه) — نص أصلي."""
    orig = to_western_digits(text or "")
    return [orig[a:b].strip() for a, b in _block_spans(_norm(text))]


_PAREN_CIT_RE = re.compile(r"\((?:نقض|قرار|هيئة|محكمة|ادارية|إدارية)[^()]{0,60}?\n[^()]{0,200}\)")


def _join_paren_lines(text: str) -> str:
    return _PAREN_CIT_RE.sub(lambda m: m.group(0).replace("\n", " "), text)


def parse_text(text: str, min_confidence: float = 0.4) -> list[Citation]:
    """نقطة الدخول: نص صفحة ⇒ استشهادات بمبادئها.

    - الشكل 1: المبدأ = سطر «المبدأ:» + السطور التالية حتى «الصفحة/القاعدة» التالية.
    - الشكل 2/3/7: المبدأ = النص الذي **يسبق** الاستشهاد إن كان بين قوسين مربعين
      أو الفقرة السابقة القصيرة (≤ 700 حرف) — أو الذي يليه إن بدأ الاستشهاد المقطع.
    """
    # أسطر مكسورة داخل قوس الإسناد «(نقض مدني سوري\n247 أساس …)» (مدوّنات بلوغر) —
    # تُستبدل بمسافات (حافظ للطول) حتى يلتقطها المحلل كاستشهاد واحد
    text = _join_paren_lines(text or "")
    orig = to_western_digits(text or "")
    t = _norm(text)
    assert len(t) == len(orig)
    out: list[Citation] = []
    seen: set[str] = set()

    # (أ) الاستشهادات بين قوسين داخل الفقرات (الشكلان 2 و7): المبدأ يسبقها
    last_end = 0
    for m in _INLINE_RE.finditer(t):
        raw = orig[m.start():m.end()]
        c = parse_citation(raw)
        prev = orig[last_end:m.start()]
        p = _principle_before(prev)
        if p:
            c.principle_text = p
        last_end = m.end()
        _push(out, seen, c, min_confidence)

    # (ب) المقاطع المسطّرة (الأشكال 1 و2 و3) — المواضع من النص المطبَّع، القصّ من الأصلي
    for bs, be in _block_spans(t):
        b, nb = orig[bs:be].strip(), t[bs:be].strip()
        first_line, _, rest = b.partition("\n")
        if nb.startswith(("القاعدة", "القضية", "الصفحة")):
            # الشكل 1: الرأس = السطور حتى «المبدأ:»، المبدأ = ما بعده
            i = nb.find("المبدا")
            head = b[:i] if i >= 0 else b
            body, nbody = (b[i:], nb[i:]) if i >= 0 else ("", "")
            c = parse_citation(head.replace("\n", " "))
            c.citation_raw = head.strip()
            if i < 0:
                # بعض القواعد بلا لصيقة «المبدأ:» — سطر كلمات مفتاحية بفواصل «–» بعد «تاريخ»
                km = re.search(r"\n\s*(?P<t>[^\n]{3,80}\s[–-]\s[^\n]{3,120})\s*\n", nb[nb.find("تاريخ"):] if "تاريخ" in nb else "")
                if km:
                    off = nb.find("تاريخ") + km.start()
                    head, body, nbody = b[:off], "المبدأ: " + b[off:].lstrip("\n"), "المبدا: " + nb[off:].lstrip("\n")
                    c = parse_citation(head.replace("\n", " "))
                    c.citation_raw = head.strip()
            pm = _PRINCIPLE_LINE_RE.search(nbody)
            if pm:
                c.title_keywords = body[pm.start("t"):pm.end("t")].strip(" .")
                after = body[pm.end():].strip()
                after = re.split(r"\n\s*(?:الصفحة|القاعدة)\s*:", after)[0].strip()
                # الحكم الكامل (منتديات): المبدأ ينتهي حيث تبدأ أسباب الطعن/الوقائع/التعليل
                after = _REASONING_RE.split(after, maxsplit=1)[0].strip()
                c.principle_text = after or None
            if c.title_keywords and not c.principle_text:
                c.principle_text = c.title_keywords
        else:
            head = first_line
            c = parse_citation(head)
            c.citation_raw = head.strip()
            if rest.strip():
                cand = re.split(r"\n\s*\n", rest.strip())[0].strip()
                if 20 <= len(cand) <= 1200 and not _BLOCK_START_RE.match(cand):
                    c.principle_text = cand
        _push(out, seen, c, min_confidence)
    return out


def _principle_before(prev: str) -> str | None:
    prev = prev.strip()
    if not prev:
        return None
    br = re.findall(r"\[([^\[\]]{20,1200})\]", prev)
    if br:
        return " ".join(x.strip() for x in br[-3:])
    # الفقرة الأخيرة (فاصل سطر فارغ)؛ الأسطر الملفوفة داخلها تُضم — وإن طالت
    # (> 700) نعود للسطر الأخير وحده (سلوك mohamah السابق)
    para = re.split(r"\n\s*\n", prev)[-1].strip()
    para = re.sub(r"\s*\n\s*", " ", para)
    if not (20 <= len(para) <= 700):
        para = re.split(r"\n\s*\n|\n", prev)[-1].strip()
    if 20 <= len(para) <= 700:
        return para
    return None


def _push(out, seen, c: Citation, min_conf: float):
    if c.confidence < min_conf:
        return
    k = c.identity_key() or hashlib.sha256(c.citation_raw.encode()).hexdigest()
    if k in seen:
        # دمج المبدأ إن كان الأول بلا مبدأ
        for o in out:
            if (o.identity_key() or "") == k and not o.principle_text and c.principle_text:
                o.principle_text = c.principle_text
        return
    seen.add(k)
    out.append(c)


# ------------------------------------------------- الروابط بالمواد + العدول
_LAW_ALIASES = {
    "اصول": "أصول المحاكمات", "اصول مدنية": "أصول المحاكمات", "اصول محاكمات": "أصول المحاكمات",
    "الاصول المدنية": "أصول المحاكمات", "الاصول": "أصول المحاكمات", "المدني": "القانون المدني",
    "العقوبات": "قانون العقوبات", "البينات": "قانون البينات", "الاصول الجزائية": "أصول المحاكمات الجزائية",
    "اصول جزائية": "أصول المحاكمات الجزائية", "مدني": "القانون المدني", "عقوبات": "قانون العقوبات",
    "بينات": "قانون البينات", "ايجار": "قانون الإيجار", "عمل": "قانون العمل", "تجارة": "قانون التجارة",
    "احوال شخصية": "قانون الأحوال الشخصية", "سلطة قضائية": "قانون السلطة القضائية",
}
_ART_RE = re.compile(
    r"(?:ال)?ماد(?:ة|تين|تان)\s*/?\s*\(?\s*(?P<n>\d{1,4})\s*(?:مكرر)?\s*\)?\s*/?\s*(?:و\s*/?\s*(?P<n2>\d{1,4})\s*/?)?"
    r"\s*(?:من\s+(?:قانون\s+|القانون\s+)?)?(?P<law>" + "|".join(sorted(map(re.escape, _LAW_ALIASES), key=len, reverse=True)) + r")?")


def extract_article_refs(text: str) -> list[dict]:
    t = _norm(text)
    refs = []
    for m in _ART_RE.finditer(t):
        law = m.group("law")
        for n in (m.group("n"), m.group("n2")):
            if n:
                refs.append({"article_number": n,
                             "law_alias": _LAW_ALIASES.get(law) if law else None,
                             "confidence": 0.9 if law else 0.4})
    return refs


_OVERRULE_RE = re.compile(
    r"العدول\s+عن\s+(?:الاجتهاد\s+(?:الوارد\s+في\s+)?|اجتهاد\s+(?:هذه\s+المحكمة\s+)?|قرار\s+الهيئة\s+العامة\s+(?:لمحكمة\s+النقض\s+)?)?"
    r"(?P<body>[^.\n]{5,200}?)(?:\s+على\s+الوجه|\.|\n|$)")


def extract_overrulings(text: str) -> list[Citation]:
    """من منطوق الهيئة العامة: «العدول عن الاجتهاد الوارد في القرار 773/512 جناية تاريخ 8/7/1965» ⇒ الهدف."""
    t = _norm(text)
    targets = []
    for m in _OVERRULE_RE.finditer(t):
        body = m.group("body")
        # تفكيك «القرار 773 / 512 جناية تاريخ …» و«والقرار رقم 2197 / 1881 جنحة تاريخ …»
        for part in re.split(r"\s+و(?=القرار|قرار|رقم)", body):
            dm = re.search(rf"المؤرخ\s+في\s+(?P<d>\d{{1,2}}){_SEP}(?P<mo>\d{{1,2}}){_SEP}(?P<y>\d{{4}})\s*(?:رقم\s+(?P<n>\d+))?", part)
            if dm:
                c = Citation(citation_raw=part.strip(), court="نقض")
                c.decision_date = _iso(dm.group("d"), dm.group("mo"), dm.group("y"))
                c.decision_number = dm.group("n")
                c.confidence = _confidence(c)
                targets.append(c)
                continue
            pm = re.search(rf"(?:القرار\s+)?(?:رقم\s+)?(?P<a>\d{{1,6}})\s*/\s*(?P<b>\d{{1,6}})\s*(?P<k>جناية|جنحة|احداث|عسكرية)?\s*(?:تاريخ\s*(?P<d>\d{{1,2}}){_SEP}(?P<mo>\d{{1,2}}){_SEP}(?P<y>\d{{4}}))?", part)
            if pm:
                c = Citation(citation_raw=part.strip(), court="نقض")
                c.decision_number, c.basis_number = pm.group("a"), pm.group("b")
                if pm.group("k"):
                    c.case_kind = pm.group("k"); c.division = "جزائية"
                if pm.group("d"):
                    c.decision_date = _iso(pm.group("d"), pm.group("mo"), pm.group("y"))
                c.confidence = _confidence(c)
                targets.append(c)
    return targets


AUTHORITY_RANK = {"هيئة_عامة_نقض": 1, "توحيد_مبادئ": 1, "نقض": 3, "ادارية_عليا": 4, "دستورية": 1}


def authority_rank(c: Citation) -> int:
    if c.case_kind == "مخاصمة":
        return 5
    return AUTHORITY_RANK.get(c.court or "", 6)
