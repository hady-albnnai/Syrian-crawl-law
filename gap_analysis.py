# -*- coding: utf-8 -*-
"""gap_analysis.py — تحليل فجوات فروع القانون + توليد استعلامات موجَّهة
(DELIVERY/DESIGN-SELF-DISCOVERY.md §7). حد أدنى متوقَّع لكل فرع يُحسب
آلياً من توزيع القاعدة نفسها (§9) — لا رقم ثابت مُخمَّن:

    الحد الأدنى المتوقَّع لفرع = 0.3 × متوسط الفروع الثلاثة الأعلى تغطية

قابل للاستبدال لاحقاً بتقدير قانوني صريح عبر config.EXPECTED_MIN_OVERRIDE
(فارغ افتراضياً) بلا تغيير بعقد هذا الملف.
"""
from config import BRANCH_KEYWORDS

# نسبة الفجوة (§9): فرع بتغطية أقل من 30% من متوسط أنجح 3 فروع يُعتبر
# ناقصاً. رقم نسبي مُبرَّر بالتصميم — لا يُخترع من هذا الملف.
GAP_RATIO = 0.3

# استبدال يدوي صريح إن توفر تقدير قانوني فعلي لاحقاً (فارغ افتراضياً —
# لا قيمة مُخمَّنة تُفرض بلا مصدر).
EXPECTED_MIN_OVERRIDE: dict = {}


def branch_distribution(conn) -> dict:
    """عدد الوثائق النشطة الفعلي بكل فرع معروف — الفروع بلا أي وثيقة
    تظهر بصفر (لا تُسقَط من التقرير)."""
    rows = conn.execute(
        "SELECT branch, COUNT(*) AS c FROM documents "
        "WHERE status = 'active' GROUP BY branch").fetchall()
    counts = {branch: 0 for branch in BRANCH_KEYWORDS}
    for row in rows:
        if row[0] in counts:
            counts[row[0]] = row[1]
    return counts


def _expected_minimum(counts: dict) -> dict:
    """الحد الأدنى المتوقَّع لكل فرع = 0.3 × متوسط أعلى 3 فروع تغطية
    (باستثناء الفرع نفسه من حساب "أعلى 3" كي لا يقارن فرع بنفسه)."""
    expected = {}
    for branch in counts:
        if branch in EXPECTED_MIN_OVERRIDE:
            expected[branch] = EXPECTED_MIN_OVERRIDE[branch]
            continue
        others = sorted(
            (v for b, v in counts.items() if b != branch), reverse=True)
        top3 = others[:3]
        avg_top3 = (sum(top3) / len(top3)) if top3 else 0
        expected[branch] = round(avg_top3 * GAP_RATIO, 1)
    return expected


def analyze_gaps(conn) -> dict:
    """يعيد تقريراً كاملاً: {branch: {"count", "expected_min", "gap"}}.
    gap=True فقط إذا كان العدد الفعلي أقل من الحد الأدنى المحسوب."""
    counts = branch_distribution(conn)
    expected = _expected_minimum(counts)
    report = {}
    for branch, count in counts.items():
        exp_min = expected[branch]
        report[branch] = {
            "count": count,
            "expected_min": exp_min,
            "gap": count < exp_min,
        }
    return report


def gap_queries_for_branch(branch: str, limit: int = 3) -> list:
    """استعلامات بحث موجَّهة لفرع تحديداً — من كلماته المفتاحية الأولى
    (الأكثر تمييزاً عادة بحسب ترتيب config.BRANCH_KEYWORDS)."""
    keywords = BRANCH_KEYWORDS.get(branch, [])
    return [f"{kw} سوريا قانون نص كامل" for kw in keywords[:limit]]


def gap_driven_queries(conn, per_branch_limit: int = 2) -> list:
    """استعلامات لكل الفروع الناقصة التغطية فعلياً — تُضاف لمصادر توليد
    الاستعلامات الأخرى (autopilot.DEFAULT_QUERIES + reference_driven_queries)."""
    report = analyze_gaps(conn)
    queries = []
    for branch, info in report.items():
        if info["gap"]:
            queries.extend(gap_queries_for_branch(branch, per_branch_limit))
    return queries


def branch_breakdown_for_run(conn, since_doc_id: int) -> dict:
    """توزيع الوثائق الجديدة المكتسبة بدورة واحدة (id > since_doc_id) حسب
    الفرع — للفرز/التقرير الختامي بعد كل دورة زحف (§7.2)."""
    rows = conn.execute(
        "SELECT branch, COUNT(*) AS c FROM documents "
        "WHERE id > ? GROUP BY branch", (since_doc_id,)).fetchall()
    return {row[0] or "غير مصنَّف": row[1] for row in rows}
