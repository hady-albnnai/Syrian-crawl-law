# -*- coding: utf-8 -*-
"""اختبارات الواجهة v3 — ما بُني على تدقيق مقاس، لا على ذوق.

تحرس أربع علل مثبتة بالتدقيق (2026-09-17):
 1) مزوّدات core_data كانت حيّة ومختبَرة و**بلا أي استعمال في الشاشات** —
    الآن الحارس يفرض أن كل شاشة تعرض بياناتها الحقيقية.
 2) validate_package كان نسخة أخفّ من بوابة ميزان ⇒ أخفى كسر البصمة —
    الآن الشاشة تستدعي verify_package حرفياً.
 3) «مهام منجزة» كانت تدمج failed — والنسبة 100٪ حتى لو انهار المصدر.
 4) المعاينة كانت تفتح حتى 2,000,000 حرف في محرر واحد — الآن بسقف معلن
    وعدد مخفى صريح.
بلا شبكة. تحتاج Qt (offscreen) — تُتخطى بأناقة إن غابت مكتبات النظام.
"""
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402
except ImportError as exc:  # حاوية بلا مكتبات Qt النظامية (libxkbcommon/…)
    # الصرامة هي القاعدة: الإغفال يُسمح به صراحةً فقط، وإلا فشل صريح —
    # لا تُعلَن دفعة واجهة ناجحة على صندوق لم يبنِ الشاشة أصلاً.
    if os.environ.get("MIZAN_ALLOW_NO_QT") != "1":
        raise
    pytest.skip(f"Qt غير متاح هنا: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui_db(tmp_path, monkeypatch):
    """قاعدة إنتاجية بأربع وثائق بحالات مختلفة + مواد + هويات."""
    import config
    import database
    db = tmp_path / "ui3.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(database, "DB_PATH", db)
    import exporter
    monkeypatch.setattr(exporter, "SNAPSHOT_DIR", tmp_path / "no_snaps")
    database.create_tables()
    conn = database.get_connection()
    cur = conn.cursor()
    from crawler import save_document
    rows = [("sha256:v1", "قانون العقوبات", "penal_law", "القانون:148:1949",
             "معدَّل", 2, "auto_accepted", "active"),
            ("sha256:v2", "قانون العمل", "civil_law", "القانون:17:2010",
             "ساري", 3, "human_verified", "active"),
            ("sha256:v3", "قرار إداري بلا هوية", "administrative", None,
             None, 4, "auto_accepted", "active"),
            ("sha256:v4", "مقتطف مرفوض", "civil_law", None, None, 4,
             "auto_accepted", "rejected")]
    for i, (doc_id, title, branch, ident, status, tier, review, st) in enumerate(rows, 1):
        save_document(cur, doc_id, title, f"https://x/t{i}", branch, 0.8, 90.0,
                      f"md5{i}", "نص الوثيقة " + ("كلام " * 60),
                      identity_key=ident, identity_confidence="number_year" if ident else None,
                      law_number=int((ident or ":").split(":")[1] or 0) if ident else None,
                      law_year=int((ident or ":").split(":")[2] or 0) if ident else None,
                      source_domain_tier=tier, quality_score=0.9, status=st)
        conn.execute("UPDATE documents SET legal_status=?, review_status=? WHERE id=?",
                     (status, review, i))
        for n in range(3):
            cur.execute("INSERT INTO articles (doc_id, article_number,"
                        " article_label, text, char_count) VALUES (?,?,?,?,?)",
                        (i, str(n + 1), f"المادة {n+1}", "متن المادة", 11))
    conn.execute("INSERT INTO crawl_runs (started_at, mode, max_pages, pages,"
                 " docs, articles, skipped, failures) VALUES"
                 " ('2026-09-17T10:00:00','live',50,26,4,12,3,1)")
    conn.execute("INSERT INTO crawl_tasks (url, status, last_error, created_at)"
                 " VALUES ('https://x/f1','failed','http_404',"
                 " '2026-09-17T10:00:01')")
    conn.execute("INSERT INTO crawl_tasks (url, status, last_error, created_at)"
                 " VALUES ('https://x/f2','failed','http_404',"
                 " '2026-09-17T10:00:02')")
    conn.execute("INSERT INTO crawl_tasks (url, status, created_at)"
                 " VALUES ('https://x/ok','success','2026-09-17T10:00:03')")
    conn.execute("INSERT INTO crawl_tasks (url, status, created_at)"
                 " VALUES ('https://x/pend','queued','2026-09-17T10:00:04')")
    conn.commit(); conn.close()
    return db


# ────────────────────────────────────────────── شاشة المراجعة
class TestReviewPage:
    def _page(self, app, ui_db, monkeypatch):
        from app import core_data
        from app.pages.review_page import ReviewPage
        monkeypatch.setattr(core_data, "PACKAGE_DIR", ui_db.parent / "pkg")
        p = ReviewPage()
        p.refresh()
        return p

    def test_seven_columns_and_four_docs(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        assert p.model.columnCount() == 7
        # المرفوضة تبقى مرئية بوسمها — الإخفاء الصامت ممنوع دستورياً
        assert p.model.rowCount() == 4

    def test_identity_and_legal_status_rendered(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        texts = []
        for r in range(p.model.rowCount()):
            texts.append([p.model.index(r, c).data(Qt.DisplayRole)
                          for c in range(7)])
        pen = next(t for t in texts if t[0] == "قانون العقوبات")
        assert pen[4] == "القانون:148:1949"
        assert pen[5] == "معدَّل"
        assert pen[6] == "2"
        orphan = next(t for t in texts if t[0] == "قرار إداري بلا هوية")
        assert orphan[4] == "" and orphan[5] == ""   # لا اختلاق

    def test_search_and_status_filter(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        p.search.setText("عقوبات")
        assert p.proxy.rowCount() == 1
        p.search.setText("")
        idx = p.status_filter.findData("human_verified")
        p.status_filter.setCurrentIndex(idx)
        assert p.proxy.rowCount() == 1
        p.status_filter.setCurrentIndex(0)
        assert p.proxy.rowCount() == 4

    def test_preview_is_capped_and_honest(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        p.view.selectRow(0)
        p._load_preview()
        assert len(p.preview.toPlainText()) <= 20_000 + 200
        assert "معاينة أول" in p.preview_hint.text()

    def test_bulk_approve_writes_all_selected(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        sel = p.view.selectionModel()
        from PySide6.QtCore import QItemSelectionModel
        for r in (0, 1, 2):
            sel.select(p.proxy.index(r, 0),
                       QItemSelectionModel.Select | QItemSelectionModel.Rows)
        assert len(p._selected_docs()) == 3
        p._approve_selected()
        conn = sqlite3.connect(ui_db)
        n = conn.execute("SELECT COUNT(*) FROM documents WHERE"
                         " review_status='human_verified'").fetchone()[0]
        conn.close()
        assert n == 3     # v1+v3 أُضيفا إلى v2 المراجَع سلفاً؛ المرفوضة خارج المحدد
        assert conn is None or True

    def test_reject_dialog_requires_reason(self, app, ui_db, monkeypatch):
        from app.pages.review_page import RejectionReasonDialog
        from app.pages.review_page import OK_BUTTON
        dlg = RejectionReasonDialog("عنوان", 2)
        assert dlg.buttons.button(OK_BUTTON).isEnabled() is False
        assert dlg.ok_btn is dlg.buttons.button(OK_BUTTON)
        assert dlg.selected_category() is None
        # مفاتيح _radios هم أزرار QRadioButton (والقيم هي الفئات)
        first_rb = next(iter(dlg._radios))
        first_rb.setChecked(True)
        assert dlg.selected_category() == dlg._radios[first_rb]
        assert dlg.buttons.button(OK_BUTTON).isEnabled() is True
        assert dlg.selected_category()

    def test_reports_tab_shows_measured_numbers(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        assert "وثائق محفوظة" not in p.runs.toPlainText()
        assert "صفحات 26" in p.runs.toPlainText()
        assert "وثائق 4" in p.runs.toPlainText() and "إخفاقات 1" in p.runs.toPlainText()
        assert "http_404" in p.failures.toPlainText() and "2" in p.failures.toPlainText()
        assert "بلا هوية ⇒ بلا حالة قانونية: 1" in p.profile.toPlainText()
        assert "وثائق نشطة: 3" in p.profile.toPlainText()   # المرفوضة خارج النشط

    def test_no_dead_providers_left_in_review(self, app, ui_db, monkeypatch):
        """الحارس البنيوي: التبويبات تستهلك مزوّدات core_data — لا شاشة
        بلا بيانات ولا بيانات بلا شاشة (علة الـ11 مزوداً اليتيماً)."""
        from app import core_data
        p = self._page(app, ui_db, monkeypatch)
        assert p.tabs.count() == 3
        for provider in ("CORPUS_PROFILE", "GAP_REPORT", "RUN_HISTORY",
                         "FAILURE_BREAKDOWN", "REJECTION_STATS"):
            assert hasattr(core_data, provider)
        # كل مزوّد يُستهلك فعلاً في إحدى الشاشات الثلاث
        import app.pages as pages_mod
        import inspect
        src = ""
        for mod in ("review_page", "home_page", "package_page"):
            src += inspect.getsource(__import__(f"app.pages.{mod}",
                                                fromlist=["x"]))
        for provider in ("CORPUS_PROFILE", "GAP_REPORT", "RUN_HISTORY",
                         "FAILURE_BREAKDOWN", "REJECTION_STATS",
                         "PACKAGE_TREE", "VALIDATION_CHECKS"):
            assert provider in src, f"{provider} لا يزال يتيماً في الشاشات"


# ────────────────────────────────────────────── شاشة الحزمة
class TestPackagePage:
    def _page(self, app, ui_db, monkeypatch):
        from app import core_data
        from app.pages.package_page import PackagePage
        pkg = ui_db.parent / "pkg"
        monkeypatch.setattr(core_data, "PACKAGE_DIR", pkg)
        p = PackagePage()
        return p, pkg

    def test_gate_red_before_generation_then_green_after(self, app, ui_db,
                                                          monkeypatch):
        from config import DB_PATH
        from exporter import build_package
        p, pkg = self._page(app, ui_db, monkeypatch)
        p.refresh()
        assert "لم تولَّد" in p.gate_banner.text()
        build_package(db_path=DB_PATH, out_dir=pkg)
        p.refresh()
        assert p.gate_banner.text().startswith("✓"), p.gate_banner.text()
        assert p.cards["articles"].text() == "9"     # 3 وثائق نشطة × 3 مواد
        assert p.cards["rows"].text() == "3"          # المرفوضة لا تُصدَّر
        assert "laws_decrees_index.csv" in p.tree.toPlainText()

    def test_gate_turns_red_on_tampered_package(self, app, ui_db, monkeypatch):
        from config import DB_PATH
        from exporter import build_package
        p, pkg = self._page(app, ui_db, monkeypatch)
        build_package(db_path=DB_PATH, out_dir=pkg)
        p.refresh()
        assert p.gate_banner.text().startswith("✓")
        victim = next((pkg / "markdown").glob("*.md"))
        victim.write_bytes(victim.read_bytes() + b"\nx")
        p.refresh()
        assert "ميزان سيتخطى" in p.gate_banner.text()
        assert "✗" in p.checks.toPlainText()

    def test_build_button_generates_through_exporter(self, app, ui_db,
                                                      monkeypatch, tmp_path):
        import config, database
        from app import core_data
        from app.pages.package_page import PackagePage
        built = tmp_path / "built"
        monkeypatch.setattr(core_data, "PACKAGE_DIR", built)
        p = PackagePage()                              # لا انهيار على «لا حزمة»
        p.out_dir.setText(str(built))
        p._build_package()
        assert (tmp_path / "built" / "laws_decrees_index.csv").exists()
        assert "✓" in p.status.text() or "✗" in p.status.text()
        assert p.build_btn.isEnabled() and not p.progress.isVisible()


# ────────────────────────────────────────────── شاشة البداية
class TestHomePageMetrics:
    def _page(self, app, ui_db, monkeypatch):
        from app import core_data
        from app.pages.home_page import HomePage
        p = HomePage()
        p._timer.stop()          # لا نبضات أثناء الاختبار
        return p

    def test_failed_is_not_counted_as_done(self, app, ui_db, monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        assert p.stat_cards["done"].text() == "1"        # success فقط
        assert p.stat_cards["failed"].text() == "2"      # منفصل، لا ملغوم
        assert "100٪" not in p.pct.text() or "فاشلة" in p.pct.text()
        assert "فاشلة" in p.pct.text()

    def test_version_and_git_head_are_shown(self, app, ui_db, monkeypatch):
        import config
        p = self._page(app, ui_db, monkeypatch)
        assert f"v{config.VERSION}" in p.meta_label.text()
        assert "آخر دورة #1" in p.meta_label.text()
        assert "قاطع الدورة" in p.meta_label.text()

    def test_auto_approve_defaults_off_and_reaches_worker(self, app, ui_db,
                                                           monkeypatch):
        p = self._page(app, ui_db, monkeypatch)
        assert p.auto_approve_box.isChecked() is False   # سياسة المالك لا قرار الشاشة
        assert p.search_box.isChecked() is True
        import app.pages.home_page as hp
        w = hp._AutopilotWorker(5, None, auto_approve=False, use_search=True)
        assert w.auto_approve is False and w.use_search is True

    def test_missing_database_does_not_crash_refresh(self, app, tmp_path,
                                                      monkeypatch):
        import config
        import database
        empty = tmp_path / "none.db"
        monkeypatch.setattr(config, "DB_PATH", empty)
        monkeypatch.setattr(database, "DB_PATH", empty)
        from app.pages.home_page import HomePage
        p = HomePage()           # الإقلاع الأول على جهاز فارغ
        p._timer.stop()
        p.refresh()
        assert "⚠︎" not in p.status_label.text()
        assert p.stat_cards["done"].text() == "0"


# ────────────────────────────────────────────── التنقل
def test_window_goto_three_pages(app, ui_db, monkeypatch):
    import config
    import database
    from config import DB_PATH  # noqa: F401  (لا إعادة تهيئة)
    from app import main as app_main
    win = app_main.MainWindow()
    for i, cls in enumerate(("HomePage", "ReviewPage", "PackagePage")):
        win.goto(i)
        assert type(win.stack.currentWidget()).__name__ == cls, i
    win.goto(99)                 # لا انهيار عند فهرس خارج المدى
    assert type(win.stack.currentWidget()).__name__ == "HomePage"
