# -*- coding: utf-8 -*-
"""اختبارات learning — التعلّم من التجارب السابقة (محلية، لا شبكة).

DELIVERY/DESIGN-SELF-DISCOVERY.md §5: عدّاد شفاف — مصدر منتج يُعطى
أولوية، مصدر مستنفد (3 دورات فارغة متتالية) يُستبعد من إعادة الفحص.
"""
import database
import learning


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "learn.db"))
    database.create_tables()
    return database.get_connection()


def _approve_source(conn, key, base_url, name="مصدر"):
    conn.execute(
        "INSERT INTO sources (source_key, base_url, name, status) "
        "VALUES (?, ?, ?, 'approved')", (key, base_url, name))
    conn.commit()


def _add_doc(conn, source_url, identity_key, status="active"):
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, identity_key, "
        "status) VALUES (?, ?, ?, ?, ?)",
        (f"sha256:{identity_key}-{source_url}", "قانون", source_url,
         identity_key, status))
    conn.commit()


# ───────────────────────── update_source_performance ─────────────────────────

def test_first_run_counts_existing_identities_as_new(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    _add_doc(conn, "https://forum.example/t1", "القانون:1:2020")
    _add_doc(conn, "https://forum.example/t2", "القانون:2:2020")

    summary = learning.update_source_performance(conn)
    assert summary["s1"]["new_this_run"] == 2
    assert summary["s1"]["learned_status"] == "active"


def test_no_new_identities_increments_empty_run_counter(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    _add_doc(conn, "https://forum.example/t1", "القانون:1:2020")
    learning.update_source_performance(conn)  # دورة 1: منتجة

    # دورة 2 و3 و4 بلا وثائق جديدة من هذا المصدر
    for _ in range(3):
        summary = learning.update_source_performance(conn)

    assert summary["s1"]["consecutive_empty_runs"] == 3
    assert summary["s1"]["learned_status"] == "exhausted"


def test_new_identity_resets_empty_run_counter(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    _add_doc(conn, "https://forum.example/t1", "القانون:1:2020")
    learning.update_source_performance(conn)
    learning.update_source_performance(conn)  # فارغة

    _add_doc(conn, "https://forum.example/t2", "القانون:2:2020")
    summary = learning.update_source_performance(conn)
    assert summary["s1"]["consecutive_empty_runs"] == 0
    assert summary["s1"]["learned_status"] == "active"


def test_superseded_documents_not_double_counted(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    _add_doc(conn, "https://forum.example/t1", "القانون:1:2020",
            status="superseded")
    summary = learning.update_source_performance(conn)
    assert summary["s1"]["new_this_run"] == 0


# ───────────────────────── is_source_exhausted ─────────────────────────

def test_is_source_exhausted_false_when_no_record(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    assert learning.is_source_exhausted(conn, "unknown") is False


def test_is_source_exhausted_true_after_threshold(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    for _ in range(3):
        learning.update_source_performance(conn)
    assert learning.is_source_exhausted(conn, "s1") is True


# ───────────────────────── prioritized_active_sources ─────────────────────────

def test_prioritized_sources_orders_by_production_desc(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://low.example/")
    _approve_source(conn, "s2", "https://high.example/")
    _add_doc(conn, "https://low.example/t1", "القانون:1:2020")
    _add_doc(conn, "https://high.example/t1", "القانون:2:2020")
    _add_doc(conn, "https://high.example/t2", "القانون:3:2020")
    learning.update_source_performance(conn)

    ordered = learning.prioritized_active_sources(conn)
    assert ordered[0]["base_url"] == "https://high.example/"


def test_exhausted_sources_excluded_from_prioritized_list(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://forum.example/")
    for _ in range(3):
        learning.update_source_performance(conn)
    ordered = learning.prioritized_active_sources(conn)
    assert ordered == []


def test_source_with_no_performance_record_yet_still_listed(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _approve_source(conn, "s1", "https://brand-new.example/")
    ordered = learning.prioritized_active_sources(conn)
    assert len(ordered) == 1
    assert ordered[0]["base_url"] == "https://brand-new.example/"
