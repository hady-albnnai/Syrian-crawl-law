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
