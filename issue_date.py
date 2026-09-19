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

_SEP = r"\s*[/\-ـ.]\s*"
_D = rf"(?P<d>\d{{1,2}}){_SEP}(?P<m>\d{{1,2}}){_SEP}(?P<y>\d{{4}})"

_CLOSING_RE = re.compile(
    rf"(?:دمشق|صدر|صدرت)\s+(?:في|فى|بتاريخ)\s*:?\s*"
    rf"(?P<first>{_D})"
    rf"(?:\s*(?:هـ|هجري|هجرية|هجرى)?\s*(?:الموافق|المصادف|و)\s*(?:لـ|ل)?\s*"
    rf"(?P<second>(?P<d2>\d{{1,2}}){_SEP}(?P<m2>\d{{1,2}}){_SEP}(?P<y2>\d{{4}})))?",
    re.S)
_HEADING_RE = re.compile(
    rf"(?:رقم|الرقم)\s*[/(]?\s*\d{{1,4}}\s*[/)]?\s*(?:و)?تاريخ\s*[/(]?\s*{_D}", re.S)
_ANY_DATE_RE = re.compile(_D)

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


def extract_issue_date(text: str, identity_year: int | None = None) -> dict:
    """يعيد {issue_date, issue_date_hijri, issue_date_confidence, conflict}."""
    out = {"issue_date": None, "issue_date_hijri": None,
           "issue_date_confidence": None, "conflict": False}
    t = to_western_digits(_nfkc(text or ""))
    if not t:
        return out

    cands: list[tuple[str, int, int, int, str | None]] = []   # (conf, d, m, y, hijri_txt)
    tail = t[-1500:]
    for m in _CLOSING_RE.finditer(tail):
        d, mo, y = int(m["d"]), int(m["m"]), int(m["y"])
        k = _kind(y)
        if m["second"]:
            d2, m2, y2 = int(m["d2"]), int(m["m2"]), int(m["y2"])
            if _kind(y2) == "gregorian":
                cands.append(("closing", d2, m2, y2,
                              f"{d}/{mo}/{y}" if k == "hijri" else None))
                continue
            if k == "gregorian":
                cands.append(("closing", d, mo, y, None))
                continue
        if k == "gregorian":
            cands.append(("closing", d, mo, y, None))
        elif k == "hijri":
            cands.append(("closing_hijri", d, mo, y, f"{d}/{mo}/{y}"))
    if not cands:
        head = t[:600]
        for m in _HEADING_RE.finditer(head):
            d, mo, y = int(m["d"]), int(m["m"]), int(m["y"])
            k = _kind(y)
            if k == "gregorian":
                cands.append(("heading", d, mo, y, None))
            elif k == "hijri":
                cands.append(("heading_hijri", d, mo, y, f"{d}/{mo}/{y}"))
            break
    if not cands:
        return out

    # الأفضلية: ميلادي على هجري؛ الختام على الرأس؛ الأخير في الختام (التوقيع)
    greg = [c for c in cands if not c[0].endswith("_hijri")]
    pick = greg[-1] if greg else cands[-1]
    conf, d, mo, y, hij = pick
    if conf.endswith("_hijri"):
        out["issue_date_hijri"] = hij
        out["issue_date_confidence"] = conf
        return out
    iso = _iso(d, mo, y)
    if iso is None:
        return out
    if identity_year and abs(y - int(identity_year)) > 1:
        out["conflict"] = True
        return out
    out.update(issue_date=iso, issue_date_hijri=hij, issue_date_confidence=conf)
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
