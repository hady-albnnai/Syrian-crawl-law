# -*- coding: utf-8 -*-
"""اختبارات دفعة 5 — قفل الفراغات التي خلّفتها دفعة الواجهة.

العِلَل الأربع التي بُني هذا الملف ليرفضها (كلّها كانت «الكود موجود، لا زرّ له»):

1) مصادر معلّقة بلا طريقة اعتماد من الواجهة: `auto_approve` مطفأ افتراضياً
   (وهو الصواب)، و`cli sources` هو المسار الوحيد — أي أن المستخدم العادي لا
   يعلم أن الزحف متوقف عند بوابة صامتة.
2) مهام طابور فاشلة بلا إعادة محاولة: `cli requeue` موجود، والشاشة التي
   تعرض عدد الفاشل (تقارير الدورات) لا تعرض عليه فعلاً.
3) «تجريبي — بلا حفظ» كان مفتاح CLI فقط، والواجهة كانت تكرّر ترتيب خطوات
   `run_autopilot` بيدها لأن الدالة لم تكن تقبل `stop_event` — ازدواجية
   تنجرف؛ صارت الشاشة تمرّر عبر `run_autopilot` وحده.
4) أي ادّعاء بـ«أُعيد N مهمة» بلا عدّ قبله وبعده.

بلا شبكة. تحتاج Qt (offscreen) — تُتخطى بأناقة إن غابت مكتبات النظام.
"""
import os
import re
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
except ImportError as exc:  # حاوية بلا مكتبات Qt النظامية (libxkbcommon/…)
    if os.environ.get("MIZAN_ALLOW_NO_QT") != "1":
        raise
    pytest.skip(f"Qt غير متاح هنا: {exc}", allow_module_level=True)

NEEDLE_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef「」，、。]")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogs(monkeypatch):
    """كل حوار وسطي جوابه مسجَّل — لا QModal يعلّق CI في وضع offscreen.

    هذه ليست ترفيهاً: حوار حقيقي في offscreen لا يردّ أبداً، ومن
    «الدخان الأعمى» نفسه — الفشل الصامت أخطر من الفشل.
    """
    seen = {"question": [], "information": [], "warning": []}

    def answer_yes(*a, **k):
        seen["question"].append(a[1] if len(a) > 1 else "")
        return QMessageBox.StandardButton.Yes

    def answer_no(*a, **k):
        seen["question"].append(a[1] if len(a) > 1 else "")
        return QMessageBox.StandardButton.No

    def record(kind):
        def _f(*a, **k):
            seen[kind].append(tuple(str(x) for x in a[1:3]))
        return _f

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer_yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(record("information")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(record("warning")))
    seen["answer_no"] = answer_no
    return seen


@pytest.fixture
def dialogs_no(monkeypatch):
    """نفس الحارس، لكن «إلغاء» — لاختبار أن الإلغاء لا يكتب."""
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
def src_db(tmp_path, monkeypatch):
    """قاعدة فيها 3 مصادر (2 معلّق، 1 مرفوض) + طابور بحالات + وثائق تحتها."""
    import config
    import database
    db = tmp_path / "v5.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    srcs = [("tazarr_tc", "https://tazarr.example", "موقع التشريع", "official",
             0.82, "proposed", 1, None),
            ("journal_tc", "https://journal.example", "الجريدة الرسمية", "official",
             0.91, "proposed", 1, None),
            ("blog_tc", "https://blog.example", "مدونة قانونية", "community",
             0.35, "rejected", 3, "user")]
    for key, url, name, eng, cred, status, tier, decided in srcs:
        cur.execute(
            "INSERT INTO sources (source_key, base_url, name, engine, credibility,"
            " status, discovered_via, discovered_at, decided_at, decided_by,"
            " domain_tier, rejection_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, url, name, eng, cred, status, "seed",
             "2026-09-17T09:00:00", decided and "2026-09-17T09:30:00",
             decided, tier, 0))
    # وثائق تحت المصدرين المعلّقين — لقياس عمود «الوثائق» من documents
    for i, (url, src) in enumerate([("https://tazarr.example/a", "https://tazarr.example"),
                                    ("https://tazarr.example/b", "https://tazarr.example"),
                                    ("https://journal.example/c", "https://journal.example")], 1):
        cur.execute("INSERT INTO documents (doc_id, title, source_url,"
                    " doc_type, status, scraped_at) VALUES (?,?,?,?,?,?)",
                    (f"sha256:s{i}", f"وثيقة {i}", url, "تشريع", "active",
                     "2026-09-17T09:10:00"))
    tasks = [("https://tazarr.example/x1", "failed", 2, "http_404"),
             ("https://tazarr.example/x2", "failed", 3, "timeout"),
             ("https://journal.example/y1", "blocked", 1, "robots"),
             ("https://blog.example/z1", "queued", 0, None),
             ("https://blog.example/z2", "success", 1, None)]
    for url, status, attempts, err in tasks:
        cur.execute("INSERT INTO crawl_tasks (url, section, kind, status, attempts,"
                    " last_error, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (url, "عام", "page", status, attempts, err,
                     "2026-09-17T09:00:00", "2026-09-17T09:05:00"))
    conn.commit()
    yield db
    conn.close()


