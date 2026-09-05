# -*- coding: utf-8 -*-
"""اختبارات دفعة P0 — محلية بالكامل، لا تحتاج شبكة.

تحرس الإصلاحات الثلاثة التي خالفت الخطة (انظر DELIVERY/ADR-001):
1. استقرار معرّف الوثيقة (بديل doc_<timestamp> الزمني).
2. منع تكرار الوثائق والمواد عند إعادة التشغيل (idempotency).
3. التطبيق الفعلي لفحص robots.txt (بديل الغلاف الذي يعيد True دائماً).
4. الدرجة القانونية محسوبة لا ثابتة (بديل 85.0 الوهمية).

التشغيل: pytest tests/ -v
"""
import pytest

import database
import fetcher
from crawler import canonicalize_url, make_doc_id, clean_url, save_document
from extractor import legal_score


# ───────────────────────────── 1) استقرار المعرّف ─────────────────────────────

def test_doc_id_is_stable_across_calls():
    u = "https://law-library.syriaforums.net/t123-topic"
    first = make_doc_id(u)
    second = make_doc_id(u)
    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_doc_id_ignores_fragment_query_and_trailing_slash():
    a = make_doc_id("https://example.org/t9-law?a=1#top")
    b = make_doc_id("https://example.org/t9-law/")
    assert a == b


def test_doc_id_ignores_host_letter_case():
    a = make_doc_id("https://EXAMPLE.org/t9-law")
    b = make_doc_id("https://example.org/t9-law")
    assert a == b


def test_doc_id_differs_for_different_pages():
    assert make_doc_id("https://example.org/t1") != make_doc_id("https://example.org/t2")


def test_canonicalize_url_keeps_path_case():
    # تطبيع المضيف فقط — مسار phpBB حساس لحالة الأحرف ولا يجوز lower() له
    c = canonicalize_url("https://Example.ORG/t9-MyTopic?x=1")
    assert c == "https://example.org/t9-MyTopic"


def test_clean_url_strips_fragment_and_query():
    assert clean_url("https://x.org/a?b=1#c") == "https://x.org/a"


# ──────────────────────── 2) منع التكرار (idempotency) ────────────────────────

def _make_tmp_db(tmp_path, monkeypatch):
    """يوجّه قاعدة البيانات إلى ملف مؤقت — لا نلمس قاعدة المستخدم أبداً."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test_p0.db"))
    database.create_tables()
    return database.get_connection()


def test_save_document_is_idempotent(tmp_path, monkeypatch):
    conn = _make_tmp_db(tmp_path, monkeypatch)
    cursor = conn.cursor()
    doc_id = make_doc_id("https://example.org/t5-law")
    args = (doc_id, "قانون اختبار", "https://example.org/t5-law",
            "civil_law", 0.9, 77.0, "hash-1", "نص القانون")

    row_id_1, created_1 = save_document(cursor, *args)
    assert created_1 is True
    assert row_id_1 is not None

    row_id_2, created_2 = save_document(cursor, *args)
    assert created_2 is False
    assert row_id_2 == row_id_1

    cursor.execute("SELECT COUNT(*) AS c FROM documents")
    assert cursor.fetchone()["c"] == 1
    conn.close()


def test_rerun_does_not_duplicate_articles(tmp_path, monkeypatch):
    """يحاكي إعادة تشغيل الزحف: الوثيقة نفسها تُحفظ مرة واحدة وتُتخطى،
    فلا تُضاف مواد مكررة أو يتيمة (العلة السابقة: INSERT OR IGNORE +
    lastrowid غير موثوق عند التجاهل)."""
    conn = _make_tmp_db(tmp_path, monkeypatch)
    cursor = conn.cursor()
    doc_id = make_doc_id("https://example.org/t7-law")
    args = (doc_id, "قانون اختبار 2", "https://example.org/t7-law",
            "penal_law", 0.8, 65.0, "hash-2", "نص")

    row_id, created = save_document(cursor, *args)
    assert created is True
    cursor.execute(
        "INSERT INTO articles (doc_id, article_number, article_label, text, char_count)"
        " VALUES (?, ?, ?, ?, ?)", (row_id, "1", "المادة 1", "نص المادة", 9))
    conn.commit()

    # إعادة تشغيل: نفس الرابط
    row_id_2, created_2 = save_document(cursor, *args)
    assert created_2 is False  # → الزاحف يتخطى ولا يضيف مواد ثانية

    cursor.execute("SELECT COUNT(*) AS c FROM articles")
    assert cursor.fetchone()["c"] == 1
    conn.close()


# ───────────────────────── 3) robots.txt فعلياً ─────────────────────────

class _FakeParser:
    def __init__(self, allowed: bool):
        self.allowed = allowed

    def can_fetch(self, useragent: str, url: str) -> bool:
        return self.allowed


def test_is_allowed_respects_robots_cache(monkeypatch):
    monkeypatch.setattr(fetcher, "RESPECT_ROBOTS", True)
    fetcher._ROBOT_CACHE.clear()
    fetcher._ROBOT_CACHE["blocked.example"] = _FakeParser(False)
    fetcher._ROBOT_CACHE["open.example"] = _FakeParser(True)

    assert fetcher.is_allowed("https://blocked.example/t1") is False
    assert fetcher.is_allowed("https://open.example/t1") is True
    fetcher._ROBOT_CACHE.clear()


def test_is_allowed_disabled_flag(monkeypatch):
    monkeypatch.setattr(fetcher, "RESPECT_ROBOTS", False)
    fetcher._ROBOT_CACHE.clear()
    assert fetcher.is_allowed("https://whatever.example/x") is True


# ──────────────────── 4) الدرجة القانونية محسوبة لا ثابتة ────────────────────

def test_legal_score_varies_with_content():
    weak = "نص عادي بلا أي إشارة قانونية"
    strong = ("القانون رقم 84 — مجلس الشعب — بناء على أحكام الدستور — يرسم ما يلي: "
              "المادة 1- نص. المادة 2- نص. المادة 3- نص. " + "مادة قانونية طويلة. " * 60)
    s_weak = legal_score(weak)
    s_strong = legal_score(strong)
    assert s_strong > s_weak
    assert s_strong != 85.0 or s_weak != 85.0  # ليست ثابتة للجميع
    assert 0.0 <= s_weak <= 100.0
    assert 0.0 <= s_strong <= 100.0


def test_legal_score_empty_text_is_zero():
    assert legal_score("") == 0.0
