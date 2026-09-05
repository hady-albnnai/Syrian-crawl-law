# -*- coding: utf-8 -*-
"""الشاشة 0 — استكشاف المصادر: الزاحف يبحث عن مصادره بنفسه.

ثلاث قنوات: بحث (DuckDuckGo بلا مفتاح / Bing بمفتاح)، إدراج يدوي،
ودليل بذور مرفق. كل مرشح يُقيَّم (قانونية/محرك/درجة) ثم موافقة صريحة —
لا زحف قبل approval (الخيار الآمن افتراضياً).
"""
from PySide6.QtCore import Qt
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


class DiscoveryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("استكشاف المصادر",
            "الأداة تبحث عن مصادر قانونية جديدة — تقيّمها — وأنت تقرّر من يُزحف"))

        # شريط البحث
        qcard, qv = card("البحث عن مصادر")
        row = QHBoxLayout(); row.setSpacing(12)
        q = QLineEdit(); q.setPlaceholderText("مثال: القانون المدني السوري نص كامل …")
        q.setMinimumHeight(40)
        search = QPushButton("بحث"); search.setProperty("class", "gold")
        seeds = QPushButton("تقييم دليل البذور"); seeds.setProperty("class", "ghost")
        manual = QPushButton("إدراج رابط يدوياً"); manual.setProperty("class", "ghost")
        row.addWidget(q, 2); row.addWidget(search); row.addWidget(seeds); row.addWidget(manual)
        qv.addLayout(row)
        hint = QLabel("القنوات: DuckDuckGo بلا مفتاح (قد يُصد) • Bing بمفتاح .env • دليل بذور مرفق")
        hint.setProperty("class", "hint")
        qv.addWidget(hint)
        root.addWidget(qcard)

        # جدول النتائج
        tcard, tv = card("المرشحون المكتشفون")
        table = QTableWidget(len(md.DISCOVERY_RESULTS), len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for r, d in enumerate(md.DISCOVERY_RESULTS):
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
        for name in md.APPROVED_SOURCES:
            av.addWidget(badge(name, "badgeSuccess"))
        note = QLabel("المعتمد فقط يدخل شاشة «تحديد النطاق» — المقترح لا يُزحف أبداً قبل موافقتك")
        note.setProperty("class", "hint")
        av.addWidget(note)
        root.addWidget(acard)
