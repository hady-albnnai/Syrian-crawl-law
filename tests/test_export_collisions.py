# -*- coding: utf-8 -*-
"""اختبارات تكرار أسماء الملفات في الحزمة — العلة التي أوقفت بوابة المالك.

قِيس على قاعدة المالك (2026-09-18): 405 وثيقة مُصدَّرة، والبوابة حمراء بـ
«بصمة غير مطابقة ⇒ سيتخطاها ميزان» + «size_bytes مطابقة للملفات (13 مخالف)».
السبب ليس البصمة ولا المنصّة: `exporter` يبني اسم الملف من
`{year}_{title}_{number}` بلا حارس تكرار، فوثيقتان بنفس الهوية تكتبان نفس
الملف — من يكتب ثانياً **يدفن** الأول، والفهرس يبقى يحمل بصمة وحجماً لملف لم
يعد موجوداً. أسوأ من البوابة الحمراء: ميزان يفصل التكرار على `filePath`، فلو
مرّت الحزمة لَدفنت وثيقة أخرى بصمت عند الاستيراد.

الحل المحروس هنا: لا دفن (لاحقة `_2`)، ولا صفّان لنفس البايتات (دمج)، وفحص
قطعي في البوابة يرفض أي تكرار مسار.
"""
import csv
import hashlib
import sqlite3
from pathlib import Path

import pytest


def _mk_db(tmp_path, monkeypatch, docs):
    """قاعدة مؤقتة بوثائق معطاة كـ (title, number, year, نص المادة)."""
    import config
    import database
    db = tmp_path / "collide.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    from crawler import save_document
    for i, (title, number, year, body) in enumerate(docs, 1):
        doc_id, _ = save_document(
            cur, f"sha256:k{i}", title, f"https://x/{i}", "penal_law", 0.9,
            90.0, f"md5{i}", body, identity_key=f"القانون:{number}:{year}",
            identity_confidence="number_year", law_number=number,
            law_year=year, source_domain_tier=2, quality_score=0.9)
        conn.execute("UPDATE documents SET number=?, year=? WHERE id=?",
                     (number, year, doc_id))
        cur.execute("INSERT INTO articles (doc_id, article_number,"
                    " article_label, text, char_count) VALUES (?,?,?,?,?)",
                    (doc_id, "1", "المادة 1", body[:40], len(body[:40])))
    conn.commit()
    conn.close()
    return db


def _index(out):
    with open(out / "laws_decrees_index.csv", encoding="utf-8-sig",
              newline="") as f:
        return list(csv.DictReader(f))


def _body(text):
    return text * 30


def test_same_identity_different_content_never_buries(tmp_path, monkeypatch):
    """وثيقتان بنفس العنوان/الرقم/السنة ومحتًى مختلف ⇒ ملفّان، والبوابة خضراء."""
    import exporter
    import verify_package
    db = _mk_db(tmp_path, monkeypatch, [
        ("قانون العقوبات", 148, 1949, _body("نص المصدر الأول للوثيقة.")),
        ("قانون العقوبات", 148, 1949, _body("نص مصدر آخر مختلف تماماً للوثيقة.")),
    ])
    out = tmp_path / "pkg"
    rep = exporter.build_package(db_path=db, out_dir=out)
    rows = _index(out)
    assert len(rows) == 2, f"ضياع صَفْر: {len(rows)}"
    paths = [r["local_path"] for r in rows]
    assert len(set(paths)) == 2, f"نفس المسار مرتين ⇒ دفن: {paths}"
    assert rep["renamed"] == 1
    for r in rows:
        f = out / "markdown" / Path(r["local_path"]).name
        assert f.exists()
        assert f.stat().st_size == int(r["size_bytes"])
        assert hashlib.sha256(f.read_bytes()).hexdigest() == r["sha256"]
    assert verify_package.gate_ok(out), verify_package.check_package(out)
    # عينة من العرض: لا «بصمة غير مطابقة» (هذا حرفياً ما رآه المالك)
    assert not any("بصمة غير مطابقة" in m for m, ok
                   in verify_package.check_package(out) if not ok)


def test_near_duplicates_survive_rather_than_being_dropped(tmp_path, monkeypatch):
    """نفس الهوية من مصدرين = ملفّان، لا ملف واحد وحذفٌ «ذكي» للصمت.

    قِيس أن المتن يتضمّن `المصدر: <url>` وأن `documents.source_url` مقيّد
    UNIQUE، فـ«حذف النسخة المطابقة» غير قابل للحدوث أصلاً — ومن يبنِ شقّاً
    له يبيع حماية ميتة. الاختبار يثبّت أن الاثنتين تمرّان وتقيسان.
    """
    import exporter
    import verify_package
    body = _body("نص واحد بلفظ واحد، من مصدرين مختلفين.")
    db = _mk_db(tmp_path, monkeypatch, [
        ("قانون العقوبات", 148, 1949, body),
        ("قانون العقوبات", 148, 1949, body),
    ])
    out = tmp_path / "pkg"
    rep = exporter.build_package(db_path=db, out_dir=out)
    rows = _index(out)
    assert len(rows) == 2, f"حُذفت وثيقة بذكاء زائد: {len(rows)}"
    assert rep["renamed"] == 1
    assert len({r["local_path"] for r in rows}) == 2
    md = sorted((out / "markdown").glob("*.md"))
    assert len(md) == 2 and all(f.stat().st_size for f in md)
    # البصمتان مختلفتان لأن الرابط مختلف — والدليل أن الحذف كان سيُضلّل
    assert len({r["sha256"] for r in rows}) == 2
    assert verify_package.gate_ok(out)


