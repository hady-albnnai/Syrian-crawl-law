# -*- coding: utf-8 -*-
"""اختبارات حقن الحزمة في ميزان (دفعة 4 — «الحقن المباشر» من جهة الحاصدة).

تُثبِت ما لا يقدر فحصُ الحزمة وحده أن يُثبته: أن الكتابة في وجهة حقيقية
**لا تُلغي** ما عند ميزان، وأننا لا ندّعي نجاحاً لم يحدث:

 1) الدمج يبقي صفوفهم (قياسهم: 29 صفاً عندهم، منها 12 `pdf/…` لا يولّدها
    الزاحف — النسخ الأعمى كان يُيتّمها).
 2) ملفاتنا تصل بايت-ببايت وتُقاس في الوجهة (بلا قياس destination = ادّعاء).
 3) البوابة الحمراء ترفض الحقن، و`--force` يسجّل التجاوز في الإيصالية.
 4) فخّ `filePath` (csv_legal_library_importer.dart:114): وثيقة تغيّرت
    بنفس المسار ⇒ ميزان يتخطاها؛ نكشفها ونكتب خطة استبدال ولا نخفيها.
 5) الحقن مرة ثانية لا يكرّر شيئاً (idempotent).
 6) المعاينة (`--preview`) لا تكتب ولا بايت واحد.
"""
import csv
import hashlib
import json
import sqlite3

import pytest

INDEX_COLS = ["id", "title", "type", "number", "year", "date", "category",
              "url", "format", "priority", "status", "local_path",
              "size_bytes", "sha256"]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """حزمة حقيقية من قاعدة إنتاجية بوثيقتين وأربع مواد."""
    import config
    import database
    db = tmp_path / "inj.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    from crawler import save_document
    a_id, _ = save_document(cur, "sha:a", "قانون العقوبات", "https://x/a",
                            "penal_law", 0.9, 92.0, "h1", "نص العقوبات",
                            identity_key="القانون:148:1949",
                            source_domain_tier=2, quality_score=0.9)
    b_id, _ = save_document(cur, "sha:b", "قانون العمل", "https://x/b",
                            "civil_law", 0.8, 87.0, "h2", "نص العمل",
                            identity_key="القانون:17:2010",
                            source_domain_tier=2, quality_score=0.8)
    for doc, num, txt in ((a_id, "1", "تُنفَّذ الأحكام."), (a_id, "2", "تُلغى المخالفات."),
                          (b_id, "1", "يسري على الجميع.")):
        cur.execute("INSERT INTO articles (doc_id, article_number,"
                    " article_label, text, char_count) VALUES (?,?,?,?,?)",
                    (doc, num, f"المادة {num}", txt, len(txt)))
    conn.commit()
    conn.close()
    import exporter
    out = tmp_path / "pkg"
    exporter.build_package(db_path=db, out_dir=out)
    return out


