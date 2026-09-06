# -*- coding: utf-8 -*-
"""شاشة «البداية» — التصميم المطلوب من المالك (2026-09-06): 3 أزرار فقط.

  [ابدأ الزحف]  [إيقاف]  [نتائج الزحف]

بالضغط «ابدأ الزحف»: الأداة تكتشف مصادرها بنفسها تلقائياً (autopilot.py)
ثم تزحف وتحمّل كل ما له علاقة بالقانون السوري من المصدر المكتشف — بلا
أي اختيار مسبق من المستخدم (لا قائمة مصدر، لا صناديق أقسام؛ الاكتشاف
والتصنيف تلقائيان بالكامل). زر «نتائج الزحف» يتفعّل فقط بعد انتهاء
الزحف، وبالضغط عليه تُفتح شاشة المراجعة (ReviewPage) بكل ما جُمع.
"""
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from app import core_data as md
from ._common import Collapsible, card, page_header

DEFAULT_MAX_PAGES = 60


def _stat(value: str, label: str) -> QWidget:
    c, v = card()
    val = QLabel(value); val.setProperty("class", "statValue")
    lab = QLabel(label); lab.setProperty("class", "statLabel")
    val.setAlignment(Qt.AlignCenter); lab.setAlignment(Qt.AlignCenter)
    v.addWidget(val); v.addWidget(lab)
    return c


