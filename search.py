# -*- coding: utf-8 -*-
"""search.py — البحث النصي العربي المحلي (التسليم 5، إعادة تأطير ADR-001).

FTS5 unicode61 أولاً؛ إن أخفق الاستعلام (صياغة خاصة) أو لم يضرب شيئاً
ننتقل لمسار LIKE مع تطبيع عربي خفيف. كل نتيجة تحمل إسنادها الكامل:
وثيقة + مادة + مسار هرمي + رابط المصدر (مخرج التسليم 5 في الخطة).
"""
import re
import unicodedata

_TATWEEL = "ـ"
_ALIF = "أإآٱ"
# كلمات وظيفية عربية: ضربها يلوّث النتائج ويكسر «الرفض الآمن»
_STOP_RAW = {"في", "من", "على", "الى", "عن", "مع", "هذا", "هذه",
             "التي", "الذي", "كل", "ما", "ان", "إن", "أن", "او", "أو",
             "ثم", "قد", "لا", "لم", "لن", "اذا", "إذا", "بعد", "قبل",
             "بين", "عند", "حتى", "غير", "فقط", "كان", "تكون", "يكون"}


def normalize_ar(text: str) -> str:
    """تطبيع خفيف للتطابق الاحتياطي: تشكيل/تطويل/همزات."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace(_TATWEEL, "")
    for a in _ALIF:
        t = t.replace(a, "ا")
    t = t.replace("ى", "ي").replace("ة", "ه")
    return t


STOPWORDS = _STOP_RAW | {normalize_ar(w) for w in _STOP_RAW}


def _fts_query(tokens: list) -> str:
    return " OR ".join(f'"{t}"' for t in tokens)


def _ensure_chunks(conn) -> None:
    n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if n == 0:
        import chunker
        chunker.build_chunks(conn)
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        conn.commit()


def search(conn, query: str, limit: int = 10) -> list:
    """نتائج مرتبة تحمل الإسناد؛ [] تعني «لا مصدر كافٍ» ولا استنتاج."""
    _ensure_chunks(conn)
    # تنظيف الرموز من كل رمز حتى لا تُكسر صياغة FTS5 ولا مسار LIKE
    tokens = [re.sub(r"[^\w؀-ۿ]", "", t)
              for t in (query or "").split()]
    tokens = [t for t in tokens
              if len(t) >= 2 and normalize_ar(t) not in STOPWORDS]
    if not tokens:
        return []
    hits = []
    try:
        rows = conn.execute(
            """SELECT c.id, c.article_id, c.doc_title, c.number, c.label,
                      c.text, c.hierarchy_path, c.source_url, rank
               FROM chunks_fts f JOIN chunks c ON c.id = f.rowid
               WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?""",
            (_fts_query(tokens), limit)).fetchall()
        hits = [dict(r) for r in rows]
    except Exception:
        hits = []
    if not hits:  # المسار الاحتياطي: LIKE على النص المطبَّع
        like = f"%{normalize_ar(' '.join(tokens))}%"
        rows = conn.execute(
            """SELECT id, article_id, doc_title, number, label, text,
                      hierarchy_path, source_url FROM chunks""").fetchall()
        scored = []
        for r in rows:
            words = set(re.split(r"\s+", normalize_ar(r["text"])))
            occ = sum(1 for t in tokens if normalize_ar(t) in words)
            if occ:
                scored.append((occ, dict(r)))
        scored.sort(key=lambda x: -x[0])
        hits = [{**r, "rank": -occ} for occ, r in scored[:limit]]
    return hits[:limit]


def run_eval(conn, questions: list, k: int = 5) -> dict:
    """Recall@k وMRR مقابل إسنادات متوقعة مكتوبة يدوياً من النصوص الفعلية."""
    recall_hits, rr_sum, answered = 0, 0.0, 0
    details = []
    for q in questions:
        res = search(conn, q["q"], limit=k)
        expect = q.get("expect")  # None ⇒ يُتوقع ألا مصدر كافياً
        if expect is None:
            ok = len(res) == 0
            details.append((q["q"], "رفض آمن" if ok else "أجاب بلا مصدر!", ok))
            continue
        answered += 1
        pos = None
        for i, r in enumerate(res, 1):
            if (r["number"] == expect["article"]
                    and expect["title_in"] in (r["doc_title"] or "")):
                pos = i
                break
        if pos:
            recall_hits += 1
            rr_sum += 1.0 / pos
        details.append((q["q"], f"ترتيب الإسناد: {pos or 'غائب'}", bool(pos)))
    n = max(answered, 1)
    return {"recall_at_k": recall_hits / n, "mrr": rr_sum / n,
            "answered": answered, "k": k, "details": details,
            "total": len(questions)}
