# -*- coding: utf-8 -*-
"""chunker.py — سياسة التقطيع للتسليم 5 (إعادة التأطير المحلي).

الوحدة الطبيعية للنص القانوني هي **المادة**؛ لذا chunk = مادة واحدة ما لم
تتجاوز MAX_CHUNK_CHARS فتُقطع عند حدود الفقرات/الجمل مع حمل بيانات
الإسناد (وثيقة/مادة/مسار هرمي/مصدر) في كل قطعة — عقد الاسترجاع §5.
"""
import json
import re

MAX_CHUNK_CHARS = 1200
_SENT_SPLIT = re.compile(r"(?<=[.؟!؛:])\s+")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list:
    """يقطع نصاً طويلاً عند الفقرات ثم الجمل، بلا تمزيق كلمات."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    paras = [p for p in text.split("\n") if p.strip()]
    if len(paras) <= 1:
        paras = [p for p in _SENT_SPLIT.split(text) if p.strip()]
    chunks, cur = [], ""
    for para in paras:
        para = para.strip()
        while len(para) > limit:  # فقرة أطول من السقف: قطع قاسٍ مضطر
            chunks.append(para[:limit])
            para = para[limit:].strip()
        if not para:
            continue
        if cur and len(cur) + 1 + len(para) > limit:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur} {para}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def chunk_document(articles: list, doc: dict) -> list:
    """يعيد قواميس chunks لوثيقة: كل مادة ⇒ قطعة أو أكثر مرقمة seq."""
    out = []
    for a in articles:
        paras = a["paragraphs_json"]
        body = a["text"] or ""
        if paras:
            try:
                loaded = json.loads(paras)
                if loaded:
                    body = "\n".join(loaded)
            except (TypeError, ValueError):
                pass
        label = a["article_label"] or (
            f"المادة {a['article_number']}" if a["article_number"] else "مادة")
        for seq, part in enumerate(split_text(body)):
            out.append({
                "doc_id": doc["id"],
                "article_id": a["id"],
                "seq": seq,
                "number": a["article_number"],
                "label": label,
                "hierarchy_path": a["hierarchy_path"],
                "text": part,
                "char_count": len(part),
                "source_url": doc["source_url"],
                "doc_title": doc["title"],
            })
    return out


def build_chunks(conn) -> dict:
    """يعيد بناء جدول chunks كاملاً من documents/articles (idempotent)."""
    docs = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
    conn.execute("DELETE FROM chunks")
    total = 0
    for d in docs:
        arts = conn.execute(
            "SELECT * FROM articles WHERE doc_id = ? ORDER BY id",
            (d["id"],)).fetchall()
        rows = chunk_document([dict(a) for a in arts], dict(d))
        conn.executemany(
            "INSERT INTO chunks (doc_id, article_id, seq, number, label,"
            " hierarchy_path, text, char_count, source_url, doc_title)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r["doc_id"], r["article_id"], r["seq"], r["number"], r["label"],
              r["hierarchy_path"], r["text"], r["char_count"],
              r["source_url"], r["doc_title"]) for r in rows])
        total += len(rows)
    conn.commit()
    return {"docs": len(docs), "chunks": total}