class _AutopilotWorker(QThread):
    """اكتشاف تلقائي كامل ثم زحف — نفس autopilot.run_autopilot المستخدم
    بأمر `cli autopilot`، خارج خيط الواجهة كي لا تتجمد النافذة."""
    finished_run = Signal(dict)

    def __init__(self, max_pages, stop_event, parent=None):
        super().__init__(parent)
        self.max_pages = max_pages
        self.stop_event = stop_event

    def run(self):
        stats = {}
        try:
            from database import create_tables, get_connection
            from autopilot import run_discovery
            create_tables()
            conn = get_connection()
            try:
                stats = run_discovery(conn, auto_approve=True,
                                      use_search=True, max_evaluate=12)
            finally:
                conn.close()
            if not self.stop_event.is_set():
                from crawler import start_crawling
                start_crawling(max_pages=self.max_pages,
                               stop_event=self.stop_event)
        except Exception as exc:  # noqa: BLE001 — الواجهة تعرض ولا تنهار
            stats["error"] = str(exc)
        finally:
            self.finished_run.emit(stats)


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.stop_event = threading.Event()
        self.on_open_results = None  # MainWindow يربطها بالانتقال لشاشة المراجعة
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(page_header(
            "البداية",
            "الأداة تكتشف مصادرها بنفسها وتجمع كل ما له علاقة بالقانون "
            "السوري تلقائياً — قوانين، قرارات، اجتهادات"))

        main_card, mv = card()
        self.status_label = QLabel("جاهزة — اضغط «ابدأ الزحف»")
        self.status_label.setProperty("class", "hint")
        mv.addWidget(self.status_label)

        btn_row = QHBoxLayout(); btn_row.setSpacing(12)
        self.start_btn = QPushButton("▶  ابدأ الزحف")
        self.start_btn.setProperty("class", "primary")
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.clicked.connect(self._start_run)

        self.stop_btn = QPushButton("■  إيقاف")
        self.stop_btn.setProperty("class", "ghost")
        self.stop_btn.setMinimumHeight(52)
        self.stop_btn.clicked.connect(self._request_stop)
        self.stop_btn.setEnabled(False)

        self.results_btn = QPushButton("نتائج الزحف  ◀")
        self.results_btn.setProperty("class", "gold")
        self.results_btn.setMinimumHeight(52)
        self.results_btn.setEnabled(False)
        self.results_btn.clicked.connect(self._open_results)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.results_btn)
        mv.addLayout(btn_row)
        root.addWidget(main_card)

        adv = Collapsible("خيارات متقدّمة (حد الصفحات فقط)")
        limits_row = QHBoxLayout(); limits_row.setSpacing(12)
        limits_row.addWidget(QLabel("أقصى عدد صفحات بكل دورة زحف:"))
        from PySide6.QtWidgets import QSpinBox
        self.spin = QSpinBox(); self.spin.setRange(5, 5000)
        self.spin.setValue(DEFAULT_MAX_PAGES)
        limits_row.addWidget(self.spin)
        limits_row.addStretch()
        adv.addLayout(limits_row)
        root.addWidget(adv)

        self.stats_row = QHBoxLayout(); self.stats_row.setSpacing(16)
        root.addLayout(self.stats_row)

        prog_card, pv = card()
        top = QHBoxLayout()
        t = QLabel("تقدّم الطابور الدائم"); t.setProperty("class", "cardTitle")
        self.pct = QLabel("—"); self.pct.setProperty("class", "cardTitle")
        top.addWidget(t); top.addStretch(); top.addWidget(self.pct)
        pv.addLayout(top)
        self.bar = QProgressBar(); self.bar.setRange(0, 100)
        self.bar.setValue(0); self.bar.setTextVisible(False)
        self.bar.setMinimumHeight(18)
        pv.addWidget(self.bar)
        root.addWidget(prog_card)

        log_section = Collapsible("سجل الأحداث التفصيلي")
        self.log = QPlainTextEdit(); self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)
        log_section.addWidget(self.log)
        root.addWidget(log_section, 1)
        root.addStretch()

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(4000)

    def refresh(self):
        s = md.RUN_STATS or {}
        q = s.get("queue", {})
        done = q.get("success", 0) + q.get("blocked", 0) + q.get("failed", 0)
        total = done + q.get("queued", 0) + q.get("running", 0)
        while self.stats_row.count():
            it = self.stats_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for val, lab in [(str(done), "مهام منجزة"),
                         (str(q.get("queued", 0)), "في الطابور"),
                         (str(s.get("docs", 0)), "وثائق محفوظة"),
                         (str(s.get("articles", 0)), "مواد مستخرجة"),
                         (str(q.get("needs_review", 0)), "تحتاج مراجعة")]:
            self.stats_row.addWidget(_stat(val, lab))
        pct = int(100 * done / total) if total else 0
        self.bar.setValue(pct)
        self.pct.setText(f"{pct}% من {total} مهمة")
        self._reload_log()
        needs_review = q.get("needs_review", 0)
        if not (self.worker and self.worker.isRunning()):
            self.results_btn.setEnabled(bool(done or s.get("docs", 0)))
            if needs_review:
                self.results_btn.setText(f"نتائج الزحف ({needs_review} تحتاج مراجعة)  ◀")
            else:
                self.results_btn.setText("نتائج الزحف  ◀")

    def _reload_log(self):
        pos = self.log.verticalScrollBar().value()
        at_bottom = pos >= self.log.verticalScrollBar().maximum() - 24
        self.log.clear()
        for ts, tag, msg, _ in md.LOG_EVENTS[-400:]:
            self.log.appendPlainText(f"[{ts}] [{tag:8s}] {msg}")
        if at_bottom:
            self.log.verticalScrollBar().setValue(
                self.log.verticalScrollBar().maximum())

    def _start_run(self):
        if self.worker and self.worker.isRunning():
            return
        self.stop_event = threading.Event()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.results_btn.setEnabled(False)
        self.status_label.setText(
            "🤖 جارٍ اكتشاف المصادر والزحف تلقائياً — قد يستغرق دقائق…")
        self.worker = _AutopilotWorker(self.spin.value(), self.stop_event,
                                       parent=self)
        self.worker.finished_run.connect(self._run_finished)
        self.worker.start()

    def _request_stop(self):
        self.stop_event.set()
        self.stop_btn.setEnabled(False)
        self.status_label.setText("⏹ طُلب الإيقاف — ستُغلق الدورة الحالية بأمان…")

    def _run_finished(self, stats: dict):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if stats.get("error"):
            self.status_label.setText(f"⚠️ تعطل التشغيل: {stats['error']}")
        else:
            self.status_label.setText(
                "✓ انتهت الدورة — اضغط «نتائج الزحف» لمراجعة ما جُمع")
        self.refresh()

    def _open_results(self):
        if self.on_open_results:
            self.on_open_results()
