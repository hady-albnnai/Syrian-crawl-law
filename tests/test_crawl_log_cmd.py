import argparse
import config, database, cli


def test_crawl_log_filters_by_url_and_is_read_only(monkeypatch, tmp_path):
    p = tmp_path / "l.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    database.insert_log("https://pministry.gov.sy/robots.txt", "robots_error", "SSLError — fail-closed", "blocked")
    database.insert_log("https://other.sy/x", "fetch", "ok", "success")
    lines = []
    monkeypatch.setattr(cli.log, "info", lambda m, *a, **k: lines.append(str(m)))
    assert cli.cmd_crawl_log(argparse.Namespace(contains="pministry", last=5)) == 0
    text = "\n".join(lines)
    assert "matches=1" in text and "robots_error [blocked] SSLError" in text and "other.sy" not in text
    assert database.get_connection().execute("SELECT COUNT(*) FROM crawl_log").fetchone()[0] == 2
