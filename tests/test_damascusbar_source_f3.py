"""ف٣: محرك منتدى محامي سوريا عبر Wayback — بلا شبكة (لقطتان حقيقيتان محفوظتان)."""
from pathlib import Path

import config
import database
import pytest
import damascusbar_source as ds

FIX = Path(__file__).parent / "fixtures"
T1 = (FIX / "damascusbar_thread_22726.html").read_text(encoding="utf-8")
T0 = (FIX / "damascusbar_thread_8355.html").read_text(encoding="utf-8")
CDX = ("http://www.damascusbar.org:80/AlMuntada/showthread.php? 20090822185814\n"
       "http://damascusbar.org/AlMuntada/showthread.php?t=22726&fbclid=xyz 20191210183707\n"
       "http://www.damascusbar.org:80/AlMuntada/showthread.php?s=abc&t=22726 20110210145214\n"
       "http://www.damascusbar.org:80/AlMuntada/showthread.php?t=8355 20170101000000\n")


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def fake_bytes(url):
    if "cdx/search" in url:
        return CDX.encode()
    if "t=22726" in url:
        assert "/web/20191210183707id_/http://damascusbar.org/AlMuntada/showthread.php?t=22726&fbclid=xyz" in url
        return T1.encode("windows-1256", "replace")
    if "t=8355" in url:
        return T0.encode("windows-1256", "replace")
    return None


def test_thread_map_latest_snapshot_per_thread():
    m = ds.thread_map(CDX)
    assert m["22726"] == ["20191210183707", "http://damascusbar.org/AlMuntada/showthread.php?t=22726&fbclid=xyz"]
    assert m["8355"][0] == "20170101000000" and len(m) == 2


def test_thread_text_and_title_from_real_snapshot():
    t = ds.thread_text(T1)
    assert "القضية : 152 أساس لعام 2009" in t and "المبدأ : بينات – أدلة – تقدير محكمة الموضوع" in t
    assert ds.thread_title(T1).startswith("الاجتهادات القضائية الواردة في مجلة المحامين")
    assert ds.thread_text(T0) == ""          # خيط بلا مشاركات ظاهرة


def test_decode_cp1256_roundtrip():
    assert "القضية" in ds.decode_snapshot(T1.encode("windows-1256", "replace"))


def test_harvest_writes_pending_and_resumes(db):
    rep = ds.harvest_damascusbar(db, fake_bytes)
    assert rep["threads"] == 2 and rep["fetched"] == 2 and rep["with_precedents"] == 1
    assert rep["citations"] >= 12 and rep["new_decisions"] == rep["citations"] - rep["unsourced"]
    row = db.execute("SELECT court, decision_number, decision_year, basis_number, decision_date, chamber_raw, review_status"
                     " FROM decisions WHERE identity_key='نقض|23|2009|152'").fetchone()
    assert tuple(row) == ("نقض", "23", 2009, "152", "2009-02-15", "المدنية الأولى", "pending")
    p = db.execute("SELECT text FROM principles p JOIN decisions d ON d.id=p.decision_id WHERE d.identity_key='نقض|23|2009|152'").fetchone()[0]
    assert p.startswith("يستقل قاضي الموضوع") and "أسباب طعن" not in p   # التعليل الكامل لا يدخل المبدأ
    c = db.execute("SELECT source_site, snapshot_ts, source_url FROM citations LIMIT 1").fetchone()
    assert tuple(c) == ("damascusbar.org", "20191210183707", "http://www.damascusbar.org/AlMuntada/showthread.php?t=22726")
    # الاستئناف: كلا الخيطين مسجّلان (حتى الفارغ) فلا يُجلب شيء
    rep2 = ds.harvest_damascusbar(db, fake_bytes)
    assert rep2["already_done"] == 2 and rep2["fetched"] == 0
    assert ds._threads_file().exists() and ds._done_file().exists()


def test_dry_run_writes_nothing(db):
    rep = ds.harvest_damascusbar(db, fake_bytes, dry_run=True, limit=1)
    assert rep["fetched"] == 1
    assert db.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
    assert not ds._done_file().exists()


def test_aborts_after_consecutive_connection_failures(db, monkeypatch):
    calls = []

    def dead(url):
        if "cdx/search" in url:
            return CDX.encode()
        calls.append(url)
        return None
    big = "\n".join(f"http://www.damascusbar.org/AlMuntada/showthread.php?t={i} 2020010100000{i%10}" for i in range(20))
    monkeypatch.setattr(ds, "thread_map", lambda txt: {str(i): ["20200101000000", f"http://x/?t={i}"] for i in range(20)})
    rep = ds.harvest_damascusbar(db, dead)
    assert rep["failed"] == ds.MAX_CONSECUTIVE_FAILURES and len(calls) == ds.MAX_CONSECUTIVE_FAILURES
    assert "غير قابل للوصول" in rep["aborted"]
    assert not ds._done_file().exists()          # لا شيء يُسجَّل كمُنجَز عند الفشل