def _q(conn, sql, params=()):
    return [tuple(r) for r in conn.execute(sql, params)]


# ───────────────────────────────────────────────── 1) طبقة البيانات الحية
def test_source_rows_live_fields_and_doc_counts(src_db):
    from app import core_data as md
    rows = md.source_rows()
    assert len(rows) == 3, f"توقعنا 3 مصادر، لا {len(rows)}"
    by_name = {r["name"]: r for r in rows}
    assert by_name["موقع التشريع"]["docs"] == 2
    assert by_name["الجريدة الرسمية"]["docs"] == 1
    assert by_name["مدونة قانونية"]["status"] == "rejected"
    # المعلّق أولاً: الشاشة يجب أن تفتتح بما يُطلب من المالك، لا بما انتهى
    assert rows[0]["status"] == "proposed"


def test_source_rows_filters_status_and_needle(src_db):
    from app import core_data as md
    assert [r["name"] for r in md.source_rows(status="proposed")] == \
        ["موقع التشريع", "الجريدة الرسمية"]
    assert [r["name"] for r in md.source_rows(needle="الجريدة")] == ["الجريدة الرسمية"]
    assert md.source_rows(status="approved") == []


def test_sources_stats_are_measured_not_assumed(src_db):
    from app import core_data as md
    st = md.sources_stats()
    assert st == {"total": 3, "proposed": 2, "approved": 0, "rejected": 1}


def test_decide_sources_writes_the_same_line_as_cli(src_db):
    """القرار عبر `discovery.decide_source` — بما فيها `decided_by='ui'`."""
    from app import core_data as md
    ids = [r["id"] for r in md.source_rows(needle="tazarr")]
    res = md.decide_sources(ids, True)
    assert res["changed"] == 1 and res["missing"] == []
    with sqlite3.connect(src_db) as conn:
        row = conn.execute("SELECT status, decided_by, decided_at FROM sources"
                           " WHERE source_key='tazarr_tc'").fetchone()
    assert row[0] == "approved" and row[1] == "ui" and row[2]
    # صار مرئياً لـ«ما يُسمح بالزحف منه» — أي أن القرار فتح الباب فعلياً
    # APPROVED_SOURCES نصوص «النطاق — الاسم» جاهزة للعرض
    assert any("tazarr.example" in line for line in md.APPROVED_SOURCES)


