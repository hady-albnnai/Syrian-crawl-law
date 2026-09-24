"""تقرير حصاد مقروء — يكتب ملخصاً موجزاً لما في القاعدة إلى docs/HARVEST_REPORT_<تاريخ>.md

يُستخدم بعد انتهاء دورة حصاد طويلة كي يُطّلع على النتيجة دون نسخ نافذة الأوامر.
لا يعدّل القاعدة (قراءة فقط). التشغيل من جذر المستودع:
    python tool\\harvest_report.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from config import DB_PATH  # noqa: E402


def _rows(cur, sql, args=()):
    return cur.execute(sql, args).fetchall()


def _table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(str(x) if x is not None else "—" for x in r) + " |")
    return "\n".join(out)


def _cols(cur, table):
    return {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"لا قاعدة في {DB_PATH}")
        return 1
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    today = date.today().isoformat()
    L = [f"# تقرير الحصاد — {today}", "", f"القاعدة: `{os.path.basename(DB_PATH)}` "
         f"({os.path.getsize(DB_PATH) // (1024 * 1024)} م.ب)", ""]

    # 1) الأعداد الكلية
    L.append("## 1. الأعداد")
    for t in ("documents", "articles", "sources", "crawl_log"):
        try:
            n = _rows(cur, f"SELECT COUNT(*) FROM {t}")[0][0]
        except sqlite3.Error:
            continue
        L.append(f"- {t}: **{n}**")
    active = _rows(cur, "SELECT COUNT(*) FROM documents WHERE status='active'")[0][0]
    art = _rows(cur, "SELECT COUNT(*) FROM articles WHERE doc_id IN "
                     "(SELECT id FROM documents WHERE status='active')")[0][0]
    L.append(f"- قابلة للتصدير (active): **{active}** وثيقة / **{art}** مادة")
    L.append("")

    # 2) حسب الحالة والنوع والطبيعة
    L.append("## 2. حسب الحالة / النوع / الطبيعة")
    L.append(_table(_rows(cur, "SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY 2 DESC"),
                    ["status", "عدد"]))
    L.append("")
    L.append(_table(_rows(cur, "SELECT COALESCE(doc_type,'—'), COUNT(*) FROM documents "
                               "WHERE status='active' GROUP BY 1 ORDER BY 2 DESC"),
                    ["doc_type", "عدد (active)"]))
    L.append("")
    dcols = _cols(cur, "documents")
    if "nature" in dcols:
        L.append(_table(_rows(cur, "SELECT COALESCE(nature,'—'), COUNT(*) FROM documents "
                                   "WHERE status='active' GROUP BY 1 ORDER BY 2 DESC"),
                        ["nature", "عدد (active)"]))
        L.append("")
    if "legal_status" in dcols:
        L.append(_table(_rows(cur, "SELECT COALESCE(legal_status,'—'), COUNT(*) FROM documents "
                                   "WHERE status='active' GROUP BY 1 ORDER BY 2 DESC"),
                        ["legal_status", "عدد (active)"]))
        L.append("")

    # 3) حسب الفرع
    L.append("## 3. حسب الفرع القانوني (active)")
    L.append(_table(_rows(cur, "SELECT COALESCE(branch,'—'), COUNT(*) FROM documents "
                               "WHERE status='active' GROUP BY 1 ORDER BY 2 DESC LIMIT 40"),
                    ["branch", "عدد"]))
    L.append("")

    # 4) حسب النطاق (المصدر)
    L.append("## 4. حسب موقع المصدر (active)")
    dom = {}
    for (u,) in _rows(cur, "SELECT source_url FROM documents WHERE status='active'"):
        d = urlparse(u or "").netloc.lower().replace("www.", "") or "—"
        dom[d] = dom.get(d, 0) + 1
    L.append(_table(sorted(dom.items(), key=lambda x: -x[1]), ["النطاق", "وثائق"]))
    L.append("")

    # 5) حسب العقد الزمني
    L.append("## 5. حسب عقد الصدور (active)")
    L.append(_table(_rows(cur, "SELECT CASE WHEN year IS NULL THEN '—' ELSE (year/10)*10 || 's' END, "
                               "COUNT(*) FROM documents WHERE status='active' GROUP BY 1 ORDER BY 1"),
                    ["العقد", "عدد"]))
    L.append("")

    # 6) آخر الدورات
    L.append("## 6. آخر 15 دورة حصاد")
    try:
        L.append(_table(_rows(cur, "SELECT id, substr(started_at,1,16), mode, pages, docs, articles, "
                                   "skipped, failures FROM crawl_runs ORDER BY id DESC LIMIT 15"),
                        ["#", "بدأت", "نمط", "صفحات", "وثائق", "مواد", "تخطي", "إخفاق"]))
    except sqlite3.Error:
        L.append("(لا جدول crawl_runs)")
    L.append("")

    # 7) آخر ما أُضيف
    L.append("## 7. آخر 150 وثيقة أُضيفت (الأحدث أولاً)")
    L.append(_table(_rows(cur, "SELECT substr(scraped_at,1,10), COALESCE(doc_type,'—'), number, year, "
                               "substr(title,1,70), (SELECT COUNT(*) FROM articles a WHERE a.doc_id=d.id) "
                               "FROM documents d WHERE status='active' ORDER BY scraped_at DESC LIMIT 150"),
                    ["تاريخ", "نوع", "رقم", "سنة", "العنوان", "مواد"]))
    L.append("")

    # 8) المصادر
    L.append("## 8. المصادر المسجلة")
    L.append(_table(_rows(cur, "SELECT id, status, engine, substr(name,1,40), base_url FROM sources ORDER BY id"),
                    ["#", "حالة", "محرك", "الاسم", "الرابط"]))
    L.append("")

    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    out = os.path.join(ROOT, "docs", f"HARVEST_REPORT_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"كُتب: {out}")
    print(f"active = {active} وثيقة / {art} مادة")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