def _mizan_root(tmp_path, extra_rows=(), overwrite_rows=None):
    """جذر ميزان زائف: content/legal_library/laws_decrees مع فهرسهم.

    `extra_rows` = صفوف لا يولّدها الزاحف (نقيس أنها تبقى). `overwrite_rows` =
    قائمة (id, local_path, نصقديم) تحاكي وثيقة لدينا مسجّلة عندهم بنسخة قديمة.
    """
    root = tmp_path / "mizan"
    lib = root / "content" / "legal_library" / "laws_decrees"
    (lib / "pdf").mkdir(parents=True, exist_ok=True)
    (lib / "markdown").mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (rid, rel, body) in enumerate(extra_rows, start=1):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
        rows.append(dict(zip(INDEX_COLS, [
            rid, f"صك قديم {i}", "قانون", str(i), 1990, "", "مدني",
            "https://old", "pdf", "1", "downloaded", rel, str(len(body)),
            _sha(body)])))
    for rid, rel, old_body in (overwrite_rows or []):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(old_body)
        rows.append(dict(zip(INDEX_COLS, [
            rid, "نسخة قديمة", "قانون", "148", 1949, "", "جزائي",
            "https://old2", "html", "1", "downloaded", rel, str(len(old_body)),
            _sha(old_body)])))
    if rows:
        with open(lib / "laws_decrees_index.csv", "w", encoding="utf-8-sig",
                  newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=INDEX_COLS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    return root


def _read_index(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestPlan:
    def test_plan_is_pure_no_bytes_written(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path, extra_rows=[
            ("old_pdf_1", "content/legal_library/laws_decrees/pdf/old.pdf",
             b"PDF-BYTES")])
        before = {p: _sha(p.read_bytes())
                  for p in root.rglob("*") if p.is_file()}
        p = inj.plan(pkg, root)
        assert p["rows_ours"] == 2 and p["gate_green"] is True
        assert p["kept_foreign"] == ["old_pdf_1"]
        after = {q: _sha(q.read_bytes()) for q in root.rglob("*") if q.is_file()}
        assert before == after, "المعاينة كتبت شيئاً"
        assert not (root / inj.BACKUP_DIRNAME).exists()

    def test_missing_package_index_raises(self, tmp_path):
        import mizan_injector as inj
        with pytest.raises(FileNotFoundError) as e:
            inj.plan(tmp_path / "nowhere", tmp_path)
        # مسار مكتوب غلط ≠ حزمة غير مولّدة: التشخيص لازم يفرّق (قيس على ويندوز)
        assert "غير موجود" in str(e.value)

    def test_existing_folder_without_index_says_so(self, tmp_path):
        import mizan_injector as inj
        empty = tmp_path / "pkg_typo"
        empty.mkdir()
        with pytest.raises(FileNotFoundError) as e:
            inj.plan(empty, tmp_path)
        assert "المجلد موجود لكنه بلا" in str(e.value)

    def test_missing_mizan_root_raises(self, pkg, tmp_path):
        import mizan_injector as inj
        with pytest.raises(FileNotFoundError):
            inj.plan(pkg, tmp_path / "not-a-mizan-checkout")


class TestMergeInjection:
    def test_their_rows_survive_and_ours_are_added(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path, extra_rows=[
            ("old_pdf_1", "content/legal_library/laws_decrees/pdf/old.pdf",
             b"PDF-BYTES"),
            ("old_pdf_2", "content/legal_library/laws_decrees/pdf/old2.pdf",
             b"PDF2")])
        rec = inj.apply(pkg, root)
        rows = _read_index(root / "content" / "legal_library" /
                           "laws_decrees" / "laws_decrees_index.csv")
        ids = {r["id"] for r in rows}
        assert {"old_pdf_1", "old_pdf_2"} <= ids, "الدمج أكل صفوفهم"
        assert set(rec["rows"].keys()) and rec["rows"]["added"] == 2
        assert rec["rows"]["index_rows_after"] == len(rows) == 4
        assert rec["mode"] == "merge"

    def test_files_land_byte_identical_and_verified(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path)
        rec = inj.apply(pkg, root)
        assert rec["verify_our_rows"]["ok"] is True
        assert rec["verify_our_rows"]["checked"] == 2
        for src_md in (pkg / "markdown").glob("*.md"):
            dst = (root / "content" / "legal_library" / "laws_decrees" /
                   "markdown" / src_md.name)
            assert dst.read_bytes() == src_md.read_bytes()
        # JSON الجانبي لازم يوصل معه — دونه تفقد ميزان عقد المواد
        assert list((root / "content" / "legal_library" / "laws_decrees" /
                     "markdown").glob("*.json"))

    def test_receipt_written_at_both_ends(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path)
        rec = inj.apply(pkg, root)
        a = json.loads((root / "content" / "legal_library" / "laws_decrees" /
                        inj.RECEIPT_NAME).read_text(encoding="utf-8"))
        b = json.loads((pkg / inj.RECEIPT_NAME).read_text(encoding="utf-8"))
        assert a == rec and b == rec  # نفس القياس في المكانين
        assert a["index_sha256"] == _sha(
            (root / "content" / "legal_library" / "laws_decrees" /
             "laws_decrees_index.csv").read_bytes())
        assert inj.read_receipt(root)["injected_at"] == a["injected_at"]

    def test_read_receipt_is_none_before_any_injection(self, tmp_path):
        import mizan_injector as inj
        assert inj.read_receipt(_mizan_root(tmp_path)) is None

    def test_replace_index_drops_their_rows_and_says_so(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path, extra_rows=[
            ("old_pdf_1", "content/legal_library/laws_decrees/pdf/old.pdf",
             b"PDF-BYTES")])
        rec = inj.apply(pkg, root, replace_index=True)
        ids = {r["id"] for r in _read_index(
            root / "content" / "legal_library" / "laws_decrees" /
            "laws_decrees_index.csv")}
        assert "old_pdf_1" not in ids and len(ids) == 2
        assert rec["mode"] == "replace-index"

    def test_second_injection_adds_nothing(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path)
        inj.apply(pkg, root)
        p2 = inj.plan(pkg, root)
        assert p2["added"] == [] and p2["index_rows_after"] == 2
        assert len(p2["identical"]) == 2 and p2["updated_same_path"] == []

    def test_merged_index_still_passes_our_contract(self, pkg, tmp_path):
        """الفهرس المدموج يبقى 14 عموداً بترتيبها و BOM و LF — لا يُكسر عقدنا."""
        import mizan_injector as inj
        import verify_package
        root = _mizan_root(tmp_path, extra_rows=[
            ("old_pdf_1", "content/legal_library/laws_decrees/pdf/old.pdf",
             b"PDF-BYTES")])
        inj.apply(pkg, root)
        lib = root / "content" / "legal_library" / "laws_decrees"
        raw = (lib / "laws_decrees_index.csv").read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
        header = raw.decode("utf-8-sig").splitlines()[0].split(",")
        assert header == verify_package.REQUIRED_COLUMNS


class TestUpdateTrap:
    """فخّ filePath: الوثيقة المعدَّلة تتخطاها ميزان — نكشفها، لا نخفيها."""

    def _old_row(self, pkg):
        rows = _read_index(pkg / "laws_decrees_index.csv")
        r = rows[0]
        return r["id"], r["local_path"]

    def test_changed_same_path_is_reported_not_hidden(self, pkg, tmp_path):
        import mizan_injector as inj
        rid, rel = self._old_row(pkg)
        root = _mizan_root(tmp_path, overwrite_rows=[(rid, rel, "نسخة قديمة".encode("utf-8"))])
        p = inj.plan(pkg, root)
        assert p["updated_same_path"] == [rid]
        assert any("filePath" in w for w in p["warnings"])

    def test_update_plan_written_and_old_file_backed_up(self, pkg, tmp_path):
        import mizan_injector as inj
        rid, rel = self._old_row(pkg)
        root = _mizan_root(tmp_path, overwrite_rows=[(rid, rel, "نسخة قديمة".encode("utf-8"))])
        rec = inj.apply(pkg, root)
        lib = root / "content" / "legal_library" / "laws_decrees"
        up = json.loads((lib / inj.UPDATE_PLAN_NAME).read_text(encoding="utf-8"))
        assert up["rows"][0]["id"] == rid
        assert up["rows"][0]["action"] == "replace"
        assert up["rows"][0]["sha256_new"] == _read_index(
            pkg / "laws_decrees_index.csv")[0]["sha256"]
        # النسخة القديمة محفوظة للرجوع، والنص الجديد وصل فعلاً
        bak = root / inj.BACKUP_DIRNAME
        olds = [f for f in bak.rglob("*.md")]
        assert olds and olds[0].read_bytes() == "نسخة قديمة".encode("utf-8")
        assert (root / rel).read_bytes() != "نسخة قديمة".encode("utf-8")
        assert rec["rows"]["updated_same_path"] == 1
        assert rec["files_written"] >= 4  # md+json للوثيقتين

    def test_identical_reinjection_writes_no_update_plan(self, pkg, tmp_path):
        import mizan_injector as inj
        root = _mizan_root(tmp_path)
        inj.apply(pkg, root)
        inj.apply(pkg, root)
        assert not (root / "content" / "legal_library" / "laws_decrees" /
                    inj.UPDATE_PLAN_NAME).exists()


class TestGateRefusal:
    def test_red_gate_refuses_then_force_is_recorded(self, pkg, tmp_path):
        import mizan_injector as inj
        victim = sorted((pkg / "markdown").glob("*.md"))[0]
        victim.write_bytes(victim.read_bytes() + b"\n tampered \n")  # تلاعب بالمتن
        root = _mizan_root(tmp_path)
        p = inj.plan(pkg, root)
        assert p["gate_green"] is False and p["gate_failed"]
        with pytest.raises(inj.GateError):
            inj.apply(pkg, root)
        rec = inj.apply(pkg, root, allow_red_gate=True, prefetch=p)
        assert rec["gate_before"]["forced"] is True
        assert rec["gate_before"]["green"] is False

    def test_verify_destination_is_not_vacuous(self, pkg, tmp_path):
        """لو حذفنا ملفاً من الوجهة يكشف القياس ذلك — لا يمرّ بصمت."""
        import mizan_injector as inj
        root = _mizan_root(tmp_path)
        inj.apply(pkg, root)
        lib = root / "content" / "legal_library" / "laws_decrees"
        victim = sorted((lib / "markdown").glob("*.md"))[0]
        victim.unlink()
        v = inj.verify_destination(root, lib,
                                  [r["id"] for r in _read_index(
                                      pkg / "laws_decrees_index.csv")])
        assert v["ok"] is False and v["missing"]


class TestCliSurface:
    def _ns(self, **kw):
        import argparse
        return argparse.Namespace(**kw)

    def test_cli_requires_a_root(self, monkeypatch, capsys):
        import cli
        monkeypatch.setattr("config.MIZAN_ROOT", "")
        assert cli.cmd_inject(self._ns(pkg="x", mizan_root=None, preview=True,
                                       replace_index=False, force=False)) == 2

    def test_cli_preview_writes_nothing(self, pkg, tmp_path, monkeypatch,
                                        capsys):
        import cli
        root = _mizan_root(tmp_path, extra_rows=[
            ("old_pdf_1", "content/legal_library/laws_decrees/pdf/old.pdf",
             b"PDF-BYTES")])
        files = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
        rc = cli.cmd_inject(self._ns(pkg=str(pkg), mizan_root=str(root),
                                     preview=True, replace_index=False,
                                     force=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "سيُضاف: 2 صفاً" in out and "محفوظ من فهرسهم: 1" in out
        assert all(p.stat().st_mtime_ns == files[p] for p in files)
        assert not (root / "content" / "legal_library" / "laws_decrees" /
                    "mizan_injection_receipt.json").exists()

    def test_cli_inject_reports_update_trap_exit_zero(self, pkg, tmp_path,
                                                       capsys):
        import cli
        rows = _read_index(pkg / "laws_decrees_index.csv")
        root = _mizan_root(tmp_path, overwrite_rows=[
            (rows[0]["id"], rows[0]["local_path"], "قديم".encode("utf-8"))])
        rc = cli.cmd_inject(self._ns(pkg=str(pkg), mizan_root=str(root),
                                     preview=False, replace_index=False,
                                     force=False))
        assert rc == 0
        assert (root / "content" / "legal_library" / "laws_decrees" /
                "mizan_update_plan.json").exists()
