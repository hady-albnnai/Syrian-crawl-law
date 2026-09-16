# -*- coding: utf-8 -*-
"""اختبارات law_status — سلسلة التعديلات والحالة القانونية (ف١).

محلية بالكامل: نصوص الإحالات مأخوذة من صياغات تشريعية سورية حقيقية
(مثال موثق: القانون رقم 3 لعام 2010 القاضي بتعديل بعض مواد القانون
رقم 28 لعام 2001 المتعلق بعمل المصارف المرخصة في سورية).
"""
import law_status as ls


# ───────────────────────── تصنيف نية الإحالة ─────────────────────────

def test_amend_context_classified():
    assert ls.classify_context(
        "القاضي بتعديل بعض مواد القانون رقم 28 لعام 2001") == "amend"


def test_repeal_context_classified():
    assert ls.classify_context(
        "المادة 2- يلغى القانون رقم 91 لعام 1959") == "repeal"


def test_repeal_precedence_over_amend():
    # «يلغي وينسخ ويعوض» — الأثر الغالب للمستهدف زواله
    assert ls.classify_context("يلغي القانون رقم 5 ويعوض بتعديل") == "repeal"


def test_neutral_citation_not_a_relation():
    assert ls.classify_context(
        "استناداً إلى أحكام القانون رقم 10 لعام 2006") == "cite"


def test_empty_context_is_cite():
    assert ls.classify_context("") == "cite"


# ───────────────────────── استخراج علاقات التعديل ─────────────────────────

_AMENDING_TEXT = (
    "القانون رقم 3 لعام 2010 القاضي بتعديل بعض مواد القانون رقم 28 "
    "لعام 2001 المتعلق بعمل المصارف المرخصة في سورية. "
    "المادة 1- تعدل المواد 12 و45 من القانون رقم 28 لعام 2001 على "
    "النحو الآتي. المادة 2- يلغى القانون رقم 91 لعام 1959."
)


def test_extracts_amend_and_repeal_targets():
    ams = ls.extract_amendments(
        "القانون رقم 3 لعام 2010 القاضي بتعديل بعض مواد القانون رقم 28",
        _AMENDING_TEXT)
    by_key = {a["target_identity"]: a["action"] for a in ams}
    assert by_key.get("القانون:28:2001") == "amend"
    assert by_key.get("القانون:91:1959") == "repeal"


def test_self_reference_excluded():
    # الوثيقة تذكر صكها بديباجتها — ليست تعديلاً لنفسها
    ams = ls.extract_amendments(
        "القانون رقم 3 لعام 2010 القاضي بتعديل بعض مواد القانون رقم 28",
        _AMENDING_TEXT)
    assert all(a["target_identity"] != "القانون:3:2010" for a in ams)


def test_neutral_citations_not_recorded():
    ams = ls.extract_amendments(
        "قانون الالتزامات",
        "استناداً إلى أحكام القانون رقم 10 لعام 2006 نص المادة الأولى...")
    assert ams == []


# ───────────────────────── التسجيل والحساب (قاعدة حقيقية) ─────────────────────────

def _tmp_db(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "law_status.db"))
    database.create_tables()
    return database.get_connection()


def _insert_doc(conn, title, content, identity):
    _t, number, year = identity.split(":")
    cur = conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "identity_key, doc_type, number, year) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (identity.replace(":", "_"), title,
         f"https://test/{identity}", content, identity,
         _t, int(number), int(year)))
    return cur.lastrowid


def test_record_compute_and_chain(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    # الصك المستهدف + صكان يعدلانه + صك يلغيه
    target_id = _insert_doc(
        conn, "القانون رقم 28 لعام 2001 المتعلق بعمل المصارف",
        "نص القانون 28 لعام 2001 الكامل هنا بمواده.", "القانون:28:2001")
    amend1 = _insert_doc(conn, "القانون رقم 3 لعام 2010",
                         _AMENDING_TEXT, "القانون:3:2010")
    repeal1 = _insert_doc(
        conn, "القانون رقم 6 لعام 2015",
        "المادة 1- يلغى القانون رقم 28 لعام 2001 بكامل مواده.",
        "القانون:6:2015")
    standalone = _insert_doc(conn, "قانون بلا إحالات", "نص محايد.",
                             "القانون:99:1999")

    n = ls.record_amendments_for_doc(conn.cursor(), amend1,
                                     "القانون رقم 3 لعام 2010",
                                     _AMENDING_TEXT)
    conn.commit()
    assert n >= 2  # تعديل 28/2001 + إلغاء 91/1959
    ls.record_amendments_for_doc(
        conn.cursor(), repeal1, "القانون رقم 6 لعام 2015",
        "المادة 1- يلغى القانون رقم 28 لعام 2001 بكامل مواده.")
    conn.commit()

    counts = ls.compute_legal_statuses(conn)
    # الإلغاء يغلب التعديل
    status = conn.execute(
        "SELECT legal_status FROM documents WHERE id=?",
        (target_id,)).fetchone()["legal_status"]
    assert status == "ملغى"
    # الصك المحايد ساري (لا إحالات عليه)
    standalone_status = conn.execute(
        "SELECT legal_status FROM documents WHERE id=?",
        (standalone,)).fetchone()["legal_status"]
    assert standalone_status == "ساري"
    assert counts["ملغى"] >= 1 and counts["ساري"] >= 1

    chain = ls.law_chain(conn, "القانون:28:2001")
    actions = [r["action"] for r in chain]
    assert "amend" in actions and "repeal" in actions
    years = [r["year"] for r in chain]
    assert years == sorted(years)  # مرتبة زمنياً


def test_amend_only_yields_modified_status(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "القانون رقم 28 لعام 2001", "نص.", "القانون:28:2001")
    amend_doc = _insert_doc(conn, "القانون رقم 3 لعام 2010",
                            _AMENDING_TEXT, "القانون:3:2010")
    ls.record_amendments_for_doc(conn.cursor(), amend_doc,
                                 "القانون رقم 3 لعام 2010", _AMENDING_TEXT)
    conn.commit()
    ls.compute_legal_statuses(conn)
    status = conn.execute(
        "SELECT legal_status FROM documents WHERE identity_key=?",
        ("القانون:28:2001",)).fetchone()["legal_status"]
    assert status == "معدَّل"


def test_document_without_identity_gets_no_status(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content) "
        "VALUES ('x', 'وثيقة بلا رقم', 'https://test/x', 'نص عادي')")
    conn.commit()
    counts = ls.compute_legal_statuses(conn)
    row = conn.execute(
        "SELECT legal_status FROM documents WHERE doc_id='x'").fetchone()
    assert row["legal_status"] is None
    assert counts["بلا هوية (بلا حالة)"] == 1


def test_rebuild_links_from_existing_documents(tmp_path, monkeypatch):
    conn = _tmp_db(tmp_path, monkeypatch)
    _insert_doc(conn, "القانون رقم 28 لعام 2001", "نص.", "القانون:28:2001")
    _insert_doc(conn, "القانون رقم 3 لعام 2010", _AMENDING_TEXT,
                "القانون:3:2010")
    total = ls.rebuild_links(conn)
    assert total >= 2
    rows = conn.execute(
        "SELECT COUNT(*) FROM law_amendments").fetchone()[0]
    assert rows == total
