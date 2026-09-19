"""B-3: مراجعة أزواج التكرار (تقرير للمالك — الطبقة تبقى الحاكمة)."""
import config
import database
import pytest
from dedup import audit_dedup


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "d.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def _doc(db, i, status, tier, n_articles):
    db.execute("INSERT INTO documents(id,doc_id,title,clean_content,status,nature,identity_key,number,year,"
               "source_domain_tier,is_complete_text,quality_score,source_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (i, f"d{i}", "ق", "المادة 1 نص", status, "instrument", "القانون:1:2000", 1, 2000, tier, 1, 0.9, f"http://x/{i}"))
    for k in range(1, n_articles + 1):
        db.execute("INSERT INTO articles(doc_id,article_number,text) VALUES (?,?,?)", (i, str(k), "نص"))


def test_audit_flags_and_rebalance_fixes(db):
    _doc(db, 1, "active", 2, 11)         # الفائز الحالي: شذرة رسمية
    _doc(db, 2, "superseded", 3, 300)    # الخاسر: كامل
    db.commit()
    a = audit_dedup(db)
    assert len(a) == 1 and a[0]["suspicious"] and a[0]["winner_id"] == 1