def test_package_article_count_equals_the_database(tmp_path, monkeypatch):
    """القياس من القرص يجب أن يساوي الحقيقة بالقاعدة — لا أقل ولا أكثر.

    قِيس على قاعدة المالك قبل الإصلاح: الحزمة أعلنت 15٬300 مادة وهي تعدّ من
    ملفات مدفون بعضها، والقاعدة تقول 15٬142 ⇒ فرق 158 مادة. هنا نفس العلة
    بأرقام صغيرة: صَفّان يشيران نفس الملف ⇒ العدد ينحرف في أي اتجاه.
    """
    import exporter
    import verify_package
    db = _mk_db(tmp_path, monkeypatch, [
        ("قانون العقوبات", 148, 1949, _body("نص المصدر الأول.")),
        ("قانون العقوبات", 148, 1949, "متن أطول بكثير من المصدر الثاني " * 6),
    ])
    # الثاني بأربع مواد، الأول بمادة واحدة — والتصادم كان يجعل الاثنين يعدّان
    # ملف الفائز فقط
    import database
    conn = database.get_connection()
    last = conn.execute("SELECT id FROM documents ORDER BY id DESC LIMIT 1").fetchone()[0]
    for n in ("2", "3", "4"):
        conn.execute("INSERT INTO articles (doc_id, article_number,"
                     " article_label, text, char_count) VALUES (?,?,?,?,?)",
                     (last, n, f"المادة {n}", "متن", 8))
    conn.commit()
    truth = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE doc_id IN"
        " (SELECT id FROM documents WHERE status='active')").fetchone()[0]
    conn.close()
    out = tmp_path / "pkg"
    rep = exporter.build_package(db_path=db, out_dir=out)
    counts = verify_package.article_counts(out)
    assert counts["articles"] == truth, (
        f"عدد الحزمة {counts['articles']} ≠ عدد القاعدة {truth}")
    assert rep["docs"] == 2 and counts["rows"] == 2
    assert verify_package.gate_ok(out)


def test_gate_flags_duplicate_local_paths(tmp_path, monkeypatch):
    """ولو جاء التكرار من حزمة قديمة/يدوية، البوابة ترفضه لا تمرّره."""
    import exporter
    import verify_package
    db = _mk_db(tmp_path, monkeypatch, [
        ("قانون العقوبات", 148, 1949, _body("نص.")),
        ("قانون العمل", 17, 2010, _body("نص ثانٍ.")),
    ])
    out = tmp_path / "pkg"
    exporter.build_package(db_path=db, out_dir=out)
    idx = out / "laws_decrees_index.csv"
    rows = _index(out)
    rows[1]["local_path"] = rows[0]["local_path"]      # تكرار متعمَّد
    with open(idx, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                           lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    checks = verify_package.check_package(out)
    assert any("لا مسار مكرر" in m and not ok for m, ok in checks), checks
    assert not verify_package.gate_ok(out)


def test_sidecar_json_bytes_are_platform_independent(tmp_path, monkeypatch):
    """‏`write_text` بلا newline يحوّل \n إلى \r\n على ويندوز — فلو قِيس حجم
    أو بصمة على الجانبي لاحقاً لانفصلت المنصتان. البايتات يجب أن تكون LF."""
    import exporter
    db = _mk_db(tmp_path, monkeypatch, [("قانون العقوبات", 148, 1949, _body("نص."))])
    out = tmp_path / "pkg"
    exporter.build_package(db_path=db, out_dir=out)
    js = next((out / "markdown").glob("*.json"))
    assert b"\r" not in js.read_bytes(), "CRLF تسلل إلى الجانبي"


def test_stats_reports_exportable_not_only_total(tmp_path, monkeypatch, caplog):
    """الفارق بين «كم عندي» و«كم يُصدَّر» يجب أن يُطبع، لا أن يُسأل عنه."""
    import cli
    db = _mk_db(tmp_path, monkeypatch, [("قانون العقوبات", 148, 1949, _body("نص."))])
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO documents (doc_id, title, source_url, doc_type,"
                 " status, scraped_at) VALUES ('sha256:rej','مرفوض',"
                 "'https://x/r','law','rejected','2026-09-18T00:00:00')")
    conn.commit(); conn.close()
    import config
    monkeypatch.setattr(config, "DB_PATH", db)
    import io
    import logging
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    root = logging.getLogger("mizan")
    root.addHandler(h)
    try:
        assert cli.cmd_stats(None) == 0
    finally:
        root.removeHandler(h)
    out = buf.getvalue()
    assert "قابلة للتصدير (active)" in out, out
    assert "documents[active] = 1" in out, out
    assert "documents[rejected] = 1" in out, out
