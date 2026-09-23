# -*- coding: utf-8 -*-
"""ف٤: اجتهادات syria-law عبر REST — تقسيم المنشور، تصنيف، إدخال (بلا شبكة)."""
import json
import config
import database
import pytest
import precedent_syrialaw as psl
from precedent_parser import parse_citation


def test_split_post_and_classify_syrian():
    post = psl.split_post(
        "موسوعة جرائم الأمن الاقتصادي        58",
        "<p>لا بد لتحقيق الركن المادي لجريمة إلحاق الضرر بالأموال العامة من وقوع ضرر فعلي محقق.</p>"
        "<p>(نقض قرار رقم 841 جناية أساس 735 تاريخ 10/12/1968 موسوعة جرائم الأمن الاقتصادي للأستاذ عبد الناصر سنان الجزء الأول صفحة 58)</p>")
    assert post["collection"] == "موسوعة جرائم الأمن الاقتصادي"
    assert post["principle"].startswith("لا بد لتحقيق") and "(" not in post["principle"]
    c, reason = psl.classify(post)
    assert reason == "ok" and c.identity_key() == "نقض|841|1968|735" and c.publication == "سنان"


def test_foreign_and_unsourced_are_excluded():
    post = psl.split_post("الموسوعة القانونية لأنس كيلاني – قانون العقوبات 2397",
                          "<p>مبدأ مصري طويل بما يكفي ليتجاوز الحد الأدنى للمبدأ القانوني المعتبر.</p><p>(مصر قرار 212 تاريخ 27/4/959 ح 3982 – الموسوعة القانونية لأنس كيلاني)</p>")
    assert psl.classify(post)[1] == "foreign"
    post = psl.split_post("الاجتهادات الخاصة", "<p>مبدأ بلا أي إسناد في آخره وهو طويل بما يكفي ليتجاوز الحد الأدنى.</p>")
    assert psl.classify(post)[1] == "no_ref"


def test_parser_new_formats():
    c = parse_citation("(سورية قرار جنحي 322 تاريخ 11/3/965 قق 1273 – الموسوعة القانونية لأنس كيلاني – قاعدة 2403)")
    assert c.identity_key() == "نقض|322|1965|" and c.decision_date == "1965-03-11" and "court_inferred_kilani" in c.warnings
    c = parse_citation("(نقض سوري جنحة أساس 323 قرر 1511 تاريخ 28/12/1992 موسوعة جرائم الأمن الاقتصادي صفحة 65)")
    assert c.identity_key() == "نقض|1511|1992|323"
    c = parse_citation("(نقض سوري رقم 483 أساس 486 تاريخ 14 / 4 / 1976 سجلات محكمة النقض)")
    assert c.identity_key() == "نقض|483|1976|486" and c.publication == "سجلات النقض"


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "p.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_harvest_writes_pending_and_resumes(db, monkeypatch):
    monkeypatch.setattr(psl, "POLITE_DELAY", 0)
    rows = [
        {"id": 1, "link": "https://syria-law.com/ijtihadat/a/", "title": {"rendered": "موسوعة جرائم الأمن الاقتصادي 1"},
         "content": {"rendered": "<p>لا بد لتحقيق الركن المادي لجريمة إلحاق الضرر بالأموال العامة من وقوع ضرر فعلي محقق.</p><p>(نقض سوري أساس 1757 قرار 1771 تاريخ 19/5/1977 موسوعة جرائم الأمن الاقتصادي صفحة 84)</p>"}},
        {"id": 2, "link": "https://syria-law.com/ijtihadat/b/", "title": {"rendered": "كيلاني 2"},
         "content": {"rendered": "<p>مبدأ مصري طويل بما يكفي ليتجاوز الحد الأدنى للمبدأ القانوني المعتبر هنا.</p><p>(مصر قرار 212 تاريخ 27/4/959 ح 3982)</p>"}},
    ]
    def fake(url):
        return 200, json.dumps(rows if "&page=1&" in url else []), {"X-WP-TotalPages": "1"}
    st = psl.harvest(db, http_get=fake)
    assert st["written"] == 1 and st["foreign"] == 1 and st["new_principles"] == 1
    assert db.execute("SELECT review_status FROM decisions").fetchone()[0] == "pending"
    assert db.execute("SELECT source_site FROM citations").fetchone()[0] == "syria-law.com"
    st2 = psl.harvest(db, http_get=fake)
    assert st2["seen"] == 1 and st2["written"] == 0
