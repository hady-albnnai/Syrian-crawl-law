"""سياسة مسارات الاستيراد المتخصصة — fixtures محلية بلا شبكة/pyarrow."""
import database
import hf_syria_laws as hf


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "imports.db"))
    database.create_tables()
    return database.get_connection()


def _pair():
    return [({"id": "law-1", "title": "قانون رقم 1 لعام 2000",
              "source_url": "https://parliament.gov.sy/laws/law-1"},
             [{"text": "المادة 1 — نص تجريبي"}])]


def _approve_parliament(conn):
    conn.execute("INSERT INTO sources (source_key, base_url, name, status) "
                 "VALUES ('parliament', 'https://parliament.gov.sy/', "
                 "'مجلس الشعب', 'approved')")
    conn.commit()


def test_hf_import_does_not_queue_unapproved_original(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(hf, "load_laws_with_articles", lambda *_a, **_k: _pair())
    rep = hf.import_hf_laws(conn)
    assert rep["unapproved"] == 1
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    conn.close()


def test_hf_import_dry_run_has_no_queue_side_effect(tmp_path, monkeypatch):
    import crawler

    conn = _db(tmp_path, monkeypatch)
    _approve_parliament(conn)
    monkeypatch.setattr(hf, "load_laws_with_articles", lambda *_a, **_k: _pair())
    monkeypatch.setattr(crawler, "_handle_topic", lambda *_a, **_k: None)
    rep = hf.import_hf_laws(conn, dry_run=True)
    assert rep["imported"] == 1
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    conn.close()


def test_hf_import_queues_only_after_source_approval(tmp_path, monkeypatch):
    import crawler

    conn = _db(tmp_path, monkeypatch)
    _approve_parliament(conn)
    monkeypatch.setattr(hf, "load_laws_with_articles", lambda *_a, **_k: _pair())
    monkeypatch.setattr(crawler, "_handle_topic", lambda *_a, **_k: None)
    monkeypatch.setattr(hf, "Path", lambda _value: tmp_path / "hf_syria_laws.py")
    rep = hf.import_hf_laws(conn)
    assert rep["unapproved"] == 0
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 1
    conn.close()
