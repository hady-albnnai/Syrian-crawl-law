# -*- coding: utf-8 -*-
"""answer.py — «جواب موثَّق» بلا توليد (التسليم 6، إعادة تأطير محلي).

السياسة الموثقة (لا ادعاء RAG توليدي):
- الجواب = **نص المادة نفسها** من المتن (كامل المادة لا القطعة إن قُطعت)،
  لأنه المصدر الأوثق بلا وسيط يخطئ.
- كل جواب يحمل استشهادات: وثيقة + لفظية + رقم مادة + رابط المصدر.
- لا ضرب ⇒ رفض آمن صريح («لا مصدر كافٍ») — لا يُستنتج جواب أبداً.
- تُذكر عدد الرموز المضطردة شفافيةً للمستخدم.

الـAPI الخادمي/OpenAPI/المصادقة تبقى مؤجلة لمسار الخادم الاختياري
(ADR-001)؛ الاستهلاك هنا عبر CLI والواجهة المحلية.
"""
import search


def answer_question(conn, question: str, limit: int = 3,
                    min_matched: int = 2) -> dict:
    hits = search.search(conn, question, limit=limit)
    if not hits:
        return {"status": "refused",
                "answer": None,
                "citations": [],
                "reason": "لا مصدر كافٍ — لا يُستنتج جواب."}
    top = hits[0]
    # رفض المصدر الضعيف: ضربة FTS بكلمة واحدة (مثل «ضريبة» في قانون
    # الرسوم) لا تجعل منه مصدراً لجواب — يلزم تطابق رمزين محتوائيين.
    if search.is_weak(question, top, min_matched):
        return {"status": "refused",
                "answer": None,
                "citations": [],
                "reason": "مصدر ضعيف: تطابق رمز واحد فقط — لا جواب."}
    # نص المادة الكامل (القطعة قد تكون جزءاً من مادة طويلة)
    row = conn.execute("SELECT text FROM articles WHERE id = ?",
                       (top["article_id"],)).fetchone()
    full = row["text"] if row and row["text"] else top["text"]
    citations = [{
        "doc_title": h["doc_title"],
        "label": h["label"],
        "number": h["number"],
        "source_url": h["source_url"],
    } for h in hits]
    return {"status": "answered",
            "answer": full,
            "citations": citations,
            "matched": len([t for t in question.split() if len(t) >= 2])}


def run_qa_eval(conn, questions: list, k: int = 3) -> dict:
    """تقييم عربي للسؤال-جواب: صحة الجواب = صحة إسناد الاستشهاد الأول."""
    good = refused_ok = total_refuse = answered = 0
    details = []
    for q in questions:
        rep = answer_question(conn, q["q"], limit=k)
        expect = q.get("expect")
        if expect is None:
            total_refuse += 1
            ok = rep["status"] == "refused"
            refused_ok += ok
            details.append((q["q"], "رفض آمن" if ok else "أجاب بلا مصدر!", ok))
            continue
        answered += 1
        ok = (rep["status"] == "answered"
              and rep["citations"]
              and rep["citations"][0]["number"] == expect["article"]
              and expect["title_in"] in rep["citations"][0]["doc_title"])
        good += ok
        details.append((q["q"],
                        f"استشهاد أول: {rep['citations'][0]['label']}"
                        if rep["citations"] else "بلا استشهاد", ok))
    return {
        "qa_accuracy": good / max(answered, 1),
        "refusal_precision": refused_ok / max(total_refuse, 1),
        "answered": answered, "refused": total_refuse,
        "total": len(questions), "k": k, "details": details,
    }
