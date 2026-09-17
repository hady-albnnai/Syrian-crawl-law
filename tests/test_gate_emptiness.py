# -*- coding: utf-8 -*-
"""بوابة خضراء على حزمة فاضية = كذب بصمت — هذا الملف يحرس ضدّه.

العلة (قِيس 2026-09-17 قبل الإصلاح): `python -m cli export` على قاعدة بلا
وثائق طبع «بوابة ميزان: ✓ ستُستورد كل الصفوف» وخرج **0**، لأن كل فحوص
`check_package` ما فوق البنية تدور على قائمة صفوف فارغة فتنجح كلها بلا استثناء.
النتيجة أن المستخدِم الجديد — الذي لم يجمع شيئاً بعد — يظن أن حزمته جاهزة
للميزان، ويرفع فهرساً صفره صفوف، وميزان من ناحيته يسقط تحت 8 صفوف
(‏`bootstrap()` في `csv_legal_library_importer.dart`) فلا يحدث شيء إطلاقاً.

الحارس يغطي الأطراف الثلاثة التي يجب أن ترفض: `verify_package`، و`cli`
(خروج غير صفري)، و`mizan_injector` (لا كتابة ولا نسخة أمان بلا مقابل).
"""
import csv
from pathlib import Path

import pytest

REQUIRED = 14


def _mk_empty_db(tmp_path, monkeypatch, name="empty.db"):
    """قاعدة نظيفة على مسار مؤقت — مع إعادة الضبط بعد الاختبار.

    الضبط بلا `monkeypatch` يترك `config.DB_PATH` مشوّهاً لباقي ملفات
    الاختبار في نفس العملية (انجراف ترتيب)، وهذا آخر ما نحتاجه.
    """
    import config
    import database
    db = tmp_path / name
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    return db


def _build(db, tmp_path, sub="pkg"):
    import exporter
    out = tmp_path / sub
    return exporter.build_package(db_path=db, out_dir=out)


