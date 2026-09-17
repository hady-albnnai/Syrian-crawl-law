# -*- coding: utf-8 -*-
"""اختبارات عقد الحزمة v2 (ف٢ — عقد المواد + المانيفست + بوابة واحدة).

تغطي ما لا يغطيه test_migration_export (الذي يفحص 14 عموداً وحدها):
 1) التوسيع الغني لكل JSON جانبي: الحالة القانونية، الهوية، طبقة الرسمية،
    سلسلة التعديل (اتجاهيها)، بصمة نص كل مادة.
 2) mizan_package_manifest.json: أرقام مأخوذة من القرص وبصمات الملفات.
 3) verify_package = نسخة ميزان الحرفية من الفحص: يكشف التلاعب بملف md،
    ويكشف بصمة اللقطة القديمة (الحارس الذي يمنع رجوع العطل).
 4) أن الواجهة (core_data.validate_package) صارت **نفس** البوابة، لا نسخة أخفّ.
"""
import csv
import hashlib
import json
import sqlite3

import pytest


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """قاعدة إنتاجية كاملة بوثيقتين + سلسلة تعديل حقيقية + حزمة مولَّدة."""
    import config
    import database
    db = tmp_path / "c.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    from crawler import save_document
    # (1) قانون مستهدف بالإلغاء — doc A يعدّله و doc B يلغيه
    a_id, _ = save_document(cur, "sha256:aa", "قانون العقوبات", "https://x/a",
                            "penal_law", 0.9, 91.0, "md5a", "نص العقوبات",
                            identity_key="القانون:148:1949",
                            identity_confidence="number_year",
                            law_number=148, law_year=1949,
                            source_domain_tier=2, quality_score=0.93)
    b_id, _ = save_document(cur, "sha256:bb", "قانون التعديل 2020",
                            "https://x/b", "penal_law", 0.8, 88.0, "md5b",
                            "نص المعدِّل", identity_key="القانون:7:2020",
                            identity_confidence="number_year", law_number=7,
                            law_year=2020, source_domain_tier=1,
                            quality_score=0.9)
    conn.commit()
    for doc, num, txt in ((a_id, "1", "تُنَفَّذ أحكام هذا القانون."),
                          (a_id, "2", "تُلغى أي نص مخالف."),
                          (b_id, "1", "تُعدَّل المادة 1 من القانون 148.")):
        cur.execute("INSERT INTO articles (doc_id, article_number,"
                    " article_label, text, char_count)"
                    " VALUES (?,?,?,?,?)",
                    (doc, num, f"المادة {num}", txt, len(txt)))
    # سلسلة التعديل: b يعدّل a ويبطل قانوناً آخر برقم
    cur.execute("INSERT INTO law_amendments (amending_doc_id,"
                " target_identity, action, context, created_at)"
                " VALUES (?,?,?,?,?)",
                (b_id, "القانون:148:1949", "amend",
                 "تُعدَّل المادة 1 من القانون 148", "2026-09-17T00:00:00"))
    cur.execute("INSERT INTO law_amendments (amending_doc_id,"
                " target_identity, action, context, created_at)"
                " VALUES (?,?,?,?,?)",
                (b_id, "القانون:99:1990", "repeal",
                 "يُلغى القانون 99 لعام 1990", "2026-09-17T00:00:00"))
    conn.commit()
    # الحالة القانونية محسوبة (كما تفعل الدورة) — نكتبها مباشرة للاختبار
    cur.execute("UPDATE documents SET legal_status='معدَّل' WHERE id=?", (a_id,))
    cur.execute("UPDATE documents SET review_status='human_verified' WHERE id=?",
                (a_id,))
    conn.commit()
    conn.close()
    import exporter
    out = tmp_path / "pkg"
    rep = exporter.build_package(db, out_dir=out)
    return db, out, rep


def _rows(out):
    return list(csv.DictReader(open(out / "laws_decrees_index.csv",
                                    encoding="utf-8-sig")))


