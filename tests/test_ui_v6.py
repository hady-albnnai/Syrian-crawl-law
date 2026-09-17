# -*- coding: utf-8 -*-
"""اختبارات دفعة 6 — الطابور قابل للتشخيص من داخل الشاشة، لا من الطرفية فقط.

العلة المقيسة في دفعة 5 (وثّقتها ثم أُنجزت الآن): تبويب «توزيع أسباب الفشل»
كان يعدّ لكل عطل، ولا يدلك على مهمة واحدة منها — فـ«لماذا فشلت الـ8,501؟»
سؤال بلا جواب، والإعادة كانت جماعية عمياء (`cli requeue` بكل الفاشل) أو بلا
إعادة. الآن: جدول `crawl_tasks` بفلتر حالة وبحث، وإعادة **للمحدد** بالـid.

المبدأ المتبع منذ دفعة 3: لا منطق ثانٍ في الواجهة — القراءة عبر
`crawl_queue.list_tasks`، والفعل عبر `crawl_queue.requeue`.

بلا شبكة. تحتاج Qt (offscreen) — تُتخطى بأناقة إن غابت مكتبات النظام.
"""
import os

import pytest

from PySide6.QtCore import Qt  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
except ImportError as exc:  # حاوية بلا مكتبات Qt النظامية (libxkbcommon/…)
    if os.environ.get("MIZAN_ALLOW_NO_QT") != "1":
        raise
    pytest.skip(f"Qt غير متاح هنا: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogs(monkeypatch):
    """لا حوار حقيقي في offscreen — يعلّق CI بلا ردّ (قِيس في دفعة 5)."""
    seen = {"question": [], "information": [], "warning": []}

    def answer_yes(*a, **k):
        seen["question"].append(a[1] if len(a) > 1 else "")
        return QMessageBox.StandardButton.Yes

    def record(kind):
        def _f(*a, **k):
            seen[kind].append(tuple(str(x) for x in a[1:3]))
        return _f

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer_yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(record("information")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(record("warning")))
    return seen


@pytest.fixture
def dialogs_no(monkeypatch):
    seen = {"question": [], "information": [], "warning": []}

    def answer_no(*a, **k):
        seen["question"].append(a[1] if len(a) > 1 else "")
        return QMessageBox.StandardButton.No

    def record(kind):
        def _f(*a, **k):
            seen[kind].append(tuple(str(x) for x in a[1:3]))
        return _f

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer_no))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(record("information")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(record("warning")))
    return seen


@pytest.fixture
def q_db(tmp_path, monkeypatch):
    """طابور بحالات متعددة وأسباب مختلفة، على قاعدة مؤقتة."""
    import config
    import database
    db = tmp_path / "v6.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    tasks = [  # (url, status, attempts, last_error)
        ("https://x/f1", "failed", 3, "http_404"),
        ("https://x/f2", "failed", 2, "timeout"),
        ("https://x/f3", "failed", 1, "http_500"),
        ("https://journal/b1", "blocked", 1, "robots_disallow"),
        ("https://x/q1", "queued", 0, None),
        ("https://x/s1", "success", 2, None),
        ("https://x/r1", "needs_review", 1, "quality_below_gate"),
    ]
    for url, status, attempts, err in tasks:
        cur.execute(
            "INSERT INTO crawl_tasks (url, section, kind, status, attempts,"
            " last_error, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (url, "عام", "page", status, attempts, err,
             "2026-09-17T10:00:00", "2026-09-17T10:20:00"))
    conn.commit()
    yield conn
    conn.close()


# ───────────────────────────────────────────────── 1) القراءة
def test_task_rows_are_the_queue_verbatim(q_db):
    from app import core_data as md
    rows = md.task_rows()
    assert len(rows) == 7, f"توقعنا 7 مهام، لا {len(rows)}"
    assert rows[0]["id"] == 7, "list_tasks يرتّب الأحدث أولاً — لا نفترض العكس"
    assert {r["status"] for r in rows} == {"failed", "blocked", "queued",
                                          "success", "needs_review"}
    failed = md.task_rows(status="failed")
    assert [r["last_error"] for r in failed] == ["http_500", "timeout", "http_404"]
    assert all(r["attempts"] for r in failed), "عدّاد المحاولات جزء من التشخيص"


def test_task_rows_filter_by_needle_and_limit(q_db):
    from app import core_data as md
    assert [r["url"] for r in md.task_rows(needle="journal")] == \
        ["https://journal/b1"]
    assert len(md.task_rows(limit=2)) == 2
    assert md.task_rows(status="success", needle="nope") == []


def test_task_rows_without_database_is_empty_not_traceback(tmp_path, monkeypatch):
    import config
    from app import core_data as md
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    assert md.task_rows() == []
    assert md.requeue_ids([1]) == {"revived": 0, "error": "لا قاعدة/لا طابور"}


