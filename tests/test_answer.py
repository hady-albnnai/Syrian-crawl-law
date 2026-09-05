"""اختبارات التسليم 6 (محلي): جواب موثَّق + رفض آمن + تقييم QA."""
import pytest

import answer
import chunker
from crawler import save_document
from database import create_tables


@pytest.fixture
def db(tmp_path, monkeypatch):
    import config
    import database
    dbp = tmp_path / "a.db"
    monkeypatch.setattr(config, "DB_PATH", dbp)
    monkeypatch.setattr(database, "DB_PATH", dbp)
    create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    save_document(cur, "sha256:a1", "مرسوم خطف الأشخاص", "https://x/t1",
                  "جزائي", 0.8, 0.9, "m", "نص", snapshot_sha256=None)
    conn.execute("INSERT INTO articles (id, doc_id, article_number, text,"
                 " char_count) VALUES (11, 1, '2', 'وتكون العقوبة الإعدام"
                 " إذا نجم عن جريمة الخطف وفاة أحد الأشخاص.', 60)")
    conn.commit()
    chunker.build_chunks(conn)
    return conn


def test_answered_with_full_text_and_citations(db):
    rep = answer.answer_question(db, "عقوبة الإعدام الخطف وفاة")
    assert rep["status"] == "answered"
    # الجواب نص المادة الكامل لا القطعة
    assert "الإعدام" in rep["answer"] and rep["answer"].startswith("وتكون")
    c = rep["citations"][0]
    assert c["number"] == "2" and c["doc_title"] == "مرسوم خطف الأشخاص"
    assert c["source_url"] == "https://x/t1"


def test_refusal_without_source(db):
    rep = answer.answer_question(db, "تنظيم الذكاء الاصطناعي في المدارس")
    assert rep["status"] == "refused"
    assert rep["answer"] is None and rep["citations"] == []
    assert "لا مصدر كافٍ" in rep["reason"]


def test_qa_eval_numbers(db):
    qs = [
        {"q": "الإعدام وفاة", "expect": {"article": "2",
                                          "title_in": "خطف"}},
        {"q": "لا وجود له في المتن إطلاقاً", "expect": None},
    ]
    rep = answer.run_qa_eval(db, qs, k=3)
    assert rep["qa_accuracy"] == 1.0
    assert rep["refusal_precision"] == 1.0
    assert rep["answered"] == 1 and rep["refused"] == 1
