import argparse
import config, database, cli


def _db(monkeypatch, tmp_path):
    p = tmp_path / "u.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    return database.get_connection()


def test_seed_urls_only_enqueues_urls_covered_by_approved_source(monkeypatch, tmp_path):
    conn = _db(monkeypatch, tmp_path)
    conn.execute("INSERT INTO sources(source_key,base_url,name,status) "
                 "VALUES('a','https://arch.example/','arch','approved')")
    conn.commit()
    f = tmp_path / "urls.txt"
    f.write_text("https://arch.example/one/\nhttps://arch.example/one/\nhttps://evil.example/x\n"
                 "# comment\nhttps://arch.example/two/\n", encoding="utf-8")
    ns = argparse.Namespace(file=str(f), section="s", limit=None, dry=True)
    assert cli.cmd_seed_urls(ns) == 0
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0     # dry
    ns.dry = False
    assert cli.cmd_seed_urls(ns) == 0
    urls = sorted(r[0] for r in conn.execute("SELECT url FROM crawl_tasks"))
    assert len(urls) == 2 and all("arch.example" in u for u in urls)               # evil مرفوض، المكرر مرة واحدة
    ns.limit = 1
    assert cli.cmd_seed_urls(ns) == 0                                              # لا يكرر


def test_seed_urls_unapproved_source_enqueues_nothing(monkeypatch, tmp_path):
    conn = _db(monkeypatch, tmp_path)
    f = tmp_path / "urls.txt"
    f.write_text("https://arch.example/one/\n", encoding="utf-8")
    assert cli.cmd_seed_urls(argparse.Namespace(file=str(f), section="s", limit=None, dry=False)) == 0
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0


def test_seed_urls_missing_file_returns_error(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    assert cli.cmd_seed_urls(argparse.Namespace(file=str(tmp_path / "nope.txt"), section="s",
                                                limit=None, dry=False)) == 2
