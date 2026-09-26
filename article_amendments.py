# -*- coding: utf-8 -*-
"""
article_amendments.py — تتبع نفاذ المادة بعينها (ذ19 في خطة ذكاء ميزان).

law_status.py يجيب «هل هذا القانون معدَّل أو ملغى؟» على مستوى الصك كله.
المحامي يسأل أدقّ: «هل المادة 17 من القانون 6/2001 ما زالت نافذة؟».
هذه الوحدة تستخرج من متن كل صك لاحق العبارات التي تقع على **مادة بعينها**
من صك آخر: «تعدل المادة 5 من القانون رقم 28 لعام 2001»، «تلغى المادتان 7
و14 من المرسوم التشريعي رقم 81 لعام 1979»، «يضاف إلى المادة 3 من …»،
وتسجلها بجدول article_amendments ثم تصدّرها لميزان في article_amendments.csv.

حدود صريحة (لا تخمين):
  - الاستخراج نصّي حتمي: فعل + كلمة «المادة/المواد/المادتين» + أرقام + إحالة
    لصك بهويته (law_identity.extract_law_references). ما لم يطابق لا يُسجَّل.
  - «نافذة» في ميزان تعني «لا تعديل ولا إلغاء لهذه المادة بالمتن المتوفر» —
    ويقولها ميزان بهذه الصيغة.
  - الفقرة/البند داخل المادة يُحفظان في السياق فقط؛ الوحدة هي المادة.
"""
import csv
import re
from datetime import datetime
from pathlib import Path

from law_identity import extract_law_identity, extract_law_references

_TASHKEEL = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_HINDI = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# الأعداد الترتيبية الشائعة في صيغة «المادة الأولى» (تكفي حتى العشرين؛ ما بعدها يُكتب رقماً عادةً).
_ORDINALS = {
    "الاولى": 1, "الأولى": 1, "الثانية": 2, "الثالثة": 3, "الرابعة": 4, "الخامسة": 5,
    "السادسة": 6, "السابعة": 7, "الثامنة": 8, "التاسعة": 9, "العاشرة": 10,
    "الحادية عشرة": 11, "الثانية عشرة": 12, "الثالثة عشرة": 13, "الرابعة عشرة": 14,
    "الخامسة عشرة": 15, "السادسة عشرة": 16, "السابعة عشرة": 17, "الثامنة عشرة": 18,
    "التاسعة عشرة": 19, "العشرون": 20,
}
_ORD_RE = "|".join(sorted(map(re.escape, _ORDINALS), key=len, reverse=True))

# الفعل ⇒ الأثر. الإضافة قبل التعديل («يضاف إلى المادة» تعديل بالزيادة، تُميَّز لأن نص المادة الأصلي يبقى).
_REPEAL = re.compile(r"(يلغ[يى]|تلغ[يى]|الغ[يى]|ألغ[يى]|إلغاء|الغاء|ينه[يى] العمل|تنه[يى] العمل|يوقف العمل|توقف العمل)")
_ADD = re.compile(r"(يضاف|تضاف|إضافة|اضافة)")
_AMEND = re.compile(r"(يعدل|تعدل|تعديل|يستبدل|تستبدل|استبدال|يستعاض|تستعاض|يحذف|تحذف|حذف|تصحح|يصحح)")

# «المادة 5» | «المادتين 7 و14» | «المواد 3 و4 و9» | «المواد من 3 إلى 9» | «المادة الأولى» | «/5/»
_ART_WORD = r"(?:المادة|المادتين|المادتان|المواد|مادة)"
_NUM = r"/?\s*[0-9٠-٩]{1,4}\s*/?(?:\s*(?:مكرر|مكررة|مكرراً))?"
_ARTICLES_RE = re.compile(
    rf"{_ART_WORD}\s+(?:رقم\s+|من\s+)?"
    rf"((?:{_NUM}(?:\s*(?:و|،|,|-|إلى|الى|حتى|ولغاية|لغاية)\s*)?)+|(?:{_ORD_RE}))"
)
_RANGE_RE = re.compile(r"([0-9]{1,4})\s*(?:-|إلى|الى|حتى|ولغاية|لغاية)\s*([0-9]{1,4})")
_SELF_RE = re.compile(r"من هذا (?:القانون|المرسوم|النظام)|من هذه (?:اللائحة|التعليمات)")


def _strip(s: str) -> str:
    return _TASHKEEL.sub("", s or "").translate(_HINDI)


def _numbers(chunk: str) -> list[int]:
    """أرقام المواد من مقطع بعد كلمة «المادة»: قوائم ومدى وترتيبي."""
    c = chunk.strip()
    if c in _ORDINALS:
        return [_ORDINALS[c]]
    c = c.translate(_HINDI)
    out: list[int] = []
    m = _RANGE_RE.search(c)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < a <= b < a + 60:
            out.extend(range(a, b + 1))
            c = c[:m.start()] + c[m.end():]
    for n in re.findall(r"[0-9]{1,4}", c):
        v = int(n)
        if 0 < v < 5000 and v not in out:
            out.append(v)
    return out


