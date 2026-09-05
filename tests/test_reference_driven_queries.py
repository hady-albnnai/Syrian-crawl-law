# -*- coding: utf-8 -*-
"""اختبارات reference_driven_queries — القطعة الثانية من خطة الاكتشاف
الذاتي للمصادر (§3): إشارات نصية داخل المتن المحفوظ → استعلامات بحث،
مع تفادي البحث عن قوانين موجودة أصلاً بالقاعدة (§3.4).
"""
import autopilot
import database


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "refq.db"))
    database.create_tables()
    return database.get_connection()


def _insert_doc(conn, doc_id, identity_key, clean_content, status="active"):
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "identity_key, status) VALUES (?, ?, ?, ?, ?, ?)",
        (doc_id, "قانون", f"https://x.example/{doc_id}", clean_content,
         identity_key, status))
    conn.commit()


def test_generates_query_for_unknown_reference(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "d1", "القانون:9:2022",
               "المادة 6- عدلت بموجب المرسوم رقم 14 لعام 2023.")
    queries = autopilot.reference_driven_queries(conn)
    assert "المرسوم رقم 14 لعام 2023 سوريا نص كامل" in queries


def test_no_query_generated_for_reference_already_in_db(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "d1", "القانون:9:2022",
               "المادة 6- عدلت بموجب المرسوم رقم 14 لعام 2023.")
    _insert_doc(conn, "d2", "المرسوم:14:2023", "نص هذا المرسوم موجود فعلاً.")
    queries = autopilot.reference_driven_queries(conn)
    assert queries == []


def test_superseded_documents_not_scanned_for_references(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "d1", "القانون:9:2022",
               "عدلت بموجب المرسوم رقم 99 لعام 2030.",
               status="superseded")
    queries = autopilot.reference_driven_queries(conn)
    assert queries == []


def test_respects_limit(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    refs_text = " ".join(
        f"عدلت بموجب المرسوم رقم {n} لعام 2020." for n in range(1, 20))
    _insert_doc(conn, "d1", "القانون:9:2022", refs_text)
    queries = autopilot.reference_driven_queries(conn, limit=3)
    assert len(queries) == 3


def test_duplicate_references_across_documents_deduplicated(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "d1", "القانون:1:2020",
               "عدلت بموجب المرسوم رقم 5 لعام 2021.")
    _insert_doc(conn, "d2", "القانون:2:2020",
               "أشير أيضاً للمرسوم رقم 5 لعام 2021 بموضع آخر.")
    queries = autopilot.reference_driven_queries(conn)
    assert queries.count("المرسوم رقم 5 لعام 2021 سوريا نص كامل") == 1
