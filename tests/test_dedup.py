# -*- coding: utf-8 -*-
"""اختبارات dedup — مطابقة القاعدة وتنقيح التكرار (محلية، لا شبكة).

تحرس ترتيب الأولوية الذي حدده المالك صراحة: المصدر الرسمي أولاً، ثم
اكتمال النص، ثم بقية معايير الجودة عند التعادل فقط.
"""
import sqlite3

import pytest

import database
import dedup


def _cand(domain_tier=4, is_complete=True, quality=0.5, articles=5,
         hierarchy=False, length=1000):
    return {"domain_tier": domain_tier, "is_complete_text": is_complete,
            "quality_score": quality, "article_count": articles,
            "has_hierarchy": hierarchy, "text_length": length}


# ───────────────────────── ترتيب الأولوية ─────────────────────────

def test_official_source_wins_regardless_of_lower_quality():
    # جديدة من مصدر رسمي (tier=1) لكن جودة أقل من القديمة (tier=4)
    new = _cand(domain_tier=1, quality=0.2, articles=2)
    existing = _cand(domain_tier=4, quality=0.9, articles=50)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "domain_tier"


def test_lower_tier_number_beats_higher_tier_number():
    new = _cand(domain_tier=2)
    existing = _cand(domain_tier=1)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "existing"
    assert r["decisive_criterion"] == "domain_tier"


def test_completeness_decides_when_tier_tied():
    new = _cand(domain_tier=4, is_complete=True, quality=0.1)
    existing = _cand(domain_tier=4, is_complete=False, quality=0.9)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "is_complete_text"


def test_quality_score_decides_when_tier_and_completeness_tied():
    new = _cand(domain_tier=4, is_complete=True, quality=0.8)
    existing = _cand(domain_tier=4, is_complete=True, quality=0.5)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "quality_score"


def test_article_count_decides_when_quality_tied():
    new = _cand(quality=0.5, articles=10)
    existing = _cand(quality=0.5, articles=3)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "article_count"


def test_hierarchy_decides_when_article_count_tied():
    new = _cand(articles=5, hierarchy=True)
    existing = _cand(articles=5, hierarchy=False)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "has_hierarchy"


def test_text_length_decides_last():
    new = _cand(hierarchy=True, length=2000)
    existing = _cand(hierarchy=True, length=500)
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "new"
    assert r["decisive_criterion"] == "text_length"


def test_full_tie_returns_tie_and_favors_no_change():
    new = _cand()
    existing = _cand()
    r = dedup.compare_candidates(new, existing)
    assert r["winner"] == "tie"
    assert r["decisive_criterion"] is None


# ───────────────────────── سجل القرارات + النسخ ─────────────────────────

@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "dedup_test.db"))
    database.create_tables()
    return database.get_connection()


def test_record_dedup_decision_persists_audit_row(db_conn):
    cur = db_conn.cursor()
    dedup.record_dedup_decision(cur, "القانون:10:2015", winner_doc_id=1,
                                loser_doc_id=2, decisive_criterion="domain_tier",
                                winner_value=-1, loser_value=-4)
    db_conn.commit()
    row = cur.execute("SELECT * FROM dedup_decisions").fetchone()
    assert row["identity_key"] == "القانون:10:2015"
    assert row["winner_doc_id"] == 1
    assert row["decisive_criterion"] == "domain_tier"


def test_archive_document_version_copies_not_deletes(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content) "
        "VALUES ('sha256:winner', 'قانون فائز', 'https://new.example/x', 'نص')")
    winner_id = cur.lastrowid
    doc_row = {"doc_id": "sha256:xxx", "title": "قانون قديم",
              "source_url": "https://old.example/x", "clean_content": "نص",
              "quality_score": 0.4}
    dedup.archive_document_version(cur, original_doc_id=winner_id,
                                   doc_row=doc_row,
                                   reason="استُبدلت بنسخة رسمية أفضل")
    db_conn.commit()
    row = cur.execute("SELECT * FROM document_versions").fetchone()
    assert row["title"] == "قانون قديم"
    assert row["superseded_reason"] == "استُبدلت بنسخة رسمية أفضل"


def test_find_existing_by_identity_returns_active_only(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO documents (doc_id, title, source_url, identity_key, "
        "status, clean_content) VALUES (?, ?, ?, ?, 'active', 'نص')",
        ("sha256:a", "قانون أ", "https://x.example/a", "القانون:1:2000"))
    cur.execute(
        "INSERT INTO documents (doc_id, title, source_url, identity_key, "
        "status, clean_content) VALUES (?, ?, ?, ?, 'superseded', 'نص')",
        ("sha256:b", "قانون ب", "https://x.example/b", "القانون:2:2000"))
    db_conn.commit()

    found = dedup.find_existing_by_identity(cur, "القانون:1:2000")
    assert found["title"] == "قانون أ"

    not_found = dedup.find_existing_by_identity(cur, "القانون:2:2000")
    assert not_found is None  # superseded لا تُطابَق

    assert dedup.find_existing_by_identity(cur, None) is None