def test_decide_sources_reject_keeps_history_and_reports_missing(src_db):
    from app import core_data as md
    target = md.source_rows(needle="الجريدة")[0]["id"]
    res = md.decide_sources([target, 9999], False)
    assert res["changed"] == 1 and res["missing"] == [9999]
    with sqlite3.connect(src_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        st = conn.execute("SELECT status FROM sources WHERE id=?",
                          (target,)).fetchone()[0]
    assert st == "rejected"
    assert n == 3, "الرفض قرار، لا حذف — الصف يجب أن يبقى للمراجعة"


def test_decide_sources_empty_selection_is_error_not_silence(src_db):
    from app import core_data as md
    res = md.decide_sources([], True)
    assert res["changed"] == 0 and res["error"]


def test_queue_counts_and_preview(src_db):
    from app import core_data as md
    q = md.queue_counts()
    assert q["failed"] == 2 and q["blocked"] == 1
    assert q["queued"] == 1 and q["success"] == 1
    pre = md.preview_requeue(("failed", "blocked"))
    assert pre["total"] == 3 and pre["by_status"] == {"failed": 2, "blocked": 1}
    assert md.preview_requeue(("failed",), contains="journal")["total"] == 0


def test_preview_requeue_does_not_write(src_db):
    """المعاينة تعِدّ فقط — لولا هذا الاختبار لكان «زر المعاينة» يفعل الفعل."""
    from app import core_data as md
    before = None
    with sqlite3.connect(src_db) as conn:
        before = _q(conn, "SELECT id, status, attempts FROM crawl_tasks ORDER BY id")
        md.preview_requeue(("failed", "blocked"))
        after = _q(conn, "SELECT id, status, attempts FROM crawl_tasks ORDER BY id")
    assert before == after


def test_requeue_failed_moves_and_resets(src_db):
    from app import core_data as md
    res = md.requeue_failed(("failed", "blocked"))
    assert res["revived"] == 3
    with sqlite3.connect(src_db) as conn:
        rows = dict(conn.execute("SELECT url, status FROM crawl_tasks").fetchall())
        attempts = dict(conn.execute("SELECT url, attempts FROM crawl_tasks").fetchall())
    assert rows["https://tazarr.example/x1"] == "queued"
    assert rows["https://journal.example/y1"] == "queued"
    assert attempts["https://tazarr.example/x2"] == 0, "تصفير المحاولات جزء من الإعادة"
    assert rows["https://blog.example/z2"] == "success", "النجاح لا يُمسّ"


def test_requeue_limit_requeues_oldest_only(src_db):
    """حدّ اختياري: «كل الفاشل» قرار، والمفتاح يحمي من خطأ إدخال جماعي."""
    from app import core_data as md
    res = md.requeue_failed(("failed", "blocked"), limit=1)
    assert res["revived"] == 1 and res["limited_to"] == 1
    with sqlite3.connect(src_db) as conn:
        st = dict(conn.execute("SELECT url, status FROM crawl_tasks").fetchall())
    assert st["https://tazarr.example/x1"] == "queued"
    assert st["https://tazarr.example/x2"] == "failed"
    assert st["https://journal.example/y1"] == "blocked"


def test_requeue_without_database_reports_error_not_traceback(tmp_path, monkeypatch):
    import config
    from app import core_data as md
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "nope.db")
    assert md.requeue_failed()["revived"] == 0
    assert md.requeue_failed()["error"]
    assert md.preview_requeue()["total"] == 0
    assert md.source_rows() == [] and md.sources_stats()["total"] == 0


# ───────────────────────────────────────────────── 2) المعبر الواحد
def test_run_autopilot_forwards_stop_event_and_dry_run(src_db, monkeypatch):
    """الشاشة يجب أن تمرّر عبر run_autopilot — والدالة تمرّر للزاحف."""
    import autopilot
    import crawler
    seen = {}

    def fake_disc(conn, **kw):
        seen["discovery"] = kw
        return {"evaluated": 0, "approved": 0}

    def fake_crawl(**kw):
        seen["crawl"] = kw
        return None

    monkeypatch.setattr(autopilot, "run_discovery", fake_disc)
    monkeypatch.setattr(crawler, "start_crawling", fake_crawl)
    from threading import Event
    ev = Event()
    stats = autopilot.run_autopilot(pages=7, use_search=False,
                                    auto_approve=False, stop_event=ev,
                                    dry_run=True)
    assert stats == {"evaluated": 0, "approved": 0}
    assert seen["crawl"]["dry_run"] is True
    assert seen["crawl"]["stop_event"] is ev
    assert seen["crawl"]["max_pages"] == 7
    assert seen["discovery"]["auto_approve"] is False


def test_run_autopilot_crawl_false_skips_crawler(src_db, monkeypatch):
    import autopilot
    import crawler

    def boom(**kw):  # noqa: ANN001
        raise AssertionError("start_crawling استُدعي مع crawl=False")

    monkeypatch.setattr(autopilot, "run_discovery", lambda conn, **kw: {})
    monkeypatch.setattr(crawler, "start_crawling", boom)
    assert autopilot.run_autopilot(pages=5, crawl=False) == {}


# ───────────────────────────────────────────────── 3) الشاشة الرابعة
def test_sources_page_lists_and_filters(src_db, app):
    from app.pages.sources_page import SourcesPage
    pg = SourcesPage()
    try:
        pg.refresh()
        assert pg.model.rowCount() == 3
        assert pg.model.data(pg.model.index(0, 0)) == "معلّق"
        assert pg.model.data(pg.model.index(0, 4)) == "2"      # الوثائق
        assert pg.model.data(pg.model.index(0, 5)) == "0.82"   # الجدارة
        pg.filter.setCurrentText("مرفوض")
        assert pg.model.rowCount() == 1
        assert pg.model.source_id(0) is not None
        pg.search.setText("لا-يوجد-كذلك")
        assert pg.model.rowCount() == 0
        assert "لا مصدر بهذه الحالة/البحث" in pg.note.text()
    finally:
        pg._timer.stop(); pg.deleteLater()


def test_sources_page_note_has_no_raw_markdown(src_db, app):
    """`**bold**` نصّ خام في QLabel — علة مرئية في لقطة الشاشة."""
    from app.pages.sources_page import SourcesPage
    pg = SourcesPage()
    try:
        pg.refresh()
        assert "**" not in pg.note.text()
    finally:
        pg._timer.stop(); pg.deleteLater()


