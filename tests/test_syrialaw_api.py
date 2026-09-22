# -*- coding: utf-8 -*-
"""ف٤: مصدر syria-law.com عبر REST — محاكاة بلا شبكة."""
import json
import config
import database
import pytest
import syrialaw_api as sl


def _fake(url):
    if "lawss?" in url:
        return 200, json.dumps([{"id": 12, "name": "بينات ـ المرسوم رقم 359 لعام 1947", "count": 3,
                                 "link": "https://syria-law.com/lawss/binat-359-1947/"}]), {"X-WP-TotalPages": "1"}
    if "laws?lawss=12" in url:
        return 200, json.dumps([
            {"id": 1, "title": {"rendered": "الباب الأول: أحكام عامة من بينات"}, "content": {"rendered": "<p>الباب الأول</p>"}},
            {"id": 2, "title": {"rendered": "مادة 2        من بينات ـ المرسوم رقم 359 لعام 1947"}, "content": {"rendered": "<p>على المدعي إثبات ما يدعيه.</p>"}},
            {"id": 3, "title": {"rendered": "مادة 1 من بينات ـ المرسوم رقم 359 لعام 1947"}, "content": {"rendered": "<p>البينة على من ادعى.</p>"}},
        ]), {"X-WP-TotalPages": "1"}
    return 404, "", {}


def test_list_and_fetch_sorted():
    terms = sl.list_laws(http_get=_fake)
    assert terms[0]["name"].startswith("بينات") and terms[0]["count"] == 3
    arts = sl.fetch_articles(12, http_get=_fake)
    assert [a["num"] for a in arts] == [1, 2, None]
    assert arts[0]["text"] == "البينة على من ادعى."


def test_import_html_has_article_lines():
    arts = sl.fetch_articles(12, http_get=_fake)
    h = sl.to_import_html("بينات ـ المرسوم رقم 359 لعام 1947", arts)
    assert "<h1>بينات" in h and "المادة 1<br/>البينة على من ادعى." in h and "الباب الأول" not in h


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def _fake_big(url):
    """قانون بـ40 مادة يجتاز بوابات الجودة (المحاكاة الصغيرة تُرفض عمداً)."""
    if "lawss?" in url:
        return _fake(url)
    if "laws?lawss=12" in url:
        rows = [{"id": i, "title": {"rendered": f"مادة {i} من بينات ـ المرسوم رقم 359 لعام 1947"},
                 "content": {"rendered": f"<p>على من يدعي خلاف الثابت أصلاً أن يقيم البينة على ذلك برقم {i} من هذا القانون.</p>"}}
                for i in range(1, 41)]
        return 200, json.dumps(rows), {"X-WP-TotalPages": "1"}
    return 404, "", {}


def test_import_saves_document_and_articles(db, monkeypatch):
    monkeypatch.setattr(sl, "POLITE_DELAY", 0)
    rep = sl.import_laws(db, dry_run=False, http_get=_fake_big)
    assert rep["laws"] == 1 and rep["imported"] == 1 and rep["failed"] == 0
    doc = db.execute("SELECT number, year, status FROM documents").fetchone()
    assert (doc["number"], doc["year"], doc["status"]) == (359, 1947, "active")
    assert db.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 40
    # إعادة التشغيل لا تكرر
    rep2 = sl.import_laws(db, dry_run=False, http_get=_fake_big)
    assert rep2["skipped"] == 1 and db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
