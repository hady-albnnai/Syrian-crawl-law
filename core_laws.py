# -*- coding: utf-8 -*-
"""core_laws.py — القائمة الأساسية لمكتب محاماة سوري (بيانات لا كود) + فحص تغطيتها.

الغرض (2026-09-22، قرار المالك: «نكمل تجهيز المكتبة قبل تطوير ميزان»): معرفة
أي الصكوك اليومية ناقصة أو ناقصة المواد أو حالتها مشبوهة في القاعدة.

قواعد القائمة (CONSTITUTION: لا رقم غير متحقَّق منه):
- كل مدخل: اسم شائع، رقم، سنة، «الحد الأدنى المتوقَّع للمواد» إن كان معلوماً
  من نص القانون نفسه (وإلا None فلا يُقارَن)، والمرجع.
- المطابقة بالرقم والسنة عبر أي نوع صك (identity_key = نوع:رقم:سنة) لأن
  بعض المصادر تسمّي المرسوم التشريعي «قانوناً».
- ما يُشكّ فيه يُعلَّم `review=True` ليؤكده المالك قبل أن يُعدّ فجوة.
"""
from __future__ import annotations

CORE_LAWS: list[dict] = [
    # المدني والإجرائي
    {"name": "القانون المدني", "number": 84, "year": 1949, "min_articles": 1130, "ref": "م.ت 84/1949 — 1130 مادة (نص القانون)"},
    {"name": "قانون أصول المحاكمات (المدنية)", "number": 1, "year": 2016, "min_articles": 550, "ref": "القانون 1/2016 (REVIEW-NAMED-LAWS)"},
    {"name": "قانون البينات", "number": 359, "year": 1947, "min_articles": 100, "ref": "القانون 359/1947"},
    {"name": "قانون التحكيم", "number": 4, "year": 2008, "min_articles": 60, "ref": "القانون 4/2008"},
    {"name": "قانون الإيجار", "number": 20, "year": 2015, "min_articles": 30, "ref": "القانون 20/2015 (المكتبة تعرفه — تجربة D-3)"},
    {"name": "قانون السجل العقاري", "number": 188, "year": 1926, "min_articles": None, "ref": "القرار 188/1926"},
    {"name": "قانون الاستملاك", "number": 20, "year": 1983, "min_articles": None, "ref": "م.ت 20/1983"},
    # الجزائي
    {"name": "قانون العقوبات", "number": 148, "year": 1949, "min_articles": 750, "ref": "م.ت 148/1949 (القائمة الذهبية: غير ملغى)"},
    {"name": "قانون أصول المحاكمات الجزائية", "number": 112, "year": 1950, "min_articles": 450, "ref": "م.ت 112/1950 (named_laws)"},
    {"name": "قانون الأحداث الجانحين", "number": 18, "year": 1974, "min_articles": None, "ref": "القانون 18/1974"},
    {"name": "قانون مكافحة المخدرات", "number": 2, "year": 1993, "min_articles": None, "ref": "القانون 2/1993"},
    {"name": "قانون الجريمة المعلوماتية", "number": 20, "year": 2022, "min_articles": None, "ref": "القانون 20/2022"},
    {"name": "قانون مكافحة الإرهاب", "number": 19, "year": 2012, "min_articles": None, "ref": "القانون 19/2012"},
    {"name": "قانون العقوبات الاقتصادية", "number": 3, "year": 2013, "min_articles": None, "ref": "القانون 3/2013 (named_laws)"},
    # الأحوال الشخصية والمدنية
    {"name": "قانون الأحوال الشخصية", "number": 59, "year": 1953, "min_articles": 300, "ref": "م.ت 59/1953 (named_laws)"},
    {"name": "قانون الأحوال المدنية", "number": 13, "year": 2021, "min_articles": None, "ref": "القانون 13/2021"},
    {"name": "قانون الجنسية", "number": 276, "year": 1969, "min_articles": None, "ref": "م.ت 276/1969"},
    {"name": "قانون حقوق الطفل", "number": 21, "year": 2021, "min_articles": None, "ref": "القانون 21/2021"},
    # التجاري والشركات والعمل
    {"name": "قانون التجارة", "number": 33, "year": 2007, "min_articles": 700, "ref": "القانون 33/2007"},
    {"name": "قانون الشركات", "number": 29, "year": 2011, "min_articles": 200, "ref": "م.ت 29/2011"},
    {"name": "قانون التجارة البحرية", "number": 46, "year": 2006, "min_articles": None, "ref": "القانون 46/2006"},
    {"name": "قانون الوكالات التجارية", "number": 34, "year": 2008, "min_articles": None, "ref": "م.ت 34/2008"},
    {"name": "قانون العمل", "number": 17, "year": 2010, "min_articles": 280, "ref": "القانون 17/2010"},
    {"name": "قانون التأمينات الاجتماعية", "number": 92, "year": 1959, "min_articles": None, "ref": "القانون 92/1959 (named_laws)"},
    {"name": "قانون حماية المستهلك", "number": 14, "year": 2015, "min_articles": None, "ref": "القانون 14/2015", "review": True},
    # القضاء والمهنة والإداري
    {"name": "قانون تنظيم مهنة المحاماة", "number": 30, "year": 2010, "min_articles": 150, "ref": "القانون 30/2010"},
    {"name": "قانون السلطة القضائية", "number": 98, "year": 1961, "min_articles": None, "ref": "م.ت 98/1961 (named_laws م13)"},
    {"name": "قانون مجلس الدولة", "number": 32, "year": 2019, "min_articles": 60, "ref": "القانون 32/2019 (PRECEDENTS-RESEARCH §8)"},
    {"name": "قانون الجمارك", "number": 38, "year": 2006, "min_articles": None, "ref": "القانون 38/2006"},
]