def test_sources_page_approve_selected_writes_decision(src_db, app, dialogs):
    from app.pages import sources_page as sp
    pg = sp.SourcesPage()
    try:
        pg.refresh()
        assert pg.model.rowCount() == 3
        pg.view.selectionModel().select(
            pg.model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows)
        assert pg._selected_ids(), "لم يُسجَّل أي تحديد — الاختبار بلا معنى"
        pg._decide(True)
        assert pg.model.source_id(0) is not None
        with sqlite3.connect(src_db) as conn:
            st = conn.execute("SELECT status, decided_by FROM sources"
                              " ORDER BY id LIMIT 1").fetchone()
        assert st == ("approved", "ui")
        assert "1" in pg.note.text()
        assert not dialogs["information"], "حوار «لا تحديد» في غير موضعه"
    finally:
        pg._timer.stop(); pg.deleteLater()


def test_selection_semantics_are_as_measured_not_as_assumed(src_db, app, dialogs):
    """قياس سلوك Qt الحرفي — ثم حارس أن شاشة القرار لا تفتعله.

    المقيس (PySide6 6.11، offscreen):
      · `setCurrentIndex(i)` وحده يجعل الصفّ i محدَّداً (سلوك SelectRows)؛
      · `clearSelection()` يترك التحديد فارغاً **والمؤشر صالحاً** — وهي حالة
        Ctrl+click الحقيقية؛ وعلى الرغم من ذلك يرفض الزرّ الكتابة.
    الحارس مطلوب لأن السلوكين متعاكسان ظاهرياً، ولو بُني «احتياط الصفّ
    الجاري» على أحدهما لانقلب إلى تنفيذ قرار على صفّ أزاحه المستعمل عمداً.
    """
    from app.pages import sources_page as sp
    from PySide6.QtCore import QItemSelectionModel
    pg = sp.SourcesPage()
    try:
        pg.refresh()
        pg.view.setCurrentIndex(pg.model.index(1, 0))
        assert pg.view.selectionModel().selectedRows(), \
            "تغيّر سلوك SelectRows — راجع افتراضات الزرّ في sources_page"
        pg.view.selectionModel().select(
            pg.model.index(1, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows)
        assert pg._selected_ids()
        pg.view.selectionModel().clearSelection()
        assert not pg._selected_ids()
        assert pg.view.currentIndex().isValid(), "المؤشر بقي — هذا هو الخطر"
        pg._decide(True)
        assert dialogs["information"][0][0] == "لا تحديد"
        with sqlite3.connect(src_db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM sources"
                             " WHERE status='approved'").fetchone()[0]
        assert n == 0, "رُفض بلا تحديد ⇒ لا كتابة إطلاقاً"
    finally:
        pg._timer.stop(); pg.deleteLater()


def test_sources_page_cancel_changes_nothing(src_db, app, dialogs_no):
    from app.pages import sources_page as sp
    pg = sp.SourcesPage()
    try:
        pg.refresh()
        pg.view.selectionModel().select(
            pg.model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows)
        pg._decide(True)
        with sqlite3.connect(src_db) as conn:
            st = conn.execute("SELECT status FROM sources ORDER BY id LIMIT 1").fetchone()[0]
        assert st == "proposed", "أُلغي — يجب ألا يلمس الإلغاء القاعدة"
        assert "أُلغي" in pg.note.text()
    finally:
        pg._timer.stop(); pg.deleteLater()


def test_sources_page_no_selection_is_informative_not_dead(src_db, app, dialogs):
    from app.pages import sources_page as sp
    from PySide6.QtCore import QModelIndex
    pg = sp.SourcesPage()
    try:
        pg.refresh()
        pg.view.setCurrentIndex(QModelIndex())      # لا مؤشر ولا تحديد
        pg._decide(True)
        assert dialogs["information"], "بلا تحديد ولا رسالة = زرّ ميت"
        assert dialogs["information"][0][0] == "لا تحديد"
        assert "ظلّل" in dialogs["information"][0][1]
    finally:
        pg._timer.stop(); pg.deleteLater()


# ───────────────────────────────────────────────── 4) زرّ الإعادة والمفتاح
def test_reports_tab_shows_measurable_queue_line(src_db, app):
    from app.pages.review_page import ReviewPage
    pg = ReviewPage()
    try:
        pg.refresh()
        txt = pg.requeue_note.text()
        assert "3" in txt, f"المعاينة لم تُظهر العدّ المقيس: {txt!r}"
        assert "failed: 2" in txt and "blocked: 1" in txt
    finally:
        pg.deleteLater()


def test_reports_tab_requeue_confirmed_moves_queue(src_db, app, dialogs):
    from app.pages import review_page as rp
    pg = rp.ReviewPage()
    try:
        pg._requeue_failed()
        with sqlite3.connect(src_db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM crawl_tasks"
                             " WHERE status='queued'").fetchone()[0]
        assert n == 4, f"3 معادة + 1 كانت منتظرة = 4، لا {n}"
        assert "أُعيد 3" in pg.requeue_note.text()
    finally:
        pg.deleteLater()


def test_reports_tab_requeue_cancelled_is_silent_write(src_db, app, dialogs_no):
    from app.pages import review_page as rp
    pg = rp.ReviewPage()
    try:
        pg._requeue_failed()
        with sqlite3.connect(src_db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM crawl_tasks"
                             " WHERE status='failed'").fetchone()[0]
        assert n == 2 and "أُلغيت الإعادة" in pg.requeue_note.text()
    finally:
        pg.deleteLater()


def test_home_dry_run_default_off_and_forwarded(src_db, app, monkeypatch):
    """الوضع التجريبي مطفأ افتراضياً (الافتراضي الآمن)، ومفتوحاً يصل للزاحف."""
    import autopilot
    from app.pages.home_page import HomePage, _AutopilotWorker

    hp = HomePage()
    try:
        assert hp.dry_box.isChecked() is False
        assert hp.dry_box.text().startswith("تجريبي")
        assert hp.sources_btn.text().strip() != ""
    finally:
        hp._timer.stop(); hp.deleteLater()

    seen = {}
    monkeypatch.setattr(autopilot, "run_autopilot",
                        lambda **kw: seen.update(kw) or {"ok": True})
    from threading import Event
    ev = Event()
    w = _AutopilotWorker(11, ev, auto_approve=False, use_search=False,
                         dry_run=True)
    w.run()
    assert seen["dry_run"] is True
    assert seen["stop_event"] is ev
    assert seen["pages"] == 11
    assert seen["use_search"] is False and seen["auto_approve"] is False


# ───────────────────────────────────────────────── 5) الربط ومنع الانجراف
def test_home_button_shows_pending_source_count(src_db, app):
    """«2 مصدر معلّق» على الزرّ لا على إحساس — هي العلة الأصلية للدفعات."""
    from app.pages.home_page import HomePage
    hp = HomePage()
    try:
        hp.refresh()
        assert "2" in hp.sources_btn.text() and "المصادر" in hp.sources_btn.text()
        with sqlite3.connect(src_db) as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM sources WHERE status='proposed'")]
        from app import core_data as md
        md.decide_sources(ids, True)
        hp.refresh()
        assert hp.sources_btn.text().strip() == "المصادر  ◀", \
            f"لم يُصفَّر العدّاد بعد الاعتماد: {hp.sources_btn.text()!r}"
    finally:
        hp._timer.stop(); hp.deleteLater()


def test_main_window_has_four_pages_and_goto_reaches_sources(src_db, app):
    from app.main import MainWindow
    from app.pages.sources_page import SourcesPage
    win = MainWindow()
    try:
        assert win.stack.count() == 4, f"شاشات النافذة {win.stack.count()}"
        win._open_sources()
        assert isinstance(win.stack.currentWidget(), SourcesPage)
        win.goto(3)
        assert type(win.stack.currentWidget()).__name__ == "PackagePage"
    finally:
        win.deleteLater()


def test_render_screens_names_match_window(src_db):
    """لقطة لا تُلتقط لشاشة غير مربوطة = شاشة وهم. الحارس يمنع الانفصال."""
    from app.render_screens import NAMES
    assert len(NAMES) == 4
    assert NAMES == ["01-home", "02-sources", "03-review", "04-package"]
    for n in NAMES:
        assert n[:2].isdigit()
    assert len(set(NAMES)) == len(NAMES)


def test_new_files_have_no_cjk_contamination():
    """حرف صيني/ياباني يتسلل إلى النص العربي — قِيس مراراً؛ هنا حارس دائم."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ("app/pages/sources_page.py", "app/core_data.py",
                "app/pages/home_page.py", "app/pages/review_page.py",
                "app/main.py", "autopilot.py", "README.md",
                "app/render_screens.py", "DELIVERY/UI-3-HARVESTER-UI.md"):
        txt = (root / rel).read_text(encoding="utf-8")
        bad = NEEDLE_RE.findall(txt)
        assert not bad, f"{rel}: أحرف غير عربية تسللت: {sorted(set(bad))[:5]}"