class NS:
    """كائن وسائط لـ`cli` (نفس أسلوب الاختبارات التاريخية)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ─────────────────────────────────────────────────── البوابة نفسها
def test_empty_package_is_red_not_vacuously_green(tmp_path, monkeypatch):
    import verify_package
    db = _mk_empty_db(tmp_path, monkeypatch)
    out = tmp_path / "pkg"
    _build(db, tmp_path)
    checks = verify_package.check_package(out)
    failed = [m for m, ok in checks if not ok]
    assert any("صفوف تُصدَّر" in m for m in failed), \
        f"الحزمة الفارغة مرّت خضراء: {checks}"
    assert not verify_package.gate_ok(out)


def test_empty_package_message_states_the_count(tmp_path, monkeypatch):
    """الرسالة تحمل الرقم المقيس (0) — لا نصّاً ثابتاً يصدق على كل حال."""
    import verify_package
    db = _mk_empty_db(tmp_path, monkeypatch, "empty2.db")
    out = tmp_path / "pkg2"
    _build(db, tmp_path, "pkg2")
    msgs = {m: ok for m, ok in verify_package.check_package(out)}
    key = next(m for m in msgs if "صفوف تُصدَّر" in m)
    assert "(0)" in key
    assert msgs[key] is False


def test_one_row_package_is_green(tmp_path, monkeypatch):
    """عكس الحراسة: لا نجعل البوابة حمراء على كل حال — صّف واحد يكفي."""
    import database
    import verify_package
    from crawler import save_document
    db = _mk_empty_db(tmp_path, monkeypatch, "one.db")
    conn = database.get_connection()
    cur = conn.cursor()
    doc_id, _ = save_document(
        cur, "sha256:one", "قانون واحد", "https://x/one", "civil_law", 0.9,
        90.0, "md5one", "نص طويل يكفي " * 20,
        identity_key="القانون:1:2024", identity_confidence="number_year",
        law_number=1, law_year=2024, source_domain_tier=2, quality_score=0.9)
    for n in ("1", "2"):
        cur.execute("INSERT INTO articles (doc_id, article_number,"
                    " article_label, text, char_count) VALUES (?,?,?,?,?)",
                    (doc_id, n, f"المادة {n}", "متن المادة", 11))
    conn.commit(); conn.close()
    out = tmp_path / "pkg3"
    _build(db, tmp_path, "pkg3")
    checks = verify_package.check_package(out)
    failed = [m for m, ok in checks if not ok]
    assert not failed, f"حزمة بصفّ واحد رُفضت: {failed}"
    assert verify_package.gate_ok(out)
    rows = list(csv.DictReader(open(out / "laws_decrees_index.csv",
                                     encoding="utf-8-sig")))
    assert len(rows) == 1


# ─────────────────────────────────────────────────── الطرفية
def test_cli_export_exits_1_on_empty_package(tmp_path, capsys, monkeypatch):
    import cli
    db = _mk_empty_db(tmp_path, monkeypatch, "cli.db")
    rc = cli.cmd_export(NS(db=db, out=tmp_path / "clipkg", prefix=None,
                          min_articles=0, no_manifest=False))
    assert rc == 1, "البوابة الفارغة يجب أن تُخرج رمز فشل لا 0"
    printed = capsys.readouterr().out
    assert "✗ ستُتخطى صفوف" in printed or "✗" in printed
    assert "صفوف تُصدَّر (0)" in printed


def test_cli_verify_exits_1_on_empty_package(tmp_path, capsys, monkeypatch):
    import cli
    db = _mk_empty_db(tmp_path, monkeypatch, "cli2.db")
    _build(db, tmp_path, "clipkg2")
    rc = cli.cmd_verify_package(NS(pkg=tmp_path / "clipkg2"))
    assert rc == 1, "فحص حزمة فارغة يجب أن يفشل، لا أن يصفّق"


# ─────────────────────────────────────────────────── الحقن
def _lib_dir(root):
    """مجلد المكتبة داخل جذر ميزان (‏LIB_SUBPATH مكوّنات، لا نصاً)."""
    from mizan_injector import LIB_SUBPATH
    return Path(root).joinpath(*LIB_SUBPATH)


@pytest.fixture
def mizan_root(tmp_path):  # noqa: PT004 — يبني جذراً صناعياً ويعيده
    """جذر ميزان صناعي بفهرس من صفيْن (حتى لا نكتب في مستودع المالك)."""
    from mizan_injector import INDEX_NAME
    from verify_package import REQUIRED_COLUMNS
    d = _lib_dir(tmp_path / "mizan")
    d.mkdir(parents=True)
    with open(d / INDEX_NAME, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(REQUIRED_COLUMNS),
                           lineterminator="\n")
        w.writeheader()
        for i, (rid, path) in enumerate(
                [("own1", "pdf/own1.pdf"), ("own2", "pdf/own2.pdf")], 1):
            row = {c: "" for c in REQUIRED_COLUMNS}
            row.update({"id": rid, "title": f"صفّهم {i}", "local_path": path,
                        "format": "pdf"})
            w.writerow(row)
    return tmp_path / "mizan"


def _index_bytes(root):
    from mizan_injector import INDEX_NAME
    return (_lib_dir(root) / INDEX_NAME).read_bytes()


def test_injector_refuses_empty_package_and_writes_nothing(tmp_path,
                                                           mizan_root,
                                                           monkeypatch):
    import mizan_injector as inj
    db = _mk_empty_db(tmp_path, monkeypatch, "inj.db")
    out = tmp_path / "injpkg"
    _build(db, tmp_path, "injpkg")
    before = _index_bytes(mizan_root)
    p = inj.plan(out, mizan_root)
    assert p["gate_green"] is False
    assert p["rows_ours"] == 0
    assert any("بلا صفوف" in w for w in p["warnings"]), p["warnings"]
    with pytest.raises(inj.GateError):
        inj.apply(out, mizan_root)
    assert _index_bytes(mizan_root) == before, "الرفض يجب أن يسبق أي كتابة"
    assert not (mizan_root / inj.BACKUP_DIRNAME).exists(), \
        "لا نسخة أمان لفعل لم يُكتب منه شيء"


def test_injector_receipt_is_loud_when_forced(tmp_path, mizan_root,
                                                   monkeypatch):
    """‏`--force` ما زال ممراً — لكنه مسجَّل، والفهرس يبقى بصفوفهم لا بأقل."""
    import mizan_injector as inj
    db = _mk_empty_db(tmp_path, monkeypatch, "force.db")
    out = tmp_path / "forcepkg"
    _build(db, tmp_path, "forcepkg")
    rec = inj.apply(out, mizan_root, allow_red_gate=True)
    assert rec["gate_before"]["forced"] is True, "التجاوز بلا وسم = كذب على السجل"
    assert rec["gate_before"]["green"] is False
    assert rec["rows"]["added"] == 0
    with open(_lib_dir(mizan_root) / inj.INDEX_NAME, encoding="utf-8-sig",
              newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["id"] for r in rows} == {"own1", "own2"}, "صفوفهم لا تُمسّ"
    assert (mizan_root / inj.BACKUP_DIRNAME).exists()
    # الإيصالية تُكتب في الوجهة وتُقرأ من الحزمة — تدقيق بطرفين
    assert (_lib_dir(mizan_root) / inj.RECEIPT_NAME).exists()
    assert (out / inj.RECEIPT_NAME).exists()


def test_exporter_marks_gate_failure_names(tmp_path, monkeypatch):
    """المانيفست/التقرير يجب أن يسمّيا الفحص الراسب، لا «بوابة حمراء» عمياء."""
    db = _mk_empty_db(tmp_path, monkeypatch, "rep.db")
    rep = _build(db, tmp_path, "reppkg")
    assert rep["gate_ok"] is False
    assert any("صفوف تُصدَّر" in m for m in rep["gate_failed"]), rep
