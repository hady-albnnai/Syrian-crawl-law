# -*- coding: utf-8 -*-
import json
import precedent_blogger as pb
from precedent_source import is_broad_candidate_url
from database import create_tables, get_connection

SY = ("<p>319 ـ اكراه:</p><p>إن الإكراه لا يجعل العقود المبرمة تحت سلطانه باطلة بطلاناً مطلقاً.</p>"
      "<p>(نقض مدني سوري 247 أساس 481 تاريخ 27/3/1961)</p>"
      "<p>الاكراه المعطل للرضا لا يتحقق إلا بالتهديد الذي يكون من نتيجته خوف شديد.</p>"
      "<p>(نقض رقم 3182 اساس 10376 تاريخ 4/11/1991 سجلات النقض)</p>"
      "<p>يتوجب اعادة ما ليس مستحقاً إذا دفع تحت الاكراه ولمحكمة الموضوع السلطة التامة.</p>"
      "<p>(قرار نقض رقم 575 أساس 3323 تاريخ 4 / 6 / 1978)</p>")


def _feed(entries):
    return json.dumps({"feed": {"entry": entries}})


def test_blogger_harvest_filters_and_writes(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()
    entries = [
        {"title": {"$t": "اجتهادات سورية"}, "content": {"$t": SY},
         "link": [{"rel": "alternate", "href": "https://b.com/2016/05/a.html"}]},
        {"title": {"$t": "مغربي"}, "content": {"$t": "<p>قرار محكمة النقض عدد 66 بتاريخ 05/02/2015 المغرب</p>"},
         "link": [{"rel": "alternate", "href": "https://b.com/2016/05/b.html"}]},
    ]
    calls = {"n": 0}

    def http_get(url):
        calls["n"] += 1
        return (200, _feed(entries), {}) if "start-index=1" in url else (200, _feed([]), {})
    st = pb.harvest(conn, "b.com", http_get=http_get)
    assert st["posts"] == 2 and st["candidates"] == 1 and st["written"] == 3
    st2 = pb.harvest(conn, "https://b.com/", http_get=http_get)
    assert st2["seen"] == 1 and st2["written"] == 0


def test_broad_candidate_url():
    assert is_broad_candidate_url("https://www.mohamah.net/law/أحكام-و-إجتهادات-قضائية-لمحكمة-النقض-ا/")
    assert not is_broad_candidate_url("https://www.mohamah.net/law/اجتهادات-محكمة-النقض-المصرية/")
    assert not is_broad_candidate_url("https://www.mohamah.net/law/صيغة-ونموذج-طعن-بالنقض/")


def test_blogger_www_fallback_when_apex_dead(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()
    entries = [{"title": {"$t": "اجتهادات سورية"}, "content": {"$t": SY},
                "link": [{"rel": "alternate", "href": "https://b.com/2016/05/a.html"}]}]

    def http_get(url):
        if "www.b.com" in url:
            return (200, _feed(entries) if "start-index=1" in url else _feed([]), {})
        return (404, "", {})
    st = pb.harvest(conn, "b.com", http_get=http_get)
    assert st["site"] == "b.com" and st["written"] == 3
    conn.close()
