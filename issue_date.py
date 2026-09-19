"""تاريخ الإصدار (A-2) — من ختام الصك أو رأسه، لا اختراع.

الأنماط مأخوذة من نصوص حقيقية قُرئت في هذه الجلسة (2026-09-19):
  «دمشق في 19/7/1427 هجري الموافق 13/8/2006 ميلادي»          (م.ت 35/2006)
  «دمشق في 22/2/1428هـ الموافق لـ12/3/2007م»                  (القانون 8/2007)
  «صدر في 16 /5 /1966»                                        (م.ت 37/1966)
  «القرار بالقانون رقم 92 تاريخ 6 ـ 4 ـ 1959»                  (التأمينات)
  «المرسوم التشريعي ذو الرقم/55/ تاريخ 2/9/2004م»              (التعليمات)
  «الصادر بالمرسوم التشريعي رقم 84 تاريخ 28/9/1953»            (أصول المحاكمات)

القواعد:
- الميلادي هو المعتمد. إن وُجد هجري وميلادي معاً يؤخذ الميلادي ولا يُحوَّل شيء.
- تاريخ هجري وحده لا يُحوَّل (التحويل تقريبي ±يوم وقد يخطئ السنة قرب رأس
  السنة) — يُخزَّن نصاً في `issue_date_hijri` ويُترك `issue_date` فارغاً.
- الأولوية: ختام الصك («دمشق في» / «صدر في» في آخر 1500 حرف) ثم رأسه
  («رقم N تاريخ D» في أول 600 حرف) — «تاريخ» في وسط المتن قد يخص صكاً محالاً
  إليه، فلا يُقرأ.
- السنة المستخرَجة تُقارن بسنة الهوية: إن اختلفتا بأكثر من سنة يُرفض
  التاريخ ويُوسم `issue_date_conflict` (لا يُكتب تاريخ يناقض الهوية).
- الناتج ISO `YYYY-MM-DD`؛ مع الثقة: `closing` / `heading`.
"""
from __future__ import annotations

import re
from datetime import date

from extractor_v4 import to_western_digits
from law_identity import _nfkc

_SEP = r"\s*[/\-ـ.،]\s*"
# يوم/شهر قد يغيبان («/ /1427») ولا يُقبل يوم/شهر بلا سنة
_D = rf"(?P<d>\d{{1,2}})?{_SEP}?(?P<m>\d{{1,2}})?{_SEP}(?P<y>\d{{4,5}})"
_DATE_RE = re.compile(rf"(?<!\d)(?:(?P<d>\d{{1,2}}){_SEP})?(?:(?P<m>\d{{1,2}}){_SEP})?(?P<y>\d{{4}})(?!\d)")
_MONTHS = {"كانون الثاني": 1, "يناير": 1, "شباط": 2, "فبراير": 2, "آذار": 3, "اذار": 3,
           "مارس": 3, "نيسان": 4, "أبريل": 4, "ابريل": 4, "أيار": 5, "ايار": 5, "مايو": 5,
           "حزيران": 6, "يونيو": 6, "تموز": 7, "يوليو": 7, "آب": 8, "اب": 8, "أغسطس": 8,
           "أيلول": 9, "ايلول": 9, "سبتمبر": 9, "تشرين الأول": 10, "تشرين الاول": 10,
           "أكتوبر": 10, "تشرين الثاني": 11, "تشرين الثانى": 11, "نوفمبر": 11,
           "كانون الأول": 12, "كانون الاول": 12, "ديسمبر": 12}
_NAMED_RE = re.compile(
    r"(?P<d>\d{1,2})\s+(?P<mon>" + "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
    + r")\s+(?:سنة\s+|عام\s+)?(?P<y>\d{4})")
# مرساة الختام: «دمشق في» / «دمشق» / «صدر في» / «صادر في» / «بتاريخ» — ثم نافذة قصيرة
# «صدر» يجب أن يكون كلمة مستقلة (لا «يصدر وزير…» ولا «مصدر») ويليه «في/بتاريخ»؛
# «دمشق» وحدها تكفي (قِيس issue_dates2: «دمشق 25/8/1421 ه 22/11/2000»)
_ANCHOR_RE = re.compile(
    r"(?<![\u0621-\u064A])(?:دمشق\s*(?:في|فى|بتاريخ|تاريخ)?|(?:صدر|صدرت|صادر)\s+(?:في|فى|بتاريخ))\s*:?")
_HEADING_RE = re.compile(r"(?:رقم|الرقم)\s*[/(]?\s*\d{1,4}\s*[/)]?\s*(?:و)?(?:ب)?تاريخ\s*[/(:]?\s*")
_WINDOW = 90