class TestRichSidecar:
    def test_legal_status_and_identity_in_json(self, corpus):
        db, out, rep = corpus
        js = json.loads((out / "markdown" / next(
            p for p in (out / "markdown").glob("*.json")
            if "148" in p.name or "العقوبات" in p.name)).read_text(encoding="utf-8"))
        assert js["schema_version"] == "2"
        assert js["identity_key"] == "القانون:148:1949"
        assert js["legal_status"] == "معدَّل"
        assert js["review_status"] == "human_verified"
        assert js["domain_tier"] == 2
        assert js["document_status"] == "active"

    def test_amendment_chain_both_directions(self, corpus):
        db, out, rep = corpus
        by_name = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                   for p in (out / "markdown").glob("*.json")}
        target = next(v for v in by_name.values()
                      if v.get("identity_key") == "القانون:148:1949")
        amender = next(v for v in by_name.values()
                       if v.get("identity_key") == "القانون:7:2020")
        # المستهدَف: من عدّله؟
        assert [a["amender"] for a in target["amended_by_docs"]] == ["قانون التعديل 2020"]
        assert target["amended_by_docs"][0]["action"] == "amend"
        # المعدِّل: من عدّل/أبطل؟ (بما فيها إحالة لصك غير موجود بالحزمة)
        assert {a["target_identity"] for a in amender["amends"]} == {
            "القانون:148:1949", "القانون:99:1990"}
        assert {a["action"] for a in amender["amends"]} == {"amend", "repeal"}

    def test_every_article_has_text_fingerprint(self, corpus):
        db, out, rep = corpus
        for p in (out / "markdown").glob("*.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            for a in data["articles"]:
                assert len(a["text_sha256"]) == 64
                assert a["text_sha256"] == hashlib.sha256(
                    (a["text"] or "").encode("utf-8")).hexdigest()


class TestManifest:
    def test_manifest_counts_and_hashes_are_from_disk(self, corpus):
        db, out, rep = corpus
        m = json.loads((out / "mizan_package_manifest.json").read_text(encoding="utf-8"))
        rows = _rows(out)
        assert m["index"]["rows"] == len(rows) == 2
        assert m["corpus"]["documents"] == 2
        assert m["corpus"]["articles"] == 3          # 2 للعقوبات + 1 للتعديل
        assert m["index_bom"] is True and m["index_line_endings"] == "lf"
        for f in m["files"]:
            data = (out / f["markdown"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == f["markdown_sha256"]
            assert f["size_bytes"] == len(data)
            assert f["json_sha256"] == hashlib.sha256(
                (out / f["json"]).read_bytes()).hexdigest()

    def test_manifest_index_sha_matches_file(self, corpus):
        db, out, rep = corpus
        m = json.loads((out / "mizan_package_manifest.json").read_text(encoding="utf-8"))
        assert m["index"]["sha256"] == hashlib.sha256(
            (out / "laws_decrees_index.csv").read_bytes()).hexdigest()


class TestGateIsMizanGate:
    def test_green_on_fresh_package(self, corpus):
        import verify_package
        db, out, rep = corpus
        checks = verify_package.check_package(out)
        failed = [m for m, ok in checks if not ok]
        assert not failed, failed
        assert verify_package.gate_ok(out)

    def test_detects_tampered_markdown(self, corpus):
        """ميزان يفتح ملف md نفسه — فالعبث به يجب أن يُرى."""
        import verify_package
        db, out, rep = corpus
        victim = next((out / "markdown").glob("*.md"))
        victim.write_bytes(victim.read_bytes() + "\n# تُهمة\n".encode("utf-8"))
        checks = verify_package.check_package(out)
        assert any("سيتخطاها ميزان" in m for m, ok in checks if not ok), checks
        assert not verify_package.gate_ok(out)

    def test_detects_legacy_snapshot_hash(self, corpus):
        """حارس انحدار: لو رجعت البصمة تُحسب على اللقطة الخام يجب أن يسقط."""
        import verify_package
        db, out, rep = corpus
        rows = _rows(out)
        # بصمة «لقطة وهمية» بدل بصمة الملف المُصدَّر (الدلالة القديمة)
        new = []
        for r in rows:
            r = dict(r)
            r["sha256"] = hashlib.sha256(b"<html>snapshot</html>").hexdigest()
            new.append(r)
        with open(out / "laws_decrees_index.csv", "w", encoding="utf-8-sig",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new[0].keys()),
                               lineterminator="\n")
            w.writeheader(); w.writerows(new)
        checks = verify_package.check_package(out)
        bad = [m for m, ok in checks if not ok]
        assert any("سيتخطاها ميزان" in m for m in bad), checks
        assert not verify_package.gate_ok(out)

    def test_detects_crlf_index(self, corpus):
        import verify_package
        db, out, rep = corpus
        raw = (out / "laws_decrees_index.csv").read_bytes()
        (out / "laws_decrees_index.csv").write_bytes(raw.replace(b"\n", b"\r\n"))
        checks = verify_package.check_package(out)
        assert any("LF" in m and not ok for m, ok in checks), checks

    def test_detects_missing_manifest(self, corpus):
        import verify_package
        db, out, rep = corpus
        (out / "mizan_package_manifest.json").unlink()
        checks = verify_package.check_package(out)
        assert any("مانيفست" in m and not ok for m, ok in checks), checks


class TestUiUsesTheSameGate:
    def test_core_data_delegates_to_verify_package(self, corpus, monkeypatch):
        from app import core_data
        db, out, rep = corpus
        monkeypatch.setattr(core_data, "PACKAGE_DIR", out)
        gui = dict(core_data.validate_package())
        gate = dict(__import__("verify_package").check_package(out))
        assert gui.keys() == gate.keys()          # لا نسخة أخفّ بعد اليوم
        assert all(gui.values())
        # العبث بالملف يجب أن يظهر في الواجهة كما يظهر في البوابة
        victim = next((out / "markdown").glob("*.md"))
        victim.write_bytes(b"tampered")
        assert not all(dict(core_data.validate_package()).values())

    def test_package_counts_reports_real_numbers(self, corpus, monkeypatch):
        from app import core_data
        db, out, rep = corpus
        monkeypatch.setattr(core_data, "PACKAGE_DIR", out)
        c = core_data.package_counts()
        assert c["rows"] == 2 and c["articles"] == 3
        assert c["manifest"] is True and c["schema_version"] == "2"

    def test_corpus_profile_reports_identity_and_status(self, corpus):
        from app import core_data
        prof = core_data.identity_and_status_stats()
        assert prof["documents"] == 2
        assert prof["with_identity"] == 2
        assert prof["legal_status"].get("معدَّل") == 1
        assert prof["review_status"].get("human_verified") == 1
        assert prof["domain_tier"] == {"1": 1, "2": 1}

    def test_run_history_and_failure_breakdown_are_honest(self, tmp_path,
                                                            monkeypatch):
        import config
        import database
        db = tmp_path / "h.db"
        monkeypatch.setattr(config, "DB_PATH", db)
        monkeypatch.setattr(database, "DB_PATH", db)
        database.create_tables()
        from app import core_data
        assert core_data.run_history() == []          # بلا صفوف ⇒ فارغة لا وهمية
        assert core_data.failure_breakdown() == []
        assert core_data.rejection_stats() == {"total": 0, "by_category": []}
        conn = database.get_connection()
        conn.execute("INSERT INTO crawl_runs (started_at, mode, max_pages,"
                     " pages, docs, articles, failures) VALUES"
                     " ('2026-09-17T00:00:00','live',10,7,3,40,2)")
        conn.execute("INSERT INTO crawl_tasks (url, status, last_error,"
                     " created_at) VALUES ('https://x/1','failed',"
                     "'blocked_by_robots','2026-09-17T00:00:01')")
        conn.execute("INSERT INTO crawl_tasks (url, status, last_error,"
                     " created_at) VALUES ('https://x/2','failed',"
                     "'blocked_by_robots','2026-09-17T00:00:02')")
        conn.commit(); conn.close()
        hist = core_data.run_history()
        assert hist[0]["docs"] == 3 and hist[0]["articles"] == 40
        fb = core_data.failure_breakdown()
        assert fb[0]["reason"] == "blocked_by_robots" and fb[0]["n"] == 2


class TestCli:
    def test_export_reports_gate_and_exit_zero(self, corpus, capsys):
        db, out, rep = corpus
        import cli
        ns = type("A", (), {"out": str(out), "db": str(db),
                            "prefix": "content/legal_library/laws_decrees/",
                            "min_articles": 0, "no_manifest": False})()
        rc = cli.cmd_export(ns)
        printed = capsys.readouterr().out
        assert rc == 0 and "بوابة ميزان: ✓" in printed, printed
        assert "مانيفست" in printed and "مواد داخل الحزمة" in printed

    def test_cli_export_accepts_explicit_db(self, corpus, tmp_path):
        """الفجوة التي كشفها الاختبار: cli export كان يقرأ DB_PATH الافتراضي
        وحده — فلا يمكن توليد حزمة من قاعدة أرشيف/نسخة احتياطية."""
        import csv as _csv
        db, out, rep = corpus
        import cli
        dst = tmp_path / "cli_pkg"
        rc = cli.cmd_export(type("A", (), {"out": str(dst), "db": str(db),
                                           "prefix": "content/legal_library/laws_decrees/",
                                           "min_articles": 0,
                                           "no_manifest": False})())
        assert rc == 0
        rows = list(_csv.DictReader(open(dst / "laws_decrees_index.csv",
                                         encoding="utf-8-sig")))
        assert len(rows) == 2 and (dst / "mizan_package_manifest.json").exists()

    def test_export_with_no_manifest_skips_enrichment(self, tmp_path, monkeypatch):
        import config, database, exporter
        db = tmp_path / "n.db"
        monkeypatch.setattr(config, "DB_PATH", db)
        monkeypatch.setattr(database, "DB_PATH", db)
        database.create_tables()
        conn = database.get_connection()
        from crawler import save_document
        save_document(conn.cursor(), "sha256:nn", "بلا مانيفست", "https://x/n",
                      "civil_law", 0.7, 90.0, "md5", "نص")
        conn.commit(); conn.close()
        rep = exporter.build_package(db, out_dir=tmp_path / "p2",
                                     with_manifest=False)
        assert "manifest" not in rep
        assert not (tmp_path / "p2" / "mizan_package_manifest.json").exists()

    def test_verify_command_exit_codes(self, corpus):
        db, out, rep = corpus
        import cli
        ok = cli.cmd_verify_package(type("A", (), {"pkg": str(out)})())
        assert ok == 0
        victim = next((out / "markdown").glob("*.md"))
        victim.write_bytes(b"tampered again")
        bad = cli.cmd_verify_package(type("A", (), {"pkg": str(out)})())
        assert bad == 1