def check_core(conn) -> list[dict]:
    """لكل صك أساسي: موجود؟ نشط؟ عدد مواده؟ حالته القانونية؟ ⇒ حكم."""
    out = []
    for law in CORE_LAWS:
        rows = conn.execute(
            """SELECT d.id, d.identity_key, d.title, d.status, d.legal_status, d.is_complete_text,
                      (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.id) AS n
               FROM documents d WHERE d.number = ? AND d.year = ? ORDER BY d.status = 'active' DESC, n DESC""",
            (law["number"], law["year"])).fetchall()
        active = [r for r in rows if r[3] == "active"]
        best = active[0] if active else (rows[0] if rows else None)
        n = best[6] if best else 0
        if not rows:
            verdict = "مفقود"
        elif not active:
            verdict = f"موجود لكن غير نشط ({rows[0][3]})"
        elif law["min_articles"] and n < law["min_articles"]:
            verdict = f"ناقص المواد ({n} < {law['min_articles']})"
        elif n == 0:
            verdict = "بلا مواد"
        else:
            verdict = "مكتمل" if (best[5] in (1, None)) else "نص غير كامل"
        out.append({"law": law, "verdict": verdict, "articles": n,
                    "identity_key": best[1] if best else None,
                    "legal_status": best[4] if best else None, "title": best[2] if best else None,
                    "review": law.get("review", False)})
    return out


def format_core_report(results: list[dict]) -> str:
    ok = sum(1 for r in results if r["verdict"] == "مكتمل")
    lines = [f"القائمة الأساسية: {ok}/{len(results)} مكتمل"]
    for r in results:
        l = r["law"]
        flag = " (يراجعه المالك)" if r["review"] else ""
        lines.append(f"- {r['verdict']:<28} {l['name']} {l['number']}/{l['year']}{flag} — مواد {r['articles']}"
                     + (f" — {r['legal_status']}" if r["legal_status"] else "")
                     + (f" — {r['identity_key']}" if r["identity_key"] else ""))
    return "\n".join(lines)
