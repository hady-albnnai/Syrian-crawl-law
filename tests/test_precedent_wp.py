# -*- coding: utf-8 -*-
import json, sqlite3
import precedent_wp as pw
from database import create_tables, get_connection

POSTS = [
    {"id": 1, "link": "https://syrian-arbitration.com/2026/05/15/a/",
     "title": {"rendered": "غرفة المخاصمة ورد القضاة / محكمة النقض &#8211; القرار /68/ &#8211; أساس /88/ &#8211; تاريخ 2025/07/22"},
     "content": {"rendered": "<p>أحكام قاضي الأمور المستعجلة المتعلقة بالإكساء لها طبيعة خاصة وتقبل المخاصمة.</p><p>يمكنكم متابعة الوثيقة أدناه، مع الرجاء الانتظار</p>"}},
    {"id": 2, "link": "https://syrian-arbitration.com/2026/05/15/b/",
     "title": {"rendered": "الهيئة العامة المدنية &#8211; محكمة النقض &#8211; القرار /٤٩/ أساس/٢٤٧/ تاريخ 19/08/2025"},
     "content": {"rendered": "<p>مشارطة التحكيم تتطلب تفويضاً خاصاً للمدير من الشركاء.</p>"}},
    {"id": 3, "link": "https://syrian-arbitration.com/2026/05/15/c/",
     "title": {"rendered": "خبر عن ندوة"}, "content": {"rendered": "<p>نص طويل بلا هوية قرار على الإطلاق ولا رقم.</p>"}},
]


def test_classify_title_citation():
    c, r = pw.classify(POSTS[0]["title"]["rendered"], POSTS[0]["content"]["rendered"])
    assert r == "ok"
    assert c.identity_key() == "نقض|68|2025|88"
    assert c.decision_date == "2025-07-22"
    assert "يمكنكم" not in c.principle_text


def test_harvest_writes_pending(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()

    def http_get(url):
        return 200, json.dumps(POSTS), {"X-WP-TotalPages": "1"}
    st = pw.harvest(conn, "https://syrian-arbitration.com/category/articles/", http_get=http_get)
    assert st["written"] == 2 and st["no_identity"] == 1
    n = conn.execute("SELECT COUNT(*) FROM decisions WHERE review_status='pending'").fetchone()[0]
    assert n == 2
    st2 = pw.harvest(conn, "syrian-arbitration.com", http_get=http_get)
    assert st2["seen"] == 2 and st2["written"] == 0