def test_queue_filter_keys_match_core_data(q_db):
    """الفلتر في الشاشة يشتق من md.TASK_STATUSES — لا نسخة ثانية منه."""
    from app import core_data as md
    assert md.TASK_STATUSES["الفاشلة"] == "failed"
    assert md.TASK_STATUSES["الكل"] == ""
    assert set(md.TASK_STATUSES.values()) <= {"", "failed", "blocked", "queued",
                                             "running", "needs_review",
                                             "success"}


# ───────────────────────────────────────────────── 2) الفعل
def test_requeue_ids_moves_only_the_selected(q_db):
    from app import core_data as md
    ids = [r["id"] for r in md.task_rows(status="failed")][:2]
    res = md.requeue_ids(ids)
    assert res["revived"] == 2 and res["missing"] == []
    st = dict(q_db.execute("SELECT id, status FROM crawl_tasks").fetchall())
    att = dict(q_db.execute("SELECT id, attempts FROM crawl_tasks").fetchall())
    for i in ids:
        assert st[i] == "queued" and att[i] == 0
    # الثالثة الفاشلة لم تُذكر ⇒ كما هي، وكذلك الناجحة والمحجوبة
    by_url = dict(q_db.execute("SELECT url, status FROM crawl_tasks").fetchall())
    assert by_url["https://x/s1"] == "success"
    assert by_url["https://journal/b1"] == "blocked"
    remaining = md.task_rows(status="failed")
    assert len(remaining) == 1, f"كان يجب أن يبقى فاشل واحد، لا {len(remaining)}"


def test_requeue_ids_reports_missing_and_refuses_empty(q_db):
    from app import core_data as md
    res = md.requeue_ids([1, 4242])
    assert res["revived"] == 1 and res["missing"] == [4242]
    assert md.requeue_ids([])["error"]


def test_requeue_ids_does_not_touch_success(q_db):
    from app import core_data as md
    sid = [r["id"] for r in md.task_rows(status="success")][0]
    md.requeue_ids([sid])
    assert q_db.execute("SELECT status FROM crawl_tasks WHERE id=?",
                        (sid,)).fetchone()[0] == "queued", "بالطلب الصريح تُعاد"
    before = dict(q_db.execute("SELECT id, status FROM crawl_tasks").fetchall())
    md.preview_requeue(("failed", "blocked"))     # لا كتابة
    after = dict(q_db.execute("SELECT id, status FROM crawl_tasks").fetchall())
    assert before == after


# ───────────────────────────────────────────────── 3) الشاشة
def test_reports_tab_shows_queue_table_with_reasons(q_db, app):
    from app.pages.review_page import ReviewPage
    pg = ReviewPage()
    try:
        # الافتراضي «الفاشلة»: الشاشة تفتح على ما يُعالَج لا على كل شيء
        assert pg.queue_filter.currentText() == "الفاشلة"
        assert pg.queue_model.rowCount() == 3
        pg.queue_filter.setCurrentText("الكل")
        assert pg.queue_model.columnCount() == 6
        assert pg.queue_model.rowCount() == 7
        r0 = pg.queue_model._rows[0]
        assert pg.queue_model.data(pg.queue_model.index(0, 1)) == \
            pg.queue_model.STATUS_AR[r0["status"]]
        assert pg.queue_model.headerData(4, Qt.Horizontal) == "آخر عطل"
        # آخر عطل يُعرض حرفياً، وبلا سبب يُقال «لا سبب مسجل» لا يترك فراغاً
        i_err = next(i for i in range(7)
                     if pg.queue_model._rows[i]["url"] == "https://x/f1")
        assert pg.queue_model.data(pg.queue_model.index(i_err, 4)) == "http_404"
        i_ok = next(i for i in range(7)
                    if pg.queue_model._rows[i]["url"] == "https://x/q1")
        assert pg.queue_model.data(pg.queue_model.index(i_ok, 4)) == "لا سبب مسجل"
        assert "معروض 7 من أصل 7" in pg.queue_note.text()
        assert "400" in pg.queue_note.text(), "السقف يجب أن يكون معلناً"
    finally:
        pg.deleteLater()


def test_reports_tab_status_filter_narrows_table(q_db, app):
    from app.pages.review_page import ReviewPage
    pg = ReviewPage()
    try:
        pg.queue_filter.setCurrentText("الفاشلة")
        assert pg.queue_model.rowCount() == 3
        pg.queue_search.setText("journal")
        assert pg.queue_model.rowCount() == 0
        pg.queue_filter.setCurrentText("المحجوبة")
        assert pg.queue_model.rowCount() == 1
        assert pg.queue_model.task_id(0) is not None
    finally:
        pg.deleteLater()


