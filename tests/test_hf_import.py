# -*- coding: utf-8 -*-
"""اختبارات hf_syria_laws — التبني المرحلي لمجموعة HF (ف٢ قرار ج).
محلية بالكامل: باركيه اصطناعي صغير بدل التنزيل."""
import pytest

pyarrow = pytest.importorskip("pyarrow")  # pyarrow للتشغيل والاختبار معاً

import database
import hf_syria_laws as hf


def _write_parquets(tmp_path, laws, articles):
    import pyarrow.parquet as pq
    lp, ap = tmp_path / "laws.parquet", tmp_path / "arts.parquet"
    pq.write_table(pyarrow.Table.from_pylist(laws), lp)
    pq.write_table(pyarrow.Table.from_pylist(articles), ap)
    return lp, ap


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "hf.db"))
    database.create_tables()
    return database.get_connection()


_FILLER = ("ينشأ الالتزام عن التراضي بين الطرفين ويجب أن يكون محله "
           "مشروعاً غير مخالف للقانون والنظام العام والآداب. ")


def _law(lid, title, url):
    return {"id": lid, "title": title, "text": title,
            "source_url": url, "source_type": "parliament_sy_archive",
            "article_count": "3"}


def _arts(lid, n):
    return [{"law_id": lid, "id": f"{lid}-{i}", "title": f"المادة {i}",
             "text": f"المادة {i} — {_FILLER}نص قانوني مستوفٍ للبوابات "
                     f"والطول المطلوب لاجتياز فحص الجودة.",
             "article_number": f"المادة {i}", "record_type": "article"}
            for i in range(1, n + 1)]


def test_import_gates_and_tier(tmp_path, monkeypatch):
    """الجاهز يدخل بطبقة 3 صراحة؛ الفارغ يُهمل ويبقى بالفهرس."""
    laws = [_law("good", "القانون رقم 5 لعام 2006",
                 "http://parliament.gov.sy/laws/Law/2006/good.htm"),
            _law("empty", "المرسوم رقم 9",
                 "http://parliament.gov.sy/laws/Decree/2001/empty.htm")]
    lp, ap = _write_parquets(
        tmp_path, laws, _arts("good", 6))
    conn = _db(tmp_path, monkeypatch)
    rep = hf.import_hf_laws(conn, lp, ap)
    assert rep["imported"] == 1 and rep["empty"] == 1
    doc = conn.execute("SELECT source_domain_tier, status, identity_key "
                       "FROM documents").fetchone()
    assert doc["source_domain_tier"] == 3      # إسناد صادق — لا طبقة 1
    assert doc["status"] == "active"
    assert doc["identity_key"] == "القانون:5:2006"
    assert conn.execute("SELECT COUNT(*) c FROM articles"
                        ).fetchone()["c"] == 6
    # الفهرس يشمل الصكين — الفارغ لزحف الأرشيف
    import json
    idx = json.loads((hf.Path(__file__).parent.parent / "output"
                      / "hf_index.json").read_text(encoding="utf-8"))
    assert {r["id"] for r in idx} == {"good", "empty"}
    conn.close()


def test_import_idempotent_and_alternate_vs_better(tmp_path, monkeypatch):
    """إعادة الاستيراد تخطي؛ وهوية موجودة أفضل من ويبو (طبقة 2) تبقى
    والوافد يصير نسخة بديلة موثقة."""
    # صيغة الهوية هنا تُلتقط؛ صيغة المجموعة الفعلية «رقم/ 148/ لعام
    # /1949/» لا يلتقطها المستخرج (قِيس بالتحليل) — الرابط يظل الفهرس
    laws = [_law("penal", "القانون رقم 148 لعام 1949",
                 "http://parliament.gov.sy/laws/Decree/1949/p18.htm")]
    lp, ap = _write_parquets(tmp_path, laws, _arts("penal", 5))
    conn = _db(tmp_path, monkeypatch)
    # نسخة أفضل موجودة مسبقاً (هوية العقوبات، طبقة 2 كويبو)
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "identity_key, source_domain_tier, quality_score, is_complete_text, "
        "status) VALUES ('wipo-penal', 'عقوبات ويبو', "
        "'https://wipo.int/x', ?, 'القانون:148:1949', 2, 0.9, 1, "
        "'active')", (("نص ويبو " + _FILLER) * 30,))
    conn.commit()
    rep = hf.import_hf_laws(conn, lp, ap)
    assert rep["alternate"] == 1
    rows = conn.execute("SELECT status FROM documents "
                        "ORDER BY id").fetchall()
    assert {r["status"] for r in rows} == {"active", "alternate_source"}
    rep2 = hf.import_hf_laws(conn, lp, ap)
    assert rep2["skipped"] == 1    # إعادة الاستيراد مطابقة ← تخطٍ
    assert conn.execute("SELECT COUNT(*) c FROM documents"
                        ).fetchone()["c"] == 2
    conn.close()


