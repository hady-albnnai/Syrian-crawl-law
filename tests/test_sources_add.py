import argparse
import config, database, cli, discovery


def test_sources_add_persists_the_candidate_after_close(monkeypatch, tmp_path):
    """عطل حي: sources add كان يطبع [170] سُجّل ثم يضيع الصف (لا commit)."""
    p = tmp_path / "a.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    ev = discovery.Evaluation(url="https://arch.example/", ok=True, title="t", verdict="recommended",
                              source_score=76.0, source_type="mixed")
    monkeypatch.setattr(discovery, "evaluate_candidate", lambda url, **kw: ev)
    assert cli.cmd_sources(argparse.Namespace(action="add", id="https://arch.example/")) == 0
    conn = database.get_connection()           # اتصال جديد = ما يراه الأمر التالي فعلاً
    row = conn.execute("SELECT id, status FROM sources WHERE base_url LIKE 'https://arch.example%'").fetchone()
    assert row is not None and row["status"] == "proposed"
    assert cli.cmd_sources(argparse.Namespace(action="approve", id=str(row["id"]))) == 0
    assert database.get_connection().execute(
        "SELECT status, decided_by FROM sources WHERE id=?", (row["id"],)).fetchone()["status"] == "approved"