def test_requeue_selected_writes_then_relists(q_db, app, dialogs):
    from PySide6.QtCore import QItemSelectionModel
    from app.pages.review_page import ReviewPage
    from app import core_data as md
    pg = ReviewPage()
    try:
        pg.queue_filter.setCurrentText("الفاشلة")
        ids = [pg.queue_model.task_id(i) for i in range(pg.queue_model.rowCount())]
        for i in range(pg.queue_model.rowCount()):
            pg.queue_view.selectionModel().select(
                pg.queue_model.index(i, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows)
        assert "3" in pg.requeue_sel_btn.text(), "الزرّ لم يحمل عدد المحدد"
        pg._requeue_selected()
        assert dialogs["question"] and dialogs["question"][0] == "تأكيد إعادة المحاولة"
        assert "أُعيد 3" in pg.queue_note.text()
        assert pg.queue_model.rowCount() == 0, "مرشّح «الفاشلة» يجب أن يفرغ بعد الإعادة"
        assert md.queue_counts()["queued"] == 4
    finally:
        pg.deleteLater()


def test_requeue_selected_cancelled_does_not_write(q_db, app, dialogs_no,
                                                   monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    from app.pages import review_page as rp
    from app.pages.review_page import ReviewPage
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    pg = ReviewPage()
    try:
        pg.queue_filter.setCurrentText("المحجوبة")
        pg.queue_view.selectionModel().select(
            pg.queue_model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows)
        pg._requeue_selected()
        assert "أُلغيت الإعادة" in pg.queue_note.text()
        assert rp.md.queue_counts()["blocked"] == 1, "الإلغاء لا يكتب"
    finally:
        pg.deleteLater()


def test_requeue_selected_without_selection_refuses_loudly(q_db, app, dialogs):
    from app.pages.review_page import ReviewPage
    pg = ReviewPage()
    try:
        pg.queue_view.selectionModel().clearSelection()
        pg._requeue_selected()
        assert dialogs["information"], "بلا تحديد ولا رسالة = زرّ ميت"
        assert dialogs["information"][0][0] == "لا تحديد"
    finally:
        pg.deleteLater()


def test_bulk_requeue_button_is_named_as_bulk(q_db, app):
    """الزرّان متجاوران وجملة كل واحد غير جملة الآخر — خطأ نقر مكلف هنا."""
    from app.pages.review_page import ReviewPage
    pg = ReviewPage()
    try:
        bulk, sel = pg.requeue_btn.text(), pg.requeue_sel_btn.text()
        assert "كل الفاشل" in bulk and "للمحدد" in sel
        assert bulk != sel
    finally:
        pg.deleteLater()


def test_no_english_filler_leaked_into_ui_strings():
    """«تصفية optionally…» تسللت حرفياً — ولولا الفحص لبقيت في الواجهة.

    المفهوم من نص المستخدم معطى للعامة: لا كلمات إنكليزية حشو في النصوص
    الظاهرة (يُستثنى ما بين backticks فهو اسم جدول/أمر مقصود).
    """
    import re
    from pathlib import Path as P
    root = P(__file__).resolve().parents[1]
    filler = re.compile(r"\b(optionally|placeholder|TODO|FIXME|N/A|dummy|fake)\b",
                        re.IGNORECASE)
    bad = []
    for f in sorted((root / "app" / "pages").glob("*.py")) + \
             [root / "app" / "main.py", root / "app" / "core_data.py"]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            in_str = re.findall(r'"([^"\n]*)"', line)
            for chunk in in_str:
                stripped = re.sub(r"`[^`]*`", "", chunk)
                if filler.search(stripped):
                    bad.append(f"{f.name}:{n}: {chunk[:60]}")
    assert not bad, "حشو إنكليزي في نص ظاهر:\n" + "\n".join(bad)


def test_cli_commands_named_in_readme_exist():
    """README يشير لأوامر — يجب أن تكون موجودة في `cli.py` حرفياً.

    العلة المتكررة في هذا المشروع: توثيق يسبق الأمر أو يتأخر عنه، فالمالك
    ينفّذ أمراً بلا سند. الفحص نصّي على معرّفات `add_parser`.
    """
    import re
    from pathlib import Path as P
    root = P(__file__).resolve().parents[1]
    declared = set(re.findall(r'add_parser\("([a-z][a-z-]+)"',
                              (root / "cli.py").read_text(encoding="utf-8")))
    readme = (root / "README.md").read_text(encoding="utf-8")
    used = set(re.findall(r'python -m cli ([a-z][a-z-]+)', readme))
    assert used, "فقدنا قراءة الأوامر من README — الاختبار بلا معنى"
    missing = sorted(used - declared)
    assert not missing, f"README يسمّي أوامر غير موجودة في cli.py: {missing}"


def test_smoke_asserts_queue_columns_exist():
    """الدخان المجمّد يجب أن يفحص الجدول الجديد — لا الشاشة فقط."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py"
           ).read_text(encoding="utf-8")
    assert "queue_model.columnCount() == 6" in src
    assert "len(md.TASK_STATUSES)" in src
