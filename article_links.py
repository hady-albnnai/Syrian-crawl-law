"""A-4: ربط التعديل/الإلغاء على مستوى المادة (لا الصك فقط).

من متن الصك المعدِّل: «تعدل المادة 15 من القانون رقم 148 لعام 1949» /
«تلغى المادتان 3 و4 من المرسوم التشريعي رقم …» / «يستعاض عن نص المادة 12
من القانون …». يُكتب في `article_amendments` ثم يُسقَط على
`articles.amended_by` (JSON: قائمة {by, action}) للصك المستهدَف.
كل شيء يُعاد حسابه من الصفر في كل تنقيح — لا بقايا.
"""
import json
import re
from datetime import datetime

from law_identity import LAW_ID_RE, build_identity_key, to_western_digits, _normalize_type, _year_of

_D = r"[0-9٠-٩۰-۹]+"
# فعل → مواد → «من» → صك. الفعل قبل المادة بحد 30 حرفاً.
_VERB = (r"(?P<verb>تعد[لّ]ل?|يعد[لّ]ل?|تلغ[ىي]|يلغ[ىي]|تحذف|يحذف|يستعاض عن نص|"
         r"يستبدل بنص|تستبدل|يستبدل|تضاف|يضاف|تعديل|إلغاء|الغاء)")
_ARTS = (rf"(?P<arts>الماد(?:ة|ه|تان|تين|تا|تي)|المواد)\s*"
         rf"(?P<nums>\(?/?{_D}\)?/?(?:\s*(?:مكرر[ةا]?)?\s*(?:[،,و]|إلى|الى|حتى|-|–)\s*\(?/?{_D}\)?/?)*)"
         r"\s*(?P<bis>مكرر[ةا]?)?")
_LAW = LAW_ID_RE.pattern.replace("(", "(?P<dtype>", 1)  # المجموعة الأولى (النوع) تُسمّى
_PAT = re.compile(_VERB + r"[^.\n]{0,30}?" + _ARTS + r"[^.\n]{0,25}?من\s+[^.\n]{0,60}?" + _LAW)
_RANGE = re.compile(rf"({_D})\s*(?:إلى|الى|حتى|-|–)\s*({_D})")


def _action(verb: str) -> str:
    v = verb
    if v.startswith(("تلغ", "يلغ", "تحذف", "يحذف")) or v in ("إلغاء", "الغاء"):
        return "repeal"
    return "amend"


def _numbers(nums: str) -> list:
    nums = to_western_digits(nums)
    out = []
    for a, b in _RANGE.findall(nums):
        a, b = int(a), int(b)
        if 0 < a <= b <= a + 60:
            out.extend(range(a, b + 1))
    if out:
        return out
    return [int(n) for n in re.findall(r"\d+", nums) if int(n) > 0]


def extract_article_amendments(text: str, own_identity: str | None = None) -> list:
    """[{target_identity, article_number, action, context}] — مواد صكوك أخرى فقط."""
    if not text:
        return []
    seen, out = set(), []
    for m in _PAT.finditer(text):
        # نقطة بين المواد والصك = جملتان مختلفتان («…من هذا القانون. ويلغى القانون رقم…»)
        if "." in text[m.end("nums"):m.start("num")]:
            continue
        try:
            key = build_identity_key(_normalize_type(m.group("dtype")),
                                     int(to_western_digits(m.group("num"))), _year_of(m))
        except (ValueError, TypeError):
            continue
        if own_identity and key == own_identity:
            continue
        action = _action(m.group("verb"))
        for n in _numbers(m.group("nums")):
            art = f"{n} مكرر" if m.group("bis") else str(n)
            k = (key, art, action)
            if k in seen:
                continue
            seen.add(k)
            out.append({"target_identity": key, "article_number": art,
                        "action": action,
                        "context": " ".join(m.group(0).split())[:200]})
    return out


def rebuild_article_links(conn) -> dict:
    """يعيد بناء article_amendments و articles.amended_by من الصكوك النشطة."""
    conn.execute("""CREATE TABLE IF NOT EXISTS article_amendments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amending_doc_id INTEGER NOT NULL,
        target_identity TEXT NOT NULL,
        article_number TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('amend','repeal')),
        context TEXT, created_at TEXT,
        UNIQUE (amending_doc_id, target_identity, article_number, action))""")
    conn.execute("DELETE FROM article_amendments")
    conn.execute("UPDATE articles SET amended_by=NULL, status='active'")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    nat = "AND COALESCE(nature,'instrument')='instrument'" if "nature" in cols else ""
    docs = conn.execute(f"""SELECT id, identity_key, year, clean_content FROM documents
                            WHERE status='active' {nat}""").fetchall()
    links = 0
    now = datetime.now().isoformat()
    for d in docs:
        for a in extract_article_amendments(d["clean_content"] or "", d["identity_key"]):
            conn.execute("""INSERT OR IGNORE INTO article_amendments
                (amending_doc_id, target_identity, article_number, action, context, created_at)
                VALUES (?,?,?,?,?,?)""", (d["id"], a["target_identity"], a["article_number"],
                                          a["action"], a["context"], now))
            links += 1
    # الإسقاط: مادة المستهدَف ← قائمة معدِّليها (حارس الزمن: سنة المعدِّل ≥ سنة المستهدَف)
    touched = repealed = 0
    rows = conn.execute("""SELECT aa.target_identity, aa.article_number, aa.action,
                                  d.identity_key AS by_key, d.year AS by_year
                           FROM article_amendments aa JOIN documents d ON d.id=aa.amending_doc_id
                           ORDER BY d.year, d.number""").fetchall()
    by_art = {}
    for r in rows:
        by_art.setdefault((r["target_identity"], r["article_number"]), []).append(r)
    for (ident, art), evs in by_art.items():
        tgt = conn.execute("SELECT id, year FROM documents WHERE identity_key=? AND status='active'",
                           (ident,)).fetchone()
        if not tgt:
            continue
        evs = [e for e in evs if e["by_year"] is None or tgt["year"] is None or e["by_year"] >= tgt["year"]]
        if not evs:
            continue
        payload = json.dumps([{"by": e["by_key"], "action": e["action"]} for e in evs],
                             ensure_ascii=False)
        st = "repealed" if any(e["action"] == "repeal" for e in evs) else "amended"
        cur = conn.execute("""UPDATE articles SET amended_by=?, status=? WHERE doc_id=?
                              AND article_number=?""", (payload, st, tgt["id"], art))
        touched += cur.rowcount
        repealed += cur.rowcount if st == "repealed" else 0
    conn.commit()
    return {"links": links, "articles_marked": touched, "articles_repealed": repealed}
