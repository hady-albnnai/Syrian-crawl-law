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
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from app import core_data as md
from ._common import Collapsible, card, page_header

DEFAULT_MAX_PAGES = 60


def _stat_card(label: str) -> QWidget:
    c, v = card()
    val = QLabel("—"); val.setObjectName("value")
    val.setProperty("class", "statValue")
    lab = QLabel(label); lab.setProperty("class", "statLabel")
    val.setAlignment(Qt.AlignCenter); lab.setAlignment(Qt.AlignCenter)
    v.addWidget(val); v.addWidget(lab)
    return c


def _git_head() -> str:
    """الفرع+الالتزام الحاليان — درس موثق في الدفتر: تشغيل نسخة قديمة
    أرسل 7,000+ طلب زائد وثبّت حجبا كان قابلاً للتفادي. الشاشة تعرضه
    الآن بدل أن يُنسى قبل كل جلسة."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(["git", "log", "--oneline", "-1"], cwd=root,
                             capture_output=True, text=True, timeout=4)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()[:60]
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


class _AutopilotWorker(QThread):
    """اكتشاف تلقائي كامل ثم زحف — نفس autopilot.run_autopilot المستخدم
    بأمر `cli autopilot`، خارج خيط الواجهة كي لا تتجمد النافذة."""
    finished_run = Signal(dict)

    def __init__(self, max_pages, stop_event, parent=None, *,
                 auto_approve: bool = False, use_search: bool = True):
        super().__init__(parent)
        self.max_pages = max_pages
        self.stop_event = stop_event
        # auto_approve=False افتراضياً: الاعتماد التلقائي للمصادر كان
        # **مُمرَّراً True بلا خيار وبلا إعلام** (قِيس في التدقيق)، بينما
        # السياسة الموثقة أن اعتماد المصدر قرار المالك. الآن الزر في الشاشة.
        self.auto_approve = auto_approve
        self.use_search = use_search

    def run(self):
        stats = {}
        try:
            from database import create_tables, get_connection
            from autopilot import run_discovery
            create_tables()
            conn = get_connection()
            try:
                stats = run_discovery(conn, auto_approve=self.auto_approve,
                                      use_search=self.use_search,
                                      max_evaluate=12)
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
        self.stat_cards = {}
        for key, label in (("done", "منجزة"), ("review", "تحتاج مراجعة"),
                           ("queued", "منتظرة"), ("failed", "فاشلة"),
                           ("docs", "وثائق"), ("articles", "مواد")):
            c = _stat_card(label)
            self.stat_cards[key] = c.findChild(QLabel, "value")
            self.stats_row.addWidget(c)
        root.addLayout(self.stats_row)

        policy_card, pol = card()
        prow = QHBoxLayout(); prow.setSpacing(18)
        self.auto_approve_box = QCheckBox(
            "اعتماد المصادر المكتشفة تلقائياً (بوابة ≥70 و≥3 مواد)")
        self.auto_approve_box.setToolTip(
            "إبقُه مطفأً إن أردت أن تعتمد كل مصدر بيدك: sources approve <id> — "
            "القرار أصلاً لك حسب السياسة الموثقة")
        self.search_box = QCheckBox("توليد مرشحين بالبحث (DuckDuckGo/Bing)")
        self.search_box.setChecked(True)
        prow.addWidget(self.auto_approve_box)
        prow.addWidget(self.search_box)
        prow.addStretch()
        pol.addLayout(prow)
        self.meta_label = QLabel(""); self.meta_label.setProperty("class", "hint")
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pol.addWidget(self.meta_label)
        root.addWidget(policy_card)

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
        # الشدّ داخل جسم القابلية للطي: عند الطي يبقى الفارغ تحت البطاقات
        # (لا فجوة وسط الصفحة)، وعند التوسّع يملأ السجل المتاح.
        log_section.body_layout.addStretch()
        root.addWidget(log_section)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(4000)

    def refresh(self):
        try:
            self._refresh_inner()
        except Exception as exc:  # noqa: BLE001 — الواجهة تُبلِّغ ولا تنهار
            self.status_label.setText(f"⚠︎ تعذّر قراءة الحالة: "
                                      f"{type(exc).__name__}: {exc}")

    def _refresh_inner(self):
        s = md.RUN_STATS or {}
        q = s.get("queue", {})
        # لا دمج فشل مع نجاح: النسخة القديمة كانت تحسب failed داخل
        # «مهام منجزة» فتصل النسبة 100٪ حتى لو انهار المصدر كله
        # (قياس قاعدة المالك: 542 نجاح + 8,501 فشل = «9,044 منجزة»).
        done = q.get("success", 0)
        failed = q.get("failed", 0)
        total = sum(q.values())
        for key, val in (("done", done), ("review", q.get("needs_review", 0)),
                         ("queued", q.get("queued", 0) + q.get("running", 0)),
                         ("failed", failed), ("docs", s.get("docs", 0)),
                         ("articles", s.get("articles", 0))):
            lab = self.stat_cards.get(key)
            if lab is not None:
                lab.setText(f"{val:,}")
        pct = int(100 * done / total) if total else 0
        self.bar.setValue(pct)
        self.pct.setText(f"{pct}% نجاح من {total:,} مهمة"
                         + (f" — {failed:,} فاشلة" if failed else ""))
        run = s.get("last_run") or {}
        meta = []
        try:
            import config
            meta.append(f"الإصدار v{config.VERSION}")
        except Exception:  # noqa: BLE001
            pass
        commit = _git_head()
        if commit:
            meta.append(commit)
        if run:
            meta.append(f"آخر دورة #{run.get('id')} [{run.get('mode')}] — "
                        f"{run.get('pages', 0)} صفحة | "
                        f"{run.get('docs', 0)} وثيقة | "
                        f"{run.get('failures', 0)} إخفاق")
            meta.append("قاطع الدورة: 12 إخفاق جلب متتالٍ يوقفها (config)")
        self.meta_label.setText("  ·  ".join(meta))
        self._reload_log()
        needs_review = q.get("needs_review", 0)
        if not (self.worker and self.worker.isRunning()):
            self.results_btn.setEnabled(bool(done or s.get("docs", 0)))
            if needs_review:
                self.results_btn.setText(f"نتائج الزحف ({needs_review:,} تحتاج مراجعة)  ◀")
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
                                       parent=self,
                                       auto_approve=self.auto_approve_box.isChecked(),
                                       use_search=self.search_box.isChecked())
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
