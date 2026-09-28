"""مسار النماذج منفصل عن التشريعات؛ اختبارات SQLite/HTML محلية."""
import csv
import json

import pytest

import database
import forms


HTML_FORM = """
<html><head><title>نموذج عقد بيع سوري</title></head>
<body><nav>روابط</nav><main>
<h1>نموذج عقد بيع</h1>
<p>في يوم ______ تم الاتفاق بين الطرفين على ما يلي: يقر البائع بملكيته للمبيع،
ويلتزم المشتري بأداء الثمن وفق الشروط المتفق عليها، وتُحدد الالتزامات والمدة
والضمانات في البنود التالية بما لا يخالف أحكام القانون السوري.</p>
<label>اسم البائع</label><input name="seller_name" placeholder="اسم البائع">
<p>حرر في دمشق، ويوقع الطرفان أدناه.</p>
</main><footer>حقوق الموقع</footer></body></html>
"""


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db = tmp_path / "forms.db"
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    connection = database.get_connection()
    yield connection
    connection.close()


def _approved_source(conn):
    cur = conn.execute(
        "INSERT INTO sources (source_key, base_url, name, status, source_role) "
        "VALUES ('src', 'https://forms.example/legal', 'بوابة النماذج', "
        "'approved', 'bar_association')")
    conn.commit()
    return cur.lastrowid


def _candidate(conn):
    return forms.register_candidate(
        conn, "نموذج عقد بيع", "https://forms.example/legal/contract-sale",
        template_type="contract", discovered_via="search:fixture")[0]


def _fetch(_url):
    return {"ok": True, "status": 200, "html": HTML_FORM,
            "final_url": "https://forms.example/legal/contract-sale"}


def test_queries_cover_requested_form_types_without_network():
    for kind in ("contract", "summons", "memorandum", "petition", "application"):
        queries = forms.template_queries(kind)
        assert queries and all("سوريا" in q or "سوري" in q or "سورية" in q
                               for q in queries)
    assert forms.classify_form_type("", "صيغة استدعاء للمحكمة") == "summons"
    assert forms.classify_form_type("مذكرة دفاع", "") == "memorandum"
    assert forms.classify_form_type("لائحة دعوى", "") == "petition"


