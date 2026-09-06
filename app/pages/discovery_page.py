# -*- coding: utf-8 -*-
"""الشاشة 0 — استكشاف المصادر: الزاحف يبحث عن مصادره بنفسه.

أربع قنوات: الطيار الآلي (بذور + بحث + تنقيب المتن + خرائط المواقع)،
بحث مباشر (DuckDuckGo بلا مفتاح / Bing بمفتاح)، إدراج يدوي، ودليل بذور.
كل مرشح يُقيَّم (قانونية/محرك/درجة/مواد) ثم موافقة صريحة — أو اعتماد
الطيار الآلي ببوابة أعلى (decided_by='auto') مسجلة للتدقيق.

كانت أزرار «بحث»/«تقييم دليل البذور»/«إدراج رابط يدوياً»/«اعتماد»/
«استبعاد» معروضة بلا أي اتصال فعلي (بيانات وهمية بصرياً) — كلها موصولة
الآن بمنطق discovery.py الحقيقي نفسه المستخدم من `cli discover`.
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app import core_data as md
from ._common import badge, card, page_header

COLUMNS = ["العنوان / الرابط", "المحرك", "الدرجة", "الحكم", "القناة"]

VERDICT = {
    "recommended": ("موصى به", "#28A745"),
    "rejected": ("مرفوض — غير قانوني", "#C08A00"),
    "blocked": ("محجوب robots", "#DC3545"),
}


def _verdict_item(v: str) -> QTableWidgetItem:
    label, color = VERDICT.get(v, VERDICT["rejected"])
    it = QTableWidgetItem(label)
    from PySide6.QtGui import QColor
    it.setForeground(QColor(color))
    f = it.font(); f.setBold(True); it.setFont(f)
    return it


class _AutoDiscoverWorker(QThread):
    """حلقة الطيار الآلي خارج خيط الواجهة — لا تجميد أثناء التقييم."""
    done = Signal(dict)

    def run(self):
        try:
            from autopilot import run_discovery
            from database import create_tables, get_connection
            create_tables()
            conn = get_connection()
            try:
                stats = run_discovery(conn, auto_approve=True,
                                      use_search=True, max_evaluate=8)
            finally:
                conn.close()
            self.done.emit(stats)
        except Exception as exc:  # noqa: BLE001 — الواجهة تعرض ولا تنهار
            self.done.emit({"error": str(exc)})


class _SearchWorker(QThread):
    """بحث + تسجيل مباشر (بلا اعتماد تلقائي) — نفس مسار `cli discover --evaluate`."""
    done = Signal(dict)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        try:
            from database import create_tables, get_connection
            from discovery import (DuckDuckGoHtmlProvider, SearchUnavailable,
                                   evaluate_candidate, register_candidate)
            create_tables()
            provider = DuckDuckGoHtmlProvider()
            candidates = provider.search(self.query, limit=8)
            conn = get_connection()
            n_new = 0
            try:
                for cand in candidates:
                    ev = evaluate_candidate(cand.url)
                    _id, created = register_candidate(conn, cand.url,
                                                       cand.via, ev)
                    n_new += int(created)
                conn.commit()
            finally:
                conn.close()
            self.done.emit({"found": len(candidates), "new": n_new})
        except SearchUnavailable as exc:
            self.done.emit({"error": f"البحث غير متاح حالياً: {exc}"})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class _SeedsWorker(QThread):
    """تقييم دليل البذور المرفق (discovery.seed_candidates) — بلا اعتماد."""
    done = Signal(dict)

    def run(self):
        try:
            from database import create_tables, get_connection
            from discovery import (evaluate_candidate, register_candidate,
                                   seed_candidates)
            create_tables()
            conn = get_connection()
            n_new = 0
            seeds = seed_candidates()
            try:
                for cand in seeds:
                    ev = evaluate_candidate(cand.url)
                    _id, created = register_candidate(conn, cand.url,
                                                       cand.via, ev)
                    n_new += int(created)
                conn.commit()
            finally:
                conn.close()
            self.done.emit({"found": len(seeds), "new": n_new})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class DiscoveryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("استكشاف المصادر",
            "الأداة تبحث عن مصادر قانونية جديدة — تقيّمها — وتعتمد الأقوى تلقائياً"))

        # شريط البحث
        qcard, qv = card("البحث عن مصادر")
        row = QHBoxLayout(); row.setSpacing(12)
        self._query = QLineEdit()
        self._query.setPlaceholderText("مثال: القانون المدني السوري نص كامل …")
        self._query.setMinimumHeight(40)
        auto = QPushButton("🤖 اكتشاف تلقائي"); auto.setProperty("class", "gold")
        auto.setToolTip("بذور + بحث + تنقيب المتن + خرائط المواقع — "
                        "والاعتماد التلقائي لمن يجتاز البوابة الأعلى")
        search = QPushButton("بحث"); search.setProperty("class", "ghost")
        seeds = QPushButton("تقييم دليل البذور"); seeds.setProperty("class", "ghost")
        manual = QPushButton("إدراج رابط يدوياً"); manual.setProperty("class", "ghost")
        row.addWidget(self._query, 2); row.addWidget(auto); row.addWidget(search)
        row.addWidget(seeds); row.addWidget(manual)
        qv.addLayout(row)
        self._status = QLabel("القنوات: الطيار الآلي (بذور/بحث/متن/خرائط) • "
                              "DuckDuckGo بلا مفتاح (قد يُصد) • Bing بمفتاح .env")
        self._status.setProperty("class", "hint")
        qv.addWidget(self._status)
        self._auto_btn = auto
        self._search_btn = search
        self._seeds_btn = seeds
        auto.clicked.connect(self._start_auto_discovery)
        search.clicked.connect(self._start_search)
        seeds.clicked.connect(self._start_seeds_eval)
        manual.clicked.connect(self._manual_insert)
        root.addWidget(qcard)

        # جدول النتائج
        tcard, tv = card("المرشحون المكتشفون")
        self._table = QTableWidget(0, len(COLUMNS))
        table = self._table
        table.setHorizontalHeaderLabels(COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMaximumHeight(252)
        hdr = table.horizontalHeader()
        hdr.setMinimumSectionSize(48)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        for c, w in zip(range(1, len(COLUMNS)), (96, 70, 150, 100)):
            table.setColumnWidth(c, w)
        tv.addWidget(table)

        btns = QHBoxLayout()
        approve = QPushButton("اعتماد المحدد مصدراً ✓"); approve.setProperty("class", "primary")
        reject = QPushButton("استبعاد"); reject.setProperty("class", "ghost")
        approve.clicked.connect(self._approve_selected)
        reject.clicked.connect(self._reject_selected)
        btns.addStretch(); btns.addWidget(reject); btns.addWidget(approve)
        tv.addLayout(btns)
        root.addWidget(tcard, 1)

        # المصادر المعتمدة
        acard, av = card("المصادر المعتمدة للزحف")
        self._approved_box = av
        self._note = QLabel("المعتمد (يدوياً أو بالطيار الآلي) وحده يدخل "
                            "طابور الزحف — وكل قرار auto مسجل في سجل المصادر")
        self._note.setProperty("class", "hint")
        root.addWidget(acard)

        self._rows = []
        self.refresh()

    # ───────────────────────── تحديث العرض من القاعدة الحية ─────────────────────────

    def refresh(self):
        self._rows = md.DISCOVERY_RESULTS
        table = self._table
        table.setRowCount(len(self._rows))
        for r, d in enumerate(self._rows):
            t = QTableWidgetItem(f"{d.title}\n{d.url}")
            f = t.font(); f.setBold(r == 0); t.setFont(f)
            table.setItem(r, 0, t)
            table.setItem(r, 1, QTableWidgetItem(d.engine))
            sc = QTableWidgetItem(f"{d.score:.2f}")
            sc.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 2, sc)
            table.setItem(r, 3, _verdict_item(d.verdict))
            table.setItem(r, 4, QTableWidgetItem(d.via))
            table.setRowHeight(r, 46)
        # شارات المعتمد
        while self._approved_box.count() > 1:  # تبقى الملاحظة الأخيرة
            it = self._approved_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, name in enumerate(md.APPROVED_SOURCES):
            self._approved_box.insertWidget(i, badge(name, "badgeSuccess"))

    def _selected_source_key(self):
        rows = sorted({i.row() for i in self._table.selectedIndexes()})
        if not rows or rows[0] >= len(self._rows):
            return None
        return self._rows[rows[0]].source_key

    # ───────────────────────── الطيار الآلي ─────────────────────────

    def _start_auto_discovery(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._auto_btn.setEnabled(False)
        self._status.setText("🤖 الطيار الآلي يعمل: يولّد مرشحين ← يقيّم ← يعتمد…")
        self._worker = _AutoDiscoverWorker(self)
        self._worker.done.connect(self._on_auto_done)
        self._worker.start()

    def _on_auto_done(self, stats: dict):
        self._auto_btn.setEnabled(True)
        if "error" in stats:
            self._status.setText(f"⚠️ تعطل الطيار الآلي: {stats['error']}")
            return
        self._status.setText(
            f"🤖 رُئي {stats['seen']} • قُيّم {stats['evaluated']} • "
            f"اعتُمد تلقائياً {stats['approved']} • مقترح/مرفوض "
            f"{stats['rejected']} • محجوب {stats['blocked']}")
        self.refresh()

    # ───────────────────────── بحث مباشر ─────────────────────────

    def _start_search(self):
        query = self._query.text().strip()
        if not query:
            self._status.setText("⚠️ اكتب استعلام بحث أولاً.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._search_btn.setEnabled(False)
        self._status.setText(f"🔎 يبحث عن: {query} …")
        self._worker = _SearchWorker(query, self)
        self._worker.done.connect(self._on_search_done)
        self._worker.start()

    def _on_search_done(self, result: dict):
        self._search_btn.setEnabled(True)
        if "error" in result:
            self._status.setText(f"⚠️ {result['error']}")
            return
        self._status.setText(
            f"🔎 وُجد {result['found']} مرشحاً — {result['new']} جديد "
            "سُجِّل بحالة proposed (يحتاج اعتماداً يدوياً أدناه)")
        self.refresh()

    # ───────────────────────── دليل البذور ─────────────────────────

    def _start_seeds_eval(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._seeds_btn.setEnabled(False)
        self._status.setText("📖 يقيّم دليل البذور المرفق …")
        self._worker = _SeedsWorker(self)
        self._worker.done.connect(self._on_seeds_done)
        self._worker.start()

    def _on_seeds_done(self, result: dict):
        self._seeds_btn.setEnabled(True)
        if "error" in result:
            self._status.setText(f"⚠️ {result['error']}")
            return
        self._status.setText(
            f"📖 قُيِّم {result['found']} من دليل البذور — {result['new']} "
            "جديد سُجِّل بحالة proposed")
        self.refresh()

    # ───────────────────────── إدراج يدوي ─────────────────────────

    def _manual_insert(self):
        url, ok = QInputDialog.getText(self, "إدراج رابط يدوياً",
                                       "رابط المصدر (https://...):")
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "رابط غير صالح",
                                "الرابط يجب أن يبدأ بـ http:// أو https://")
            return
        from database import create_tables, get_connection
        from discovery import evaluate_candidate, register_candidate
        create_tables()
        conn = get_connection()
        ev = evaluate_candidate(url)
        _id, created = register_candidate(conn, url, "manual", ev)
        conn.commit(); conn.close()
        self._status.setText(
            f"✚ {'أُضيف' if created else 'موجود مسبقاً'}: {url} — "
            f"الحكم: {VERDICT.get(ev.verdict, (ev.verdict,))[0]}")
        self.refresh()

    # ───────────────────────── اعتماد / استبعاد ─────────────────────────

    def _approve_selected(self):
        key = self._selected_source_key()
        if not key:
            self._status.setText("⚠️ حدّد صفاً من الجدول أولاً.")
            return
        from database import get_connection
        from discovery import decide_source
        conn = get_connection()
        decide_source(conn, key, approve=True, decided_by="user")
        conn.close()
        self._status.setText("✓ اعتُمد المصدر المحدد — سيدخل الزحف القادم.")
        self.refresh()

    def _reject_selected(self):
        key = self._selected_source_key()
        if not key:
            self._status.setText("⚠️ حدّد صفاً من الجدول أولاً.")
            return
        from database import get_connection
        from discovery import decide_source
        conn = get_connection()
        decide_source(conn, key, approve=False, decided_by="user")
        conn.close()
        self._status.setText("✗ استُبعد المصدر المحدد.")
        self.refresh()
