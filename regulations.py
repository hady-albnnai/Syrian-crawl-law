"""الصكوك التابعة (لوائح/تعليمات تنفيذية) → قانونها الأم (ف٩).

اللائحة التنفيذية ليست «بلا هوية» بمعنى النقص؛ هي صك تابع يُعرَّف بقانونه
الأم ويتبع حالة نفاذه. يُكتب `documents.parent_identity` (هجرة 009) من
قاموس بيانات موثَّق المصدر، وتُكتب هوية اللائحة نفسها إن كان لها رقم
متحقَّق (القرار 189/1926). لا اختراع: ما لم يُعثر على مصدره لا يُدخل.
"""
from __future__ import annotations

from named_laws import _norm

REGULATIONS: list[dict] = [
    {"title": "التعليمات التوضيحية والتنفيذية لقانون تنظيم التواصل على الشبكة",
     "parent": "المرسوم التشريعي:17:2012",
     "source": "عنوان الوثيقة نفسها: «صادرة بقرار وزاري رقم 290 المؤرخ 7 يناير 2012»؛ قانون الجريمة المعلوماتية = م.ت 17/2012 (REVIEW-NAMED-LAWS)"},
    {"title": "اللائحة التنفيذية لقانون حماية العلامات الفارقة",
     "parent": "القانون:8:2007",
     "source": "casi.gov.sy cat=14786: القانون 8/2007 م158 «تصدر اللائحة التنفيذية لهذا القانون بقرار من الوزير»"},
    {"title": "التعليمات التنفيذية للمرسوم التشريعي ذي الرقم /55",
     "parent": "المرسوم التشريعي:55:2004",
     "source": "casi.gov.sy nid=14742 «التعليمات التنفيذية للمرسوم رقم 55 لعام 2004» — المادة 1 حرفياً: «المرسوم: المرسوم التشريعي ذو الرقم/55/ تاريخ 2/9/2004»"},
    {"title": "اللائحة التنفيذية لقانون السجل العقاري",
     "parent": "القرار:188:1926",
     "own": ("القرار", 189, 1926),
     "source": "parliament.gov.sy node=5588 cat=16259 و damascusbar.org nid=118847: «القرار رقم 189 لعام 1926 اللائحة التنفيذية لقانون السجل العقاري» (المادة 1 حرفياً)؛ قانون السجل العقاري = القرار 188/1926"},
    {"title": "اللائحة التنفيذية لقانون الإصلاح الزراعي",
     "parent": "القانون:161:1958",
     "source": "syrian-lawyer.club: «اللائحة التنفيذية لقانون الإصلاح الزراعي 161 لعام 1958 — المرسوم 1109» (المادة 1 حرفياً)؛ سنة المرسوم 1109 مختلَف فيها (1962 syriadirect / 1963 مكتبة القوانين) فلا تُكتب"},
    {"title": "لائحة التفتيش القضائي",
     "parent": "المرسوم التشريعي:98:1961",
     "source": "قانون السلطة القضائية 98/1961 م13: «يضع وزير العدل لائحة للتفتيش القضائي بموافقة مجلس القضاء الأعلى» (sl-center.org PDF)؛ ونص اللائحة يحيل إلى «الفصل الثالث من قانون السلطة القضائية»"},
    {"title": "التعليمات التنفيذية لقانون الضريبة على الدخل رقم /24/ لعام 2003",
     "parent": "القانون:24:2003",
     "source": "العنوان صريح"},
]


def lookup_regulation(title: str) -> dict | None:
    nt = _norm(title)
    if not nt:
        return None
    for e in REGULATIONS:
        if _norm(e["title"]) in nt:
            return e
    return None


def link_regulations(conn) -> dict:
    """يكتب parent_identity (وهوية اللائحة إن وُجدت) للصكوك التابعة."""
    rows = conn.execute(
        "SELECT id, title, identity_key FROM documents WHERE status='active'"
    ).fetchall()
    linked = own = 0
    for r in rows:
        e = lookup_regulation(r["title"] or "")
        if not e:
            continue
        conn.execute("UPDATE documents SET parent_identity=? WHERE id=?",
                     (e["parent"], r["id"]))
        linked += 1
        if e.get("own") and not r["identity_key"]:
            t, n, y = e["own"]
            conn.execute(
                "UPDATE documents SET identity_key=?, number=?, year=?,"
                " identity_confidence='regulation_dictionary' WHERE id=?",
                (f"{t}:{n}:{y}", n, y, r["id"]))
            own += 1
    conn.commit()
    return {"linked": linked, "own_identity": own}
