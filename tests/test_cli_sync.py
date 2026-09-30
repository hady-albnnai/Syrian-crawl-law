"""C-2: أمر sync يطبع سطر JSON أخيراً حتى عند الفشل (ميزان يقرأه)."""
import json
import cli


def test_sync_reports_json_when_export_fails(monkeypatch, capsys):
    class A:
        no_refine = True
        out = "/nonexistent/pkg"
        mizan_root = None
    monkeypatch.setattr("exporter.build_package",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = cli.cmd_sync(A())
    last = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(last)
    assert rc == 1 and data["ok"] is False
    assert "boom" in data["steps"]["export"]["error"]


def test_sync_success_shape(monkeypatch, capsys, tmp_path):
    import config, database
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()

    class A:
        no_refine = True
        out = str(tmp_path)
        mizan_root = str(tmp_path / "mizan")
    monkeypatch.setattr("exporter.build_package",
                        lambda **kw: {"docs": 3, "articles_in_package": 9, "gate_ok": True})
    import mizan_injector as inj
    monkeypatch.setattr(inj, "apply", lambda pkg, root, **kw: {
        "rows": {"added": 1, "index_rows_after": 3, "updated_same_path": 0},
        "files_written": 2, "verify_our_rows": {"ok": True}})
    rc = cli.cmd_sync(A())
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and data["ok"] and data["steps"]["inject"]["added"] == 1
    assert data["steps"]["export"]["docs"] == 3


def test_sync_writes_precedents_layer(monkeypatch, capsys, tmp_path):
    """ف٣: المزامنة تُسقط حزمة الاجتهادات المعتمدة في content/legal_library/precedents."""
    import config, database
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()

    class A:
        no_refine = True
        out = str(tmp_path / "content_package")
        mizan_root = str(tmp_path / "mizan")
    monkeypatch.setattr("exporter.build_package",
                        lambda **kw: {"docs": 3, "articles_in_package": 9, "gate_ok": True})
    import mizan_injector as inj
    monkeypatch.setattr(inj, "apply", lambda pkg, root, **kw: {
        "rows": {"added": 1, "index_rows_after": 3, "updated_same_path": 0},
        "files_written": 2, "verify_our_rows": {"ok": True}})
    rc = cli.cmd_sync(A())
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and data["steps"]["precedents"]["count"] == 0
    assert (tmp_path / "mizan" / "content" / "legal_library" / "precedents" / "precedents.csv").exists()


def _ok_env(monkeypatch, tmp_path):
    import config, database
    import mizan_injector as inj
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    seen = {}

    def fake_build(**kw):
        seen.update(kw)
        return {"docs": 3, "articles_in_package": 9, "gate_ok": True,
                "current_only": kw.get("current_only", False)}
    monkeypatch.setattr("exporter.build_package", fake_build)
    monkeypatch.setattr(inj, "apply", lambda pkg, root, **kw: {
        "rows": {"added": 1, "index_rows_after": 3, "updated_same_path": 0},
        "files_written": 2, "verify_our_rows": {"ok": True}})
    return seen


class _Args:
    no_refine = True

    def __init__(self, tmp_path, **kw):
        self.out = str(tmp_path / "content_package")
        self.mizan_root = str(tmp_path / "mizan")
        self.__dict__.update(kw)


def test_sync_complete_status_when_every_step_ok(monkeypatch, capsys, tmp_path):
    _ok_env(monkeypatch, tmp_path)
    rc = cli.cmd_sync(_Args(tmp_path))
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and data["ok"] and data["status"] == "complete" and data["failed_steps"] == []


def test_sync_is_partial_not_green_when_precedents_fail(monkeypatch, capsys, tmp_path):
    """GAP-08: فشل طبقة الاجتهادات لا يُخفى خلف ok=True."""
    _ok_env(monkeypatch, tmp_path)
    import precedent_export as pe
    monkeypatch.setattr(pe, "build_package",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("precedents boom")))
    rc = cli.cmd_sync(_Args(tmp_path))
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1 and data["ok"] is False and data["status"] == "partial"
    assert data["failed_steps"] == ["precedents"] and "جزئية" in data["error"]
    assert data["steps"]["inject"]["verify_ok"] is True      # القوانين حُقنت فعلاً


def test_sync_is_partial_when_article_amendments_fail(monkeypatch, capsys, tmp_path):
    _ok_env(monkeypatch, tmp_path)
    import article_amendments as aa
    monkeypatch.setattr(aa, "export_csv",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("aa boom")))
    rc = cli.cmd_sync(_Args(tmp_path))
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1 and data["status"] == "partial" and data["failed_steps"] == ["article_amendments"]


def test_sync_failed_status_when_inject_verify_fails(monkeypatch, capsys, tmp_path):
    _ok_env(monkeypatch, tmp_path)
    import mizan_injector as inj
    monkeypatch.setattr(inj, "apply", lambda pkg, root, **kw: {
        "rows": {"added": 0, "index_rows_after": 0, "updated_same_path": 0},
        "files_written": 0, "verify_our_rows": {"ok": False}})
    rc = cli.cmd_sync(_Args(tmp_path))
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1 and data["status"] == "failed" and "inject" in data["failed_steps"]


def test_sync_passes_current_only_to_export(monkeypatch, capsys, tmp_path):
    seen = _ok_env(monkeypatch, tmp_path)
    cli.cmd_sync(_Args(tmp_path, current_only=True))
    assert seen["current_only"] is True
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert data["steps"]["export"]["current_only"] is True


def _spy_precedents(monkeypatch):
    import precedent_export as pe
    captured = {}
    real = pe.build_package

    def spy(conn, **kw):
        captured.update(kw)
        return real(conn, **kw)
    monkeypatch.setattr(pe, "build_package", spy)
    return captured


def test_sync_sends_only_approved_precedents_by_default(monkeypatch, capsys, tmp_path):
    """GAP-09: الافتراضي المعتمد فقط."""
    _ok_env(monkeypatch, tmp_path)
    captured = _spy_precedents(monkeypatch)
    cli.cmd_sync(_Args(tmp_path))
    assert captured["include_pending"] is False
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert data["steps"]["precedents"]["pending_included"] is False


def test_sync_includes_pending_precedents_only_when_asked(monkeypatch, capsys, tmp_path):
    _ok_env(monkeypatch, tmp_path)
    captured = _spy_precedents(monkeypatch)
    cli.cmd_sync(_Args(tmp_path, include_pending_precedents=True))
    assert captured["include_pending"] is True