def test_download_verifies_sha256(tmp_path, monkeypatch):
    """تنزيل بمحتوى فاسد يُرفض بصمةً — لا بيانات بلا تحقق."""
    class _BadResp:
        content = b"not the parquet"
        def raise_for_status(self):
            pass

    monkeypatch.setattr(hf.requests, "get", lambda *a, **k: _BadResp())
    monkeypatch.setattr(hf, "dataset_dir", lambda: tmp_path)
    with pytest.raises(RuntimeError) as e:
        hf.download_dataset()
    assert "بصمة" in str(e.value)


# ── دمج تصادمات ما قبل الهوية (dedup-existing) ──
def test_dedupe_active_by_identity_merges_and_archives(tmp_path, monkeypatch):
    """نسختان نشطتان بنفس الهوية (كسبتاها بعد الحفظ بreidentify):
    الأفضل تبقى نشطة، الخاسرة superseded + نسخة مؤرشفة + قرار مدوَّن،
    ومواد كلتيهما لا تُحذف."""
    from dedup import dedupe_active_by_identity
    conn = _db(tmp_path, monkeypatch)
    for doc_id, tier, arts in (("wipo", 2, 5), ("forum", 4, 3)):
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_url, clean_content, "
            "identity_key, source_domain_tier, quality_score, is_complete_text, "
            "status) VALUES (?, ?, ?, ?, 'القانون:9:2010', ?, 0.5, 1, 'active')",
            (doc_id, f"قانون {doc_id}", f"https://{doc_id}/x",
             "نص " + _FILLER * 5, tier))
        d_id = conn.execute("SELECT id FROM documents WHERE doc_id=?",
                            (doc_id,)).fetchone()["id"]
        for i in range(arts):
            conn.execute("INSERT INTO articles (doc_id, article_number, "
                         "article_label, text) VALUES (?, ?, ?, ?)",
                         (d_id, str(i + 1), f"المادة {i + 1}", _FILLER))
    conn.commit()

    rep = dedupe_active_by_identity(conn)
    assert rep == {"collisions": 1, "archived": 1}
    rows = {r["doc_id"]: r["status"] for r in
            conn.execute("SELECT doc_id, status FROM documents")}
    assert rows["wipo"] == "active"        # تير 2 يهزم تير 4
    assert rows["forum"] == "superseded"
    assert conn.execute("SELECT COUNT(*) c FROM document_versions"
                        ).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM dedup_decisions"
                        ).fetchone()["c"] == 1
    # مواد كلتيهما باقية — التاريخ لا يُحذف
    assert conn.execute("SELECT COUNT(*) c FROM articles"
                        ).fetchone()["c"] == 8
    # إعادة التشغيل: لا تصادمات متبقية
    assert dedupe_active_by_identity(conn)["collisions"] == 0
    conn.close()


def test_dedupe_ignores_superseded_and_alternate(tmp_path, monkeypatch):
    """المؤرشفة والبديلة خارج المنافسة — إلا النشطة تُقارن."""
    from dedup import dedupe_active_by_identity
    conn = _db(tmp_path, monkeypatch)
    for doc_id, status in (("a", "superseded"), ("b", "alternate_source"),
                           ("c", "active"), ("d", "active")):
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_url, clean_content, "
            "identity_key, source_domain_tier, status) VALUES "
            "(?, 'ق', ?, 'ن', 'القانون:5:2011', 3, ?)",
            (doc_id, f"https://{doc_id}/x", status))
    conn.commit()
    rep = dedupe_active_by_identity(conn)
    assert rep["collisions"] == 1 and rep["archived"] == 1
    n_active = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE status='active'"
    ).fetchone()["c"]
    assert n_active == 1  # ناجٍ واحد فقط من c/d؛ a وb خارج المنافسة أصلاً
    conn.close()
