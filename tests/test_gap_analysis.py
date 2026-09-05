# -*- coding: utf-8 -*-
"""اختبارات gap_analysis — تحليل الفجوات + الفرز بالفرع (محلية، لا شبكة).

DELIVERY/DESIGN-SELF-DISCOVERY.md §7/§9: حد أدنى متوقَّع محسوب آلياً
(30% من متوسط أنجح 3 فروع)، لا رقم ثابت مُخمَّن.
"""
import database
import gap_analysis as ga


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "gaps.db"))
    database.create_tables()
    return database.get_connection()


def _add_docs(conn, branch, n, status="active", offset=0):
    for i in range(offset, offset + n):
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_url, branch, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"sha256:{branch}-{i}", "قانون", f"https://x.example/{branch}{i}",
             branch, status))
    conn.commit()


def test_branch_distribution_includes_zero_branches(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 5)
    dist = ga.branch_distribution(conn)
    assert dist["civil_law"] == 5
    assert dist["tax_law"] == 0  # فرع بلا وثائق يظهر بصفر لا يُسقَط


def test_superseded_documents_excluded_from_distribution(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 3, status="superseded")
    dist = ga.branch_distribution(conn)
    assert dist["civil_law"] == 0


def test_gap_detected_for_underrepresented_branch(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 20)
    _add_docs(conn, "penal_law", 18)
    _add_docs(conn, "commercial_law", 15)
    _add_docs(conn, "tax_law", 1)  # فجوة واضحة نسبة لبقية الفروع
    report = ga.analyze_gaps(conn)
    assert report["tax_law"]["gap"] is True
    assert report["civil_law"]["gap"] is False


def test_expected_minimum_scales_with_corpus_growth(tmp_path, monkeypatch):
    """الحد الأدنى المحسوب يكبر تلقائياً مع نمو القاعدة — لا يبقى ثابتاً."""
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 10)
    _add_docs(conn, "penal_law", 10)
    _add_docs(conn, "commercial_law", 10)
    report_small = ga.analyze_gaps(conn)
    small_expected = report_small["tax_law"]["expected_min"]

    _add_docs(conn, "civil_law", 90, offset=10)  # القاعدة تنمو بكثير
    _add_docs(conn, "penal_law", 90, offset=10)
    _add_docs(conn, "commercial_law", 90, offset=10)
    report_big = ga.analyze_gaps(conn)
    big_expected = report_big["tax_law"]["expected_min"]

    assert big_expected > small_expected


def test_override_takes_precedence_over_computed_value(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 50)
    monkeypatch.setattr(ga, "EXPECTED_MIN_OVERRIDE", {"tax_law": 7})
    report = ga.analyze_gaps(conn)
    assert report["tax_law"]["expected_min"] == 7


def test_gap_queries_for_branch_uses_keywords():
    queries = ga.gap_queries_for_branch("tax_law", limit=2)
    assert len(queries) == 2
    assert all("سوريا قانون نص كامل" in q for q in queries)


def test_gap_driven_queries_only_for_gapped_branches(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 20)
    _add_docs(conn, "penal_law", 20)
    _add_docs(conn, "commercial_law", 20)
    # بقية الفروع بصفر ⇒ فجوة لكل منها
    queries = ga.gap_driven_queries(conn, per_branch_limit=1)
    assert len(queries) > 0


def test_branch_breakdown_for_run_counts_only_new_docs(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _add_docs(conn, "civil_law", 2)
    last_id_before = conn.execute(
        "SELECT MAX(id) FROM documents").fetchone()[0] or 0
    _add_docs(conn, "penal_law", 3)
    breakdown = ga.branch_breakdown_for_run(conn, last_id_before)
    assert breakdown == {"penal_law": 3}
