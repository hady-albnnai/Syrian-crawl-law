"""test_exporter_injection.py — إثبات عقد الحقن الحقيقي من الزاحف إلى ميزان.

لا شبكة — يقيس عقد التكامل محلياً:
1) إصلاح البصمة: sha256 في الفهرس = بايتات الـ .md المُسلَّم (لا لقطة المصدر).
2) بوابة سلامة ميزان: كل صف يمرّ (صفر skippedIntegrity).
3) الدمج الآمن: استبدال القوانين اليدوية المغطّاة + إبقاء غير المغطّاة.
"""
import csv
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from exporter import COLUMNS, build_package

HERE = Path(__file__).resolve().parent
CRAWLER_ROOT = HERE.parent


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _mizan_integrity_check(out_dir: Path):
    """يقلّد تماماً منطق planCsvImport في ميزان: ملف موجود + sha يطابق."""
    csv_path = out_dir / "laws_decrees_index.csv"
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    missing = bad = 0
    for r in rows:
        fp = r["local_path"].strip()
        f = out_dir / fp
        if not f.exists():
            missing += 1
            continue
        actual = _sha256_bytes(f.read_bytes())
        if actual != r["sha256"].lower():
            actual = _sha256_bytes(
                b"".join(b for b in f.read_bytes()
                         if not (b == 0x0D and False)))  # لا تطبيع هنا
            if actual != r["sha256"].lower():
                bad += 1
    return {"total": len(rows), "missing": missing, "bad_sha": bad}


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE documents (
        id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE, title TEXT, doc_type TEXT,
        number INTEGER, year INTEGER, branch TEXT, source_url TEXT,
        source_credibility REAL DEFAULT 0.6, status TEXT DEFAULT 'active',
        content_sha256 TEXT, snapshot_sha256 TEXT)""")
    conn.execute("""CREATE TABLE articles (
        id INTEGER PRIMARY KEY, doc_id INTEGER, article_number TEXT,
        article_label TEXT, paragraphs_json TEXT, text TEXT,
        hierarchy_path TEXT, amended_by TEXT)""")
    # وثيقة (أ) لها لقطة HTML موجودة عمداً — لاختبار أن البصمة تبقى للـ .md
    conn.execute(
        "INSERT INTO documents VALUES (1,'doc_a','القانون المدني السوري',"
        "'law',84,1949,'civil_law','https://x/civil',0.9,'active',"
        "'c_sha_a','sha256:snap_a')")
    conn.execute(
        "INSERT INTO articles (doc_id,article_number,article_label,text,"
        "hierarchy_path) VALUES (1,'1','1','نص المادة الأولى من المدني',"
        "'كتاب1/باب1')")
    # وثيقة (ب) بلا لقطة
    conn.execute(
        "INSERT INTO documents VALUES (2,'doc_b','قانون العمل','law',17,2010,"
        "'labor_law','https://x/labor',0.8,'active','c_sha_b',NULL)")
    conn.execute(
        "INSERT INTO articles (doc_id,article_number,article_label,text) "
        "VALUES (2,'5','5','نص مادة العمل الخامسة')")
    conn.commit(); conn.close()


def test_export_sha_is_of_shipped_md_not_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(CRAWLER_ROOT)
    snap_dir = CRAWLER_ROOT / "data" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_file = snap_dir / "snap_a.html"
    snap_file.write_bytes(
        "<html>لقطة المصدر الخام — يجب ألا تُبصَّم</html>".encode("utf-8"))

    db = tmp_path / "harvester.db"
    _make_db(db)
    out = tmp_path / "pkg"
    rep = build_package(db_path=str(db), out_dir=str(out), prefix="",
                        reconcile=False)

    assert rep["docs"] == 2, rep
    check = _mizan_integrity_check(out)
    assert check["missing"] == 0, check
    assert check["bad_sha"] == 0, (
        "بوابة سلامة ميزان ستُسقط صفوفاً — البصمة لا تطابق الملف المُسلَّم")
    # إثبات صريح: بصمة الصف ≠ بصمة اللقطة (أي أننا لم نبصم اللقطة)
    rows = list(csv.DictReader(
        (out / "laws_decrees_index.csv").read_text(encoding="utf-8-sig").splitlines()))
    a = next(r for r in rows if r["number"] == "84")
    md_bytes = (out / a["local_path"]).read_bytes()
    assert a["sha256"] == _sha256_bytes(md_bytes)
    assert a["sha256"] != _sha256_bytes(snap_file.read_bytes())
    # تنظيف
    import shutil
    shutil.rmtree(snap_dir, ignore_errors=True)


def test_reconcile_replaces_covered_keeps_uncovered(tmp_path, monkeypatch):
    monkeypatch.chdir(CRAWLER_ROOT)
    db = tmp_path / "harvester.db"
    _make_db(db)
    out = tmp_path / "pkg"
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    # فهرس قائم يحاكي مكتبة ميزان اليدوية:
    #  - مدني 84/1949 → مغطّى بالزاحف (يُستبدل)
    #  - قانون يتيم 999/2000 بملف موجود → غير مغطّى (يُبقى)
    #  - قانون مفقود 888/1999 بلا ملف → غير مغطّى لكنه بلا فائدة (يُسقط)
    orphan = out / "pdf" / "orphan.pdf"
    orphan.write_bytes("ملف يتيم موجود".encode("utf-8"))
    existing = [
        COLUMNS,
        ["old_civil", "القانون المدني السوري", "قانون", "84", "1949", "",
         "مدني", "https://x/old", "pdf", "1", "downloaded",
         "pdf/old_civil.pdf", "10", _sha256_bytes(b"x")],
        ["orphan_law", "قانون غير موجود في الزاحف", "قانون", "999", "2000", "",
         "أخرى", "https://x/orphan", "pdf", "2", "downloaded",
         "pdf/orphan.pdf", str(orphan.stat().st_size),
         _sha256_bytes(orphan.read_bytes())],
        ["missing_law", "قانون بلا ملف", "قانون", "888", "1999", "",
         "أخرى", "https://x/missing", "pdf", "2", "downloaded",
         "pdf/missing.pdf", "5", _sha256_bytes(b"y")],
    ]
    with open(out / "laws_decrees_index.csv", "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerows(existing)

    rep = build_package(db_path=str(db), out_dir=str(out), prefix="",
                        reconcile=True)
    assert rep["replaced"] == 2, rep  # المدني المغطّى + المفقود
    assert rep["kept"] == 1, rep      # اليتيم المغطّى-غير-موجود
    rows = {r["id"]: r for r in csv.DictReader(
        (out / "laws_decrees_index.csv").read_text(encoding="utf-8-sig").splitlines())}
    assert "old_civil" not in rows, "يجب استبدال المدني اليدوي المغطّى"
    assert "orphan_law" in rows, "يجب إبقاء القانون غير المغطّى"
    assert "missing_law" not in rows, "يجب إسقاط القانون بلا ملف"
    assert any(r["number"] == "84" for r in rows.values()), "نظير الزاحف للمدني يجب أن يوجد"
    # بوابة السلامة تمرّ لكل الصفوف المتبقية
    check = _mizan_integrity_check(out)
    assert check["missing"] == 0 and check["bad_sha"] == 0, check
