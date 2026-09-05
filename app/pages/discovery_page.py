# -*- coding: utf-8 -*-
"""الشاشة 0 — استكشاف المصادر: الزاحف يبحث عن مصادره بنفسه.

أربع قنوات: الطيار الآلي (بذور + بحث + تنقيب المتن + خرائط المواقع)،
بحث مباشر (DuckDuckGo بلا مفتاح / Bing بمفتاح)، إدراج يدوي، ودليل بذور.
كل مرشح يُقيَّم (قانونية/محرك/درجة/مواد) ثم موافقة صريحة — أو اعتماد
الطيار الآلي ببوابة أعلى (decided_by='auto') مسجلة للتدقيق.
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app import core_data as md
from ._common import badge, card, page_header

COLUMNS = ["العنوان / الرابط", "المحرك", "الدرجة", "الحكم", "القناة"]

VERDICT = {
    "recommended": ("موصى به", "#28A745"),
    "rejected": ("مرفوض — غير قانوني", "#C08A00"),
    "blocked": ("محجوب robots", "#DC3545"),
}


def _verdict_item(v: str) -> QTableWidgetItem:
    label, color = VERDICT[v]
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
        q = QLineEdit(); q.setPlaceholderText("مثال: القانون المدني السوري نص كامل …")
        q.setMinimumHeight(40)
        auto = QPushButton("🤖 اكتشاف تلقائي"); auto.setProperty("class", "gold")
        auto.setToolTip("بذور + بحث + تنقيب المتن + خرائط المواقع — "
                        "والاعتماد التلقائي لمن يجتاز البوابة الأعلى")
        search = QPushButton("بحث"); search.setProperty("class", "ghost")
        seeds = QPushButton("تقييم دليل البذور"); seeds.setProperty("class", "ghost")
        manual = QPushButton("إدراج رابط يدوياً"); manual.setProperty("class", "ghost")
        row.addWidget(q, 2); row.addWidget(auto); row.addWidget(search)
        row.addWidget(seeds); row.addWidget(manual)
        qv.addLayout(row)
        self._status = QLabel("القنوات: الطيار الآلي (بذور/بحث/متن/خرائط) • "
                              "DuckDuckGo بلا مفتاح (قد يُصد) • Bing بمفتاح .env")
        self._status.setProperty("class", "hint")
        qv.addWidget(self._status)
        self._auto_btn = auto
        auto.clicked.connect(self._start_auto_discovery)
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

        self.refresh()

    # ───────────────────────── تحديث العرض من القاعدة الحية ─────────────────────────

    def refresh(self):
        rows = md.DISCOVERY_RESULTS
        table = self._table
        table.setRowCount(len(rows))
        for r, d in enumerate(rows):
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