def test_search_candidate_is_metadata_only_and_creates_no_crawl_task(conn):
    candidate = {"url": "https://forms.example/legal/contract-sale",
                 "title": "نموذج عقد بيع", "snippet": "لا يُحفظ هذا المقتطف"}
    report = forms.register_search_results(conn, [candidate], "contract", "search:test")
    assert report == {"added": 1, "duplicates": 0, "invalid": 0}
    row = conn.execute("SELECT * FROM templates").fetchone()
    assert row["review_status"] == "pending"
    assert row["rights_status"] == "unknown"
    assert row["body"] is None and row["content_sha256"] is None
    assert conn.execute("SELECT COUNT(*) FROM crawl_tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert "snippet" not in [r["name"] for r in conn.execute("PRAGMA table_info(templates)")]


def test_fetch_requires_approved_source_and_does_not_store_text_by_default(conn):
    template_id = _candidate(conn)
    with pytest.raises(PermissionError):
        forms.fetch_candidate(conn, template_id, fetch_fn=_fetch)
    _approved_source(conn)
    report = forms.fetch_candidate(conn, template_id, fetch_fn=_fetch)
    assert report["ok"] and report["text_stored"] is False
    row = conn.execute("SELECT body, content_sha256, is_complete_text, "
                       "review_status FROM templates WHERE id=?",
                       (template_id,)).fetchone()
    assert row["body"] is None and row["content_sha256"]
    assert row["is_complete_text"] == 0 and row["review_status"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM template_versions").fetchone()[0] == 0


def test_store_requires_rights_evidence_then_human_review_and_separate_export(
        conn, tmp_path):
    _approved_source(conn)
    template_id = _candidate(conn)
    with pytest.raises(ValueError, match="حقوقاً مسموحة"):
        forms.fetch_candidate(conn, template_id, fetch_fn=_fetch, store_text=True)
    with pytest.raises(ValueError, match="رابط http/https"):
        forms.fetch_candidate(
            conn, template_id, fetch_fn=_fetch, store_text=True,
            rights_status="permission", rights_evidence_url="javascript:alert(1)")

    fetched = forms.fetch_candidate(
        conn, template_id, fetch_fn=_fetch, store_text=True,
        rights_status="permission",
        rights_evidence_url="https://forms.example/legal/terms")
    assert fetched["text_stored"] is True
    row = conn.execute("SELECT body, content_sha256, source_role FROM templates "
                       "WHERE id=?", (template_id,)).fetchone()
    assert row["body"] and row["content_sha256"] and row["source_role"] == "bar_association"
    assert conn.execute("SELECT COUNT(*) FROM template_versions").fetchone()[0] == 1

    review = forms.review_template(
        conn, template_id, reviewer="مراجع اختبار", completeness="pass",
        currentness="pass", jurisdiction="SY", rights_status="permission",
        source_role="bar_association",
        completeness_evidence_url="https://forms.example/legal/contract-sale",
        currentness_evidence_url="https://forms.example/legal/contract-sale",
        jurisdiction_evidence_url="https://forms.example/about",
        rights_evidence_url="https://forms.example/legal/terms")
    assert review["review_status"] == "approved"
    assert forms.is_exportable(conn, conn.execute(
        "SELECT * FROM templates WHERE id=?", (template_id,)).fetchone())

    out = tmp_path / "forms-export"
    report = forms.export_templates(conn, out)
    assert report["exported"] == 1
    assert (out / "syrian_legal_forms.csv").exists()
    assert not (out / "laws_decrees_index.csv").exists()
    exported = list(csv.DictReader(open(out / "syrian_legal_forms.csv",
                                      encoding="utf-8-sig")))
    assert len(exported) == 1 and exported[0]["export_eligible"] == "True"
    assert exported[0]["body"] == row["body"]
    payload = json.loads((out / "syrian_legal_forms.json").read_text(encoding="utf-8"))
    assert payload[0]["template_type"] == "contract"
    assert payload[0]["body"]
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_pending_export_is_metadata_only_and_non_syrian_not_eligible(conn, tmp_path):
    _approved_source(conn)
    template_id = _candidate(conn)
    forms.fetch_candidate(conn, template_id, fetch_fn=_fetch, store_text=True,
                          rights_status="licensed",
                          rights_evidence_url="https://forms.example/terms")
    forms.review_template(
        conn, template_id, reviewer="مراجع", completeness="pass",
        currentness="pass", jurisdiction="non-SY", rights_status="licensed",
        source_role="private",
        completeness_evidence_url="https://forms.example/form",
        currentness_evidence_url="https://forms.example/form",
        # لا دليل اختصاص لأن النتيجة سالبة.
        rights_evidence_url="https://forms.example/terms")
    out = tmp_path / "review-only"
    report = forms.export_templates(conn, out, include_pending=True)
    assert report["exported"] == 0 and report["metadata_only"] == 1
    payload = json.loads((out / "syrian_legal_forms.json").read_text(encoding="utf-8"))
    assert payload[0]["body"] == ""
    assert payload[0]["export_eligible"] is False


def test_changed_template_body_invalidates_old_reviews(conn):
    _approved_source(conn)
    template_id = _candidate(conn)
    forms.fetch_candidate(conn, template_id, fetch_fn=_fetch, store_text=True,
                          rights_status="licensed",
                          rights_evidence_url="https://forms.example/terms")
    forms.review_template(
        conn, template_id, reviewer="مراجع", completeness="pass",
        currentness="pass", jurisdiction="SY", rights_status="licensed",
        source_role="bar_association",
        completeness_evidence_url="https://forms.example/form",
        currentness_evidence_url="https://forms.example/form",
        jurisdiction_evidence_url="https://forms.example/about")
    # جلب إصدار مختلف؛ لا يُخزن النص الجديد دون تصريح، وتصبح مراجعات البصمة
    # السابقة غير مطابقة للنسخة الحالية.
    changed = lambda _url: {"ok": True, "final_url": "https://forms.example/legal/contract-sale",
                            "html": "<main><h1>نموذج عقد بيع جديد</h1><p>إصدار جديد.</p></main>"}
    forms.fetch_candidate(conn, template_id, fetch_fn=changed, store_text=True,
                          rights_status="licensed",
                          rights_evidence_url="https://forms.example/terms")
    row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
    assert row["review_status"] == "pending"
    assert not forms.is_exportable(conn, row)
