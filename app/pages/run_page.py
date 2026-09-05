# -*- coding: utf-8 -*-
"""الشاشة 2 — التشغيل: إحصاءات حية من الطابور + تشغيل/إيقاف فعلي.

الزحف يعمل في QThread (لا تجميد للواجهة)، والإيقاف تعاوني عبر
stop_event يفحصه الزاحف بين مهمة وأخرى — الطابور دائم فالاستئناف آمن.
"""
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header


def _stat(value: str, label: str) -> QWidget:
    c, v = card()
    val = QLabel(value); val.setProperty("class", "statValue")
    lab = QLabel(label); lab.setProperty("class", "statLabel")
    val.setAlignment(Qt.AlignCenter); lab.setAlignment(Qt.AlignCenter)
    v.addWidget(val); v.addWidget(lab)
    return c


class _CrawlWorker(QThread):
    """يشغّل دورة زحف حقيقية خارج خيط الواجهة."""
    finished_run = Signal()

    def __init__(self, stop_event, max_pages, parent=None):
        super().__init__(parent)
        self.stop_event = stop_event
        self.max_pages = max_pages

    def run(self):
        from crawler import start_crawling
        try:
            start_crawling(max_pages=self.max_pages, dry_run=False,
                           stop_event=self.stop_event)
        finally:
            self.finished_run.emit()


class RunPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.stop_event = threading.Event()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("التشغيل", "الطابور دائم — يمكن إغلاق الأداة واستئنافها دون تكرار وثيقة أو مادة"))

        self.stats_row = QHBoxLayout(); self.stats_row.setSpacing(16)
        root.addLayout(self.stats_row)

        prog_card, pv = card()
        top = QHBoxLayout()
        t = QLabel("الطابور الدائم"); t.setProperty("class", "cardTitle")
        self.pct = QLabel("—"); self.pct.setProperty("class", "cardTitle")
        top.addWidget(t); top.addStretch(); top.addWidget(self.pct)
        pv.addLayout(top)
        self.bar = QProgressBar(); self.bar.setRange(0, 100)
        self.bar.setValue(0); self.bar.setTextVisible(False)
        self.bar.setMinimumHeight(18)
        pv.addWidget(self.bar)
        root.addWidget(prog_card)

        log_card, lv = card("سجل الأحداث (crawl_log)")
        self.log = QPlainTextEdit(); self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        lv.addWidget(self.log)
        root.addWidget(log_card, 1)

        btns = QHBoxLayout()
        self.stop = QPushButton("■  إيقاف"); self.stop.setProperty("class", "ghost")
        self.stop.clicked.connect(self._request_stop)
        self.stop.setEnabled(False)
        self.resume = QPushButton("▶  تشغيل دورة (25 صفحة)")
        self.resume.setProperty("class", "primary")
        self.resume.clicked.connect(self._start_run)
        btns.addWidget(self.stop); btns.addStretch(); btns.addWidget(self.resume)
        root.addLayout(btns)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(4000)  # تحديث دوري أثناء التشغيل

    def refresh(self):
        s = md.RUN_STATS or {}
        q = s.get("queue", {})
        done = q.get("success", 0) + q.get("blocked", 0) + q.get("failed", 0)
        total = done + q.get("queued", 0) + q.get("running", 0)
        # إعادة بناء بطاقات الإحصاء
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
        self.resume.setEnabled(False)
        self.stop.setEnabled(True)
        self.worker = _CrawlWorker(self.stop_event, 25, self)
        self.worker.finished_run.connect(self._run_finished)
        self.worker.start()

    def _request_stop(self):
        self.stop_event.set()
        self.stop.setEnabled(False)

    def _run_finished(self):
        self.resume.setEnabled(True)
        self.stop.setEnabled(False)
        self.refresh()
