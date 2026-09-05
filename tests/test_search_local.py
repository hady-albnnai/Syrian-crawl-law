"""اختبارات التسليم 5 (محلي): chunker + FTS5 عربي + بحث مُسنَد + تقييم."""
import sqlite3

import pytest

import chunker
import search
from crawler import save_document
from database import create_tables


LONG_ART = ("نص طويل. " * 200) + " وخاتمة تخص الخطف السياسي."


@pytest.fixture
def db(tmp_path, monkeypatch):
    import config
    import database
    dbp = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", dbp)
    monkeypatch.setattr(database, "DB_PATH", dbp)
    create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    save_document(cur, "sha256:t1", "مرسوم خطف الأشخاص", "https://x/t1",
                  "جزائي", 0.8, 0.9, "m", "نص", snapshot_sha256=None)
    conn.execute("INSERT INTO articles (doc_id, article_number, text,"
                 " char_count) VALUES (1, '1', 'كل من خطف شخصا يعاقب"
                 " بالأشغال الشاقة المؤبدة.', 40)")
    conn.execute("INSERT INTO articles (doc_id, article_number, text,"
                 " char_count) VALUES (1, '2', ?, ?)",
                 (LONG_ART, len(LONG_ART)))
    conn.commit()
    return conn


class TestChunker:
    def test_short_article_one_chunk(self):
        arts = [{"id": 1, "article_number": "1", "article_label": "المادة 1",
                 "hierarchy_path": None, "text": "نص قصير",
                 "paragraphs_json": None}]
        out = chunker.chunk_document(arts, {"id": 9, "title": "ق",
                                            "source_url": "u"})
        assert len(out) == 1 and out[0]["seq"] == 0
        assert out[0]["doc_title"] == "ق" and out[0]["source_url"] == "u"

    def test_long_article_splits_with_metadata(self):
        arts = [{"id": 2, "article_number": "2", "article_label": "",
                 "hierarchy_path": "باب 1", "text": LONG_ART,
                 "paragraphs_json": None}]
        out = chunker.chunk_document(arts, {"id": 9, "title": "ق",
                                            "source_url": "u"})
        assert len(out) > 1
        assert all(len(c["text"]) <= chunker.MAX_CHUNK_CHARS for c in out)
        assert all(c["label"] == "المادة 2" and c["number"] == "2"
                   and c["hierarchy_path"] == "باب 1" for c in out)
        assert [c["seq"] for c in out] == list(range(len(out)))
        joined = " ".join(c["text"] for c in out)
        assert "خاتمة تخص الخطف السياسي" in joined  # لا ضياع


class TestSearch:
    def test_fts_arabic_with_provenance(self, db):
        chunker.build_chunks(db)
        db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        db.commit()
        hits = search.search(db, "خطف شخصاً يعاقب")
        assert hits and hits[0]["number"] == "1"
        h = hits[0]
        assert h["doc_title"] == "مرسوم خطف الأشخاص"
        assert h["source_url"] == "https://x/t1"  # إسناد كامل

    def test_auto_index_when_empty(self, db):
        hits = search.search(db, "الأشغال الشاقة")
        assert hits and hits[0]["number"] == "1"

    def test_no_source_returns_empty(self, db):
        chunker.build_chunks(db)
        assert search.search(db, "ضريبة القيمة المضافة") == []

    def test_fallback_when_fts_unavailable(self, db):
        chunker.build_chunks(db)
        db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        db.commit()
        db.execute("DROP TABLE chunks_fts")  # عطل FTS ⇒ مسار LIKE المطبَّع
        db.commit()
        hits = search.search(db, "خطف الأشغال")
        assert hits and hits[0]["number"] == "1"


class TestEval:
    def test_recall_and_safe_reject(self, db):
        chunker.build_chunks(db)
        qs = [
            {"q": "خطف يعاقب", "expect": {"article": "1",
                                          "title_in": "خطف"}},
            {"q": "ضريبة لا وجود لها", "expect": None},
        ]
        rep = search.run_eval(db, qs, k=5)
        assert rep["recall_at_k"] == 1.0
        assert rep["details"][1][2] is True  # رفض آمن محسوب