_MIN_G, _MAX_G = 1920, 2100
_MIN_H, _MAX_H = 1338, 1530


def _kind(y: int) -> str | None:
    if _MIN_G <= y <= _MAX_G:
        return "gregorian"
    if _MIN_H <= y <= _MAX_H:
        return "hijri"
    return None


def _iso(d: int, m: int, y: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _dates_in(window: str) -> list[tuple[str, int | None, int | None, int]]:
    """كل التواريخ في نافذة نصية: (kind, d, m, y) — بالأرقام أو بأسماء الأشهر."""
    found = []
    for m in _NAMED_RE.finditer(window):
        y = int(m["y"])
        if _kind(y) == "gregorian":
            found.append(("gregorian", int(m["d"]), _MONTHS[m["mon"]], y))
    for m in _DATE_RE.finditer(window):
        y = int(m["y"])
        k = _kind(y)
        if not k:
            continue
        d = int(m["d"]) if m["d"] else None
        mo = int(m["m"]) if m["m"] else None
        found.append((k, d, mo, y))
    return found


def _pick(found, identity_year, conf):
    """يفضّل ميلادياً كاملاً؛ وإلا هجرياً نصاً. يعيد dict أو None."""
    greg = [f for f in found if f[0] == "gregorian" and f[1] and f[2]]
    hij = [f for f in found if f[0] == "hijri"]
    if greg:
        _, d, mo, y = greg[-1]
        iso = _iso(d, mo, y)
        if iso is None:
            return None
        if identity_year and abs(y - int(identity_year)) > 1:
            return {"conflict": True}
        h = hij[-1] if hij else None
        return {"issue_date": iso, "issue_date_confidence": conf,
                "issue_date_hijri": f"{h[1] or ''}/{h[2] or ''}/{h[3]}" if h else None}
    if hij:
        h = hij[-1]
        return {"issue_date_hijri": f"{h[1] or ''}/{h[2] or ''}/{h[3]}",
                "issue_date_confidence": conf + "_hijri"}
    return None


def extract_issue_date(text: str, identity_year: int | None = None) -> dict:
    """يعيد {issue_date, issue_date_hijri, issue_date_confidence, conflict}."""
    out = {"issue_date": None, "issue_date_hijri": None,
           "issue_date_confidence": None, "conflict": False}
    t = to_western_digits(_nfkc(text or ""))
    if not t:
        return out
    tail = t[-1500:]
    # الختام: آخر مرساة يليها تاريخ (التوقيع في نهاية الصك)
    best = None
    for a in _ANCHOR_RE.finditer(tail):
        found = _dates_in(tail[a.end():a.end() + _WINDOW])
        r = _pick(found, identity_year, "closing")
        if r:
            best = r
    if best is None:
        # الرأس فقط قبل أول «المادة» (بعدها «رقم N تاريخ D» إحالة لا هوية —
        # قِيس issue_dates2: #28/#107 التقطا تاريخ قرار ملغى داخل المتن)
        head = t[:600]
        cut = re.search(r"(?:^|\s)ال?مادة\s*[\d(/]", head)
        if cut:
            head = head[:cut.start()]
        for a in _HEADING_RE.finditer(head):
            found = _dates_in(head[a.end():a.end() + 40])
            r = _pick(found, identity_year, "heading")
            if r:
                best = r
                break
    if best is None:
        return out
    if best.get("conflict"):
        out["conflict"] = True
        return out
    out.update(best)
    return out


def extract_issue_dates(conn) -> dict:
    """يكتب documents.issue_date / issue_date_hijri / issue_date_confidence
    لكل صك نشط. يُعاد الحساب من الصفر (لا تراكم قيم قديمة)."""
    rows = conn.execute(
        "SELECT id, clean_content, year FROM documents WHERE status='active' "
        "AND COALESCE(nature,'instrument')='instrument'").fetchall()
    st = {"dated": 0, "hijri_only": 0, "conflict": 0, "none": 0}
    for r in rows:
        d = extract_issue_date(r["clean_content"] or "", r["year"])
        conn.execute(
            "UPDATE documents SET issue_date=?, issue_date_hijri=?,"
            " issue_date_confidence=? WHERE id=?",
            (d["issue_date"], d["issue_date_hijri"],
             (d["issue_date_confidence"] or "") + ("|conflict" if d["conflict"] else "")
             or None, r["id"]))
        if d["issue_date"]:
            st["dated"] += 1
        elif d["conflict"]:
            st["conflict"] += 1
        elif d["issue_date_hijri"]:
            st["hijri_only"] += 1
        else:
            st["none"] += 1
    conn.commit()
    return st
