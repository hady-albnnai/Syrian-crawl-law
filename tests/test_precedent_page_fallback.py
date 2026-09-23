# -*- coding: utf-8 -*-
"""اختبار مسار الأرشيف الاحتياطي في أمر `precedents-page` (ف٥)."""
import types

import cli
import fetcher
import wayback_source as wb
from database import create_tables

SY_HTML = ("<html><body><p>مبدأ قانوني مستقر.</p>"
           "<p>(نقض مدني سوري 247 أساس 481 تاريخ 27/3/1961)</p>"
           "<p>لا اجتهاد مع وجود النص.</p>"
           "<p>(نقض رقم 3182 اساس 10376 تاريخ 4/11/1991 سجلات النقض)</p>"
           "<p>العقد شريعة المتعاقدين.</p>"
           "<p>(قرار نقض رقم 575 أساس 3323 تاريخ 4 / 6 / 1978)</p>"
           "</body></html>")
URL = "https://example.com/blog/سورية-اجتهادات/"


def _setup(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    return database


def _args(*urls):
    return types.SimpleNamespace(urls=list(urls), force=False)


def test_live_success_never_touches_archive(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(fetcher, "fetch", lambda u: {"ok": True, "html": SY_HTML})
    calls = []
    monkeypatch.setattr(wb, "as_pipeline_result", lambda u: calls.append(u) or {"ok": False})
    assert cli.cmd_precedents_page(_args(URL)) == 0
    assert calls == []
    assert db.get_connection().execute("SELECT count(*) FROM decisions").fetchone()[0] == 3


def test_dead_link_falls_back_to_archive(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(fetcher, "fetch", lambda u: {"ok": False})
    monkeypatch.setattr(wb, "as_pipeline_result",
                        lambda u: {"ok": True, "html": SY_HTML, "final_url": u,
                                   "snapshot_ts": "20200919124151"})
    assert cli.cmd_precedents_page(_args(URL)) == 0
    conn = db.get_connection()
    # الهوية المسجلة هي الرابط الأصلي لا رابط الأرشيف، وطابع اللقطة محفوظ
    assert conn.execute("SELECT count(*) FROM citations WHERE source_url=?", (URL,)).fetchone()[0] == 3
    assert conn.execute("SELECT snapshot_ts FROM citations LIMIT 1").fetchone()[0] == "20200919124151"


def test_dead_link_and_no_archive_writes_nothing(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(fetcher, "fetch", lambda u: {"ok": False})
    monkeypatch.setattr(wb, "as_pipeline_result", lambda u: {"ok": False, "error": "wayback_no_snapshot"})
    assert cli.cmd_precedents_page(_args(URL)) == 0
    assert db.get_connection().execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
