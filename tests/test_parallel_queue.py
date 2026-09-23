# -*- coding: utf-8 -*-
"""ف٤: عمّال متوازون — حجز ذرّي بالنطاق، WAL، لا مهمة تُؤخذ مرتين."""
import threading
import config
import database
import crawl_queue as q
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "q.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_claim_by_domain_and_domains_listing(db):
    q.enqueue(db, "https://a.example/1", "s", "topic")
    q.enqueue(db, "https://a.example/2", "s", "topic")
    q.enqueue(db, "https://www.b.example/1", "s", "topic")
    assert q.queued_domains(db) == [("a.example", 2), ("b.example", 1)]
    t = q.claim_next(db, "b.example")
    assert t and t["url"].startswith("https://www.b.example")
    assert q.claim_next(db, "b.example") is None
    assert q.claim_next(db, "a.example")["url"] == "https://a.example/1"


def test_two_workers_never_share_a_task(db):
    for i in range(60):
        q.enqueue(db, f"https://a.example/{i}", "s", "topic")
    taken = {0: [], 1: []}

    def worker(k):
        c = database.get_connection()
        while True:
            t = q.claim_next(c, "a.example")
            if t is None:
                break
            taken[k].append(t["id"])
        c.close()

    th = [threading.Thread(target=worker, args=(k,)) for k in (0, 1)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    assert len(taken[0]) + len(taken[1]) == 60
    assert not (set(taken[0]) & set(taken[1]))
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
