"""B-3: مراجعة أزواج التكرار (تقرير للمالك — الطبقة تبقى الحاكمة)."""
import config
import database
import pytest
from dedup import audit_dedup, compare_candidates, rebalance_suspicious


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


def test_overwhelming_completeness_beats_tier_owner_decision():
    # قرار المالك 2026-09-20 (dedup1): 3 مواد ط3 لا تهزم 76 مادة ط4
    frag = {"domain_tier": 3, "is_complete_text": True, "quality_score": 0.9, "article_count": 3}
    full = {"domain_tier": 4, "is_complete_text": True, "quality_score": 0.9, "article_count": 76}
    d = compare_candidates(full, frag)
    assert d["winner"] == "new" and d["decisive_criterion"] == "article_count_overwhelming"
    # فارق صغير: الطبقة تحسم (القانون 8/2007: 61 ط2 مقابل 159 ط4 → 2.6× فقط → الرسمي يبقى)
    d = compare_candidates({**full, "article_count": 159}, {**frag, "domain_tier": 2, "article_count": 61})
    assert d["winner"] == "existing" and d["decisive_criterion"] == "domain_tier"


def test_rebalance_fixes_suspicious_pair(db):
    _doc(db, 1, "active", 3, 3)
    _doc(db, 2, "alternate_source", 4, 76)
    db.commit()
    assert rebalance_suspicious(db) == 1
    st = {r[0]: r[1] for r in db.execute("SELECT id,status FROM documents")}
    assert st == {1: "superseded", 2: "active"}