def _action(verb_zone: str) -> str | None:
    """الأثر من الأفعال الواقعة قبل كلمة المادة (الأقرب يغلب)."""
    best = None
    for act, rx in (("repeal", _REPEAL), ("add", _ADD), ("amend", _AMEND)):
        for m in rx.finditer(verb_zone):
            if best is None or m.end() > best[1]:
                best = (act, m.end())
    return best[0] if best else None


def _segments(text: str) -> list[str]:
    """جمل مستقلة: كل عبارة تعديل تقف عادةً على سطر أو تنتهي بنقطة."""
    return [s.strip() for s in re.split(r"[\n\.؛]+", text) if len(s.strip()) > 15]


def extract_article_amendments(title: str, text: str) -> list[dict]:
    """كل (صك مستهدف، مادة، أثر) في متن هذا الصك. يعيد قائمة قواميس:
    {target_identity, article, action, context}. لا إحالة ذاتية ولا استشهاد محايد."""
    text = _strip(text)
    own = (extract_law_identity(title or "", text) or {}).get("identity_key")
    out: list[dict] = []
    seen: set[tuple] = set()
    for seg in _segments(text):
        refs = extract_law_references(seg)
        if not refs:
            continue
        for ref in refs:
            ident = ref.get("identity_key")
            if not ident or ident == own:
                continue
            before = ref.get("before") or ""
            # المقطع الذي يخص هذه الإحالة: من آخر إحالة سابقة (إن وُجدت) إلى بداية هذه الإحالة.
            zone = before[-220:]
            am = None
            for m in _ARTICLES_RE.finditer(zone):
                am = m  # آخر ذكر للمادة قبل «من القانون …» هو المقصود
            if am is None:
                continue
            tail = zone[am.end():]
            if _SELF_RE.search(tail):
                continue
            act = _action(zone[:am.start()][-120:])
            if act is None:
                continue
            for n in _numbers(am.group(1)):
                key = (ident, n, act)
                if key in seen:
                    continue
                seen.add(key)
                ctx = re.sub(r"\s+", " ", (seg[max(0, seg.find(am.group(0)) - 90):][:200]))
                out.append({"target_identity": ident, "article": n, "action": act, "context": ctx})
    return out


def ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_amendments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amending_doc_id INTEGER NOT NULL,
            target_identity TEXT NOT NULL,
            article INTEGER NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('amend','repeal','add')),
            context TEXT,
            created_at TEXT,
            UNIQUE (amending_doc_id, target_identity, article, action),
            FOREIGN KEY (amending_doc_id) REFERENCES documents(id)
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_art_am_target ON article_amendments(target_identity, article)")


def record_for_doc(conn, doc_row_id: int, title: str, text: str) -> int:
    """تسجيل ما يمسّ موادَّ بعينها في متن وثيقة محفوظة — يعيد عدد الجديد."""
    added = 0
    now = datetime.now().isoformat(timespec="seconds")
    for am in extract_article_amendments(title, text):
        cur = conn.execute(
            """INSERT OR IGNORE INTO article_amendments
                 (amending_doc_id, target_identity, article, action, context, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_row_id, am["target_identity"], am["article"], am["action"], am["context"], now))
        added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return added


def rebuild(conn) -> dict:
    """إعادة البناء من كل الوثائق ذات المتن (صيانة/أول تشغيل)."""
    ensure_table(conn)
    conn.execute("DELETE FROM article_amendments")
    rows = conn.execute(
        "SELECT id, title, clean_content FROM documents WHERE clean_content IS NOT NULL"
    ).fetchall()
    total = 0
    for r in rows:
        total += record_for_doc(conn, r[0], r[1] or "", r[2])
    conn.commit()
    return {"documents": len(rows), "rows": total}


CSV_COLUMNS = ["target_identity", "target_type", "target_number", "target_year", "article", "action",
               "amending_identity", "amending_title", "amending_year", "amending_date",
               "context", "source_url"]


def export_rows(conn) -> list[dict]:
    ensure_table(conn)
    q = """SELECT a.target_identity, a.article, a.action, a.context,
                  d.identity_key, d.title, d.year, d.issue_date, d.source_url
           FROM article_amendments a JOIN documents d ON d.id = a.amending_doc_id
           ORDER BY a.target_identity, a.article, d.year, d.id"""
    out = []
    for r in conn.execute(q).fetchall():
        parts = (r[0] or "").split(":")
        ttype, tnum, tyear = (parts + ["", "", ""])[:3]
        out.append({
            "target_identity": r[0], "target_type": ttype, "target_number": tnum, "target_year": tyear,
            "article": r[1], "action": r[2], "amending_identity": r[4] or "", "amending_title": r[5] or "",
            "amending_year": r[6] or "", "amending_date": r[7] or "",
            "context": (r[3] or "").replace("\n", " "), "source_url": r[8] or "",
        })
    return out


def export_csv(conn, out_path) -> dict:
    rows = export_rows(conn)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return {"count": len(rows), "path": str(p),
            "repeal": sum(r["action"] == "repeal" for r in rows),
            "amend": sum(r["action"] == "amend" for r in rows),
            "add": sum(r["action"] == "add" for r in rows)}
