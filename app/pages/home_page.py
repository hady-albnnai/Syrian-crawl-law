# -*- coding: utf-8 -*-
"""الشاشة الرئيسية — البداية: فعل واحد رئيسي «ابدأ الزحف الآن».

دمج شاشتَي «تحديد النطاق» و«التشغيل» السابقتين في شاشة واحدة، تطبيقاً
لأفضل ممارسات تصميم الواجهات (Microsoft UX Guide، Progressive Disclosure):
  - قرار رئيسي واحد لكل شاشة، لا تنقّل بين شاشتين لعمل مهمة واحدة مترابطة.
  - إعدادات افتراضية معقولة تعمل فوراً بلا أي ضبط من المستخدم.
  - التفاصيل النادر تعديلها (حد الصفحات، وضع التجربة) خلف طيّة واحدة.

تصحيح صدق (2026-09-06): أُزيلت من هذه الشاشة عناصر كانت معروضة كأنها
تتحكم بسلوك الزحف بينما لا أثر فعلي لها بالكود — تضليل بصري لمستخدم
غير تقني، اكتُشف بتجربة فعلية للأداة:
  - قائمة اختيار «مصدر» — لا شيء يقرأ اختيار المستخدم منها؛ الزاحف
    يكتشف مصادره وأقسامه بنفسه تلقائياً (crawler.start_crawling +
    الطيار الآلي)، فلا معنى لعرض اختيار وهمي.
  - صناديق اختيار «الأقسام» — نفس المشكلة، بلا أي تأثير على ما يُجمع.
  - وضعا «محدود» و«كامل» — كانا يبدوان خيارين مختلفين وهما فعلياً نفس
    السلوك بالكود (كلاهما dry_run=False) — استُبدلا بمفتاح واحد صادق:
    «تجريبي (بلا حفظ)» تشغّل/تشغّل، لأنه الفارق الحقيقي الوحيد المبرمج.

يستخدم نفس app.run_state.SETTINGS ونفس crawler.start_crawling الحقيقيَّين.
"""
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from app import core_data as md
from app.run_state import SETTINGS
from ._common import Collapsible, card, page_header


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

    def __init__(self, stop_event, max_pages, dry_run, parent=None):
        super().__init__(parent)
        self.stop_event = stop_event
        self.max_pages = max_pages
        self.dry_run = dry_run

    def run(self):
        from crawler import start_crawling
        try:
            start_crawling(max_pages=self.max_pages, dry_run=self.dry_run,
                           stop_event=self.stop_event)
        finally:
            self.finished_run.emit()


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.stop_event = threading.Event()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(page_header(
            "البداية",
            "اضغط زراً واحداً لبدء جمع التشريعات — الأداة تكتشف مصادرها وأقسامها بنفسها"))

        # ── بطاقة التشغيل الرئيسية: فعل واحد بارز ──
        main_card, mv = card()
        self.settings_label = QLabel("")
        self.settings_label.setProperty("class", "hint")
        mv.addWidget(self.settings_label)

        launch_row = QHBoxLayout()
        self.resume = QPushButton("")
        self.resume.setProperty("class", "primary")
        self.resume.setMinimumHeight(52)
        self.resume.setMinimumWidth(260)
        self.resume.clicked.connect(self._start_run)
        self.stop = QPushButton("■  إيقاف")
        self.stop.setProperty("class", "ghost")
        self.stop.clicked.connect(self._request_stop)
        self.stop.setEnabled(False)
        launch_row.addWidget(self.resume)
        launch_row.addWidget(self.stop)
        launch_row.addStretch()
        mv.addLayout(launch_row)
        root.addWidget(main_card)

        # ── خيارات متقدّمة (مطوية افتراضياً) — فقط ما له أثر فعلي بالكود ──
        adv = Collapsible("خيارات متقدّمة (حد الصفحات، وضع التجربة)")

        limits_row = QHBoxLayout(); limits_row.setSpacing(18)
        limits_row.addWidget(QLabel("أقصى عدد صفحات بكل دورة:"))
        self.spin = QSpinBox(); self.spin.setRange(5, 5000)
        self.spin.setValue(SETTINGS.max_pages)
        limits_row.addWidget(self.spin)
        limits_row.addStretch()
        adv.addLayout(limits_row)

        self.dry_box = QCheckBox("وضع تجريبي — يفحص فقط بلا حفظ أي شيء بالقاعدة")
        self.dry_box.setChecked(SETTINGS.dry_run)
        adv.addWidget(self.dry_box)

        src_hint = QLabel("المصدر والأقسام تُكتشف تلقائياً — لا حاجة لاختيارها؛ "
                          "لإضافة مصدر جديد يدوياً استخدم «متقدّم ← استكشاف المصادر»")
        src_hint.setProperty("class", "hint")
        adv.addWidget(src_hint)

        apply_row = QHBoxLayout()
        apply_btn = QPushButton("حفظ الخيارات"); apply_btn.setProperty("class", "ghost")
        apply_btn.clicked.connect(self._apply_settings)
        apply_row.addStretch(); apply_row.addWidget(apply_btn)
        adv.addLayout(apply_row)
        root.addWidget(adv)

        # ── حالة التشغيل الحية ──
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

    def _apply_settings(self):
        SETTINGS.max_pages = self.spin.value()
        SETTINGS.dry_run = self.dry_box.isChecked()
        self._sync_settings_label()

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
        self._sync_settings_label()

    def _sync_settings_label(self):
        mode_ar = "تجريبي (بلا حفظ)" if SETTINGS.dry_run else "فعلي (يحفظ بالقاعدة)"
        self.settings_label.setText(
            f"الإعدادات النشطة: {SETTINGS.max_pages} صفحة — وضع {mode_ar} — "
            "يمكن إغلاق الأداة واستئنافها دون تكرار وثيقة أو مادة")
        if not (self.worker and self.worker.isRunning()):
            self.resume.setText(f"▶  ابدأ الزحف الآن ({SETTINGS.max_pages} صفحة)")

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
        self._apply_settings()
        self.stop_event = threading.Event()
        self.resume.setEnabled(False)
        self.stop.setEnabled(True)
        self.worker = _CrawlWorker(self.stop_event, SETTINGS.max_pages,
                                   dry_run=SETTINGS.dry_run, parent=self)
        self.worker.finished_run.connect(self._run_finished)
        self.worker.start()

    def _request_stop(self):
        self.stop_event.set()
        self.stop.setEnabled(False)

    def _run_finished(self):
        self.resume.setEnabled(True)
        self.stop.setEnabled(False)
        self.refresh()
