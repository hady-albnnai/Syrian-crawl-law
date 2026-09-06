# -*- coding: utf-8 -*-
"""الشاشة الرئيسية — البداية: فعل واحد رئيسي «ابدأ الزحف الآن».

دمج شاشتَي «تحديد النطاق» و«التشغيل» السابقتين في شاشة واحدة، تطبيقاً
لأفضل ممارسات تصميم الواجهات (Microsoft UX Guide، Progressive Disclosure):
  - قرار رئيسي واحد لكل شاشة، لا تنقّل بين شاشتين لعمل مهمة واحدة مترابطة.
  - إعدادات افتراضية معقولة تعمل فوراً بلا أي ضبط من المستخدم.
  - التفاصيل النادر تعديلها (المصدر، عدد الصفحات، الوضع، الأقسام) تُخفى
    خلف قسم واحد قابل للطي «خيارات متقدّمة» — تظهر فقط لمن يطلبها.

يستخدم نفس app.run_state.SETTINGS ونفس crawler.start_crawling الحقيقيَّين
دون أي تغيير في المنطق — إعادة تنظيم عرض فقط.
"""
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QLabel, QPlainTextEdit, QProgressBar,
                               QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from app import core_data as md
from app.run_state import SETTINGS
from ._common import Collapsible, badge, card, page_header

_MODE_LABEL_AR = {"dry": "تجريبي (بلا حفظ)", "limited": "محدود", "full": "كامل"}


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
            "اضغط زراً واحداً لبدء جمع التشريعات — الإعدادات الافتراضية آمنة وجاهزة"))

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

        # ── خيارات متقدّمة (مطوية افتراضياً) ──
        adv = Collapsible("خيارات متقدّمة (المصدر، الحدود، الأقسام)")

        src_row = QHBoxLayout(); src_row.setSpacing(12)
        src_row.addWidget(QLabel("المصدر:"))
        self.combo = QComboBox()
        for name in md.APPROVED_SOURCES:
            self.combo.addItem(name)
        src_row.addWidget(self.combo, 1)
        cred = md.SOURCE_CREDIBILITY
        src_row.addWidget(badge(f"المصداقية {cred:.2f}", "badgeWarning"))
        adv.addLayout(src_row)
        src_hint = QLabel("لإضافة مصادر جديدة استخدم تبويب «متقدّم ← استكشاف المصادر»")
        src_hint.setProperty("class", "hint")
        adv.addWidget(src_hint)

        limits_row = QHBoxLayout(); limits_row.setSpacing(18)
        limits_row.addWidget(QLabel("أقصى عدد صفحات:"))
        self.spin = QSpinBox(); self.spin.setRange(5, 5000)
        self.spin.setValue(SETTINGS.max_pages)
        limits_row.addWidget(self.spin)
        self.m_dry = QRadioButton("تجريبي (بلا حفظ)")
        self.m_limited = QRadioButton("محدود")
        self.m_full = QRadioButton("كامل — بعد مراجعة النتائج")
        {"dry": self.m_dry, "limited": self.m_limited,
         "full": self.m_full}[SETTINGS.mode].setChecked(True)
        for m in (self.m_dry, self.m_limited, self.m_full):
            limits_row.addWidget(m)
        limits_row.addStretch()
        adv.addLayout(limits_row)

        grid = QGridLayout(); grid.setSpacing(10)
        self._section_boxes = []
        for i, name in enumerate(md.SECTIONS):
            cb = QCheckBox(name); cb.setChecked(True)
            self._section_boxes.append(cb)
            grid.addWidget(cb, i // 2, i % 2)
        adv.addLayout(grid)

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
        if self.m_dry.isChecked():
            SETTINGS.mode = "dry"
        elif self.m_limited.isChecked():
            SETTINGS.mode = "limited"
        else:
            SETTINGS.mode = "full"
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
        mode_ar = _MODE_LABEL_AR.get(SETTINGS.mode, SETTINGS.mode)
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
                                   dry_run=(SETTINGS.mode == "dry"),
                                   parent=self)
        self.worker.finished_run.connect(self._run_finished)
        self.worker.start()

    def _request_stop(self):
        self.stop_event.set()
        self.stop.setEnabled(False)

    def _run_finished(self):
        self.resume.setEnabled(True)
        self.stop.setEnabled(False)
        self.refresh()
