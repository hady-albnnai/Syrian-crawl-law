"""البذور تتجاوز مرشّح النطاق المعروف (jus.moj.gov.sy مقابل moj.gov.sy) — دون شبكة."""
import autopilot
import database
import discovery
from discovery import Candidate


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "s.db"))
    database.create_tables()
    return database.get_connection()


def _add_source(conn, url, status):
    conn.execute("INSERT INTO sources (source_key, base_url, name, engine, credibility, status,"
                 " discovered_via, discovered_at) VALUES (?,?,?,?,0.6,?, 'x','2026-01-01')",
                 (discovery._source_key(url), url, url, "unknown", status))
    conn.commit()


def _no_channels(monkeypatch):
    monkeypatch.setattr(autopilot, "mine_corpus_links", lambda *a, **k: [])
    monkeypatch.setattr(autopilot, "wikipedia_candidates", lambda *a, **k: [])


def test_seed_on_registrable_of_old_rejected_source_still_evaluated(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _no_channels(monkeypatch)
    _add_source(conn, "https://moj.gov.sy/", "rejected")   # site القديم الميت
    monkeypatch.setattr(autopilot, "seed_candidates", lambda: [
        Candidate("https://jus.moj.gov.sy/", "jus", via="seed")])
    urls = [c.url for c in autopilot.generate_candidates(conn, snowball=False)]
    assert "https://jus.moj.gov.sy/" in urls


def test_seed_already_registered_or_host_approved_is_skipped(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _no_channels(monkeypatch)
    _add_source(conn, "https://momc.gov.sy/", "proposed")
    _add_source(conn, "https://www.syrian-lawyer.club/deep/page", "approved")
    monkeypatch.setattr(autopilot, "seed_candidates", lambda: [
        Candidate("https://momc.gov.sy/", "momc", via="seed"),
        Candidate("https://www.syrian-lawyer.club/", "club", via="seed"),
        Candidate("https://sana.sy/?cat=214", "sana", via="seed")])
    urls = [c.url for c in autopilot.generate_candidates(conn, snowball=False)]
    assert urls == ["https://sana.sy/?cat=214"]
