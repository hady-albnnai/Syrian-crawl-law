# -*- coding: utf-8 -*-
"""تبويب «الفجوات والتعلّم» (داخل شاشة متقدّم): تعرض فعلياً نتاج خطة الاكتشاف الذاتي
(DELIVERY/DESIGN-SELF-DISCOVERY.md) التي لم يكن لها أي أثر بالواجهة رغم
عملها الفعلي بالخلفية (gap_analysis.py + learning.py + dedup.py):

  1. تحليل فجوات فروع القانون — أي فرع دون الحد الأدنى المتوقَّع فعلياً.
  2. استعلامات البحث المولَّدة تلقائياً لسدّ تلك الفجوات (نفس ما يستخدمه
     autopilot.generate_candidates بالدورة القادمة — لا نص توضيحي منفصل).
  3. أداء كل مصدر معتمد عبر الدورات (من نجح تاريخياً / من استُنفد).
  4. عدد قرارات تنقيح التكرار المسجَّلة فعلياً (اكتشاف نفس القانون من
     مصدرين وحسم الفائز).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header


def _gap_item(text: str, is_gap: bool) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    from PySide6.QtGui import QColor
    it.setForeground(QColor("#DC3545" if is_gap else "#28A745"))
    f = it.font(); f.setBold(True); it.setFont(f)
    it.setTextAlignment(Qt.AlignCenter)
    return it


class InsightsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header(
            "الفجوات والتعلّم",
            "ما الفروع القانونية الناقصة؟ وأي مصادر أثبتت جدواها فعلياً؟"))

        top_row = QHBoxLayout(); top_row.setSpacing(18)

        gap_card, gv = card("تحليل الفجوات حسب الفرع")
        self._gap_table = QTableWidget(0, 3)
        self._gap_table.setHorizontalHeaderLabels(
            ["الفرع", "العدد الفعلي", "الحد الأدنى المتوقَّع"])
        self._gap_table.verticalHeader().setVisible(False)
        self._gap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self._gap_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        self._gap_table.setColumnWidth(1, 110)
        self._gap_table.setColumnWidth(2, 160)
        self._gap_table.setMinimumHeight(280)
        gv.addWidget(self._gap_table)
        gap_hint = QLabel("الحد الأدنى يُحسب آلياً: 30% من متوسط أعلى 3 "
                         "فروع تغطية بالقاعدة الحالية — لا رقم مُخمَّن")
        gap_hint.setProperty("class", "hint")
        gv.addWidget(gap_hint)
        top_row.addWidget(gap_card, 3)

        q_card, qv = card("استعلامات بحث مقترحة للفروع الناقصة")
        self._queries = QListWidget()
        self._queries.setMinimumHeight(280)
        qv.addWidget(self._queries)
        q_hint = QLabel("تُستخدم فعلياً بالدورة القادمة لـ«اكتشاف تلقائي»")
        q_hint.setProperty("class", "hint")
        qv.addWidget(q_hint)
        top_row.addWidget(q_card, 2)
        root.addLayout(top_row, 1)

        bottom_row = QHBoxLayout(); bottom_row.setSpacing(18)

        perf_card, pv = card("أداء المصادر عبر الدورات (التعلّم)")
        self._perf_table = QTableWidget(0, 4)
        self._perf_table.setHorizontalHeaderLabels(
            ["المصدر", "الدورات", "قوانين جديدة إجمالاً", "الحالة"])
        self._perf_table.verticalHeader().setVisible(False)
        self._perf_table.setEditTriggers(QTableWidget.NoEditTriggers)
        phdr = self._perf_table.horizontalHeader()
        phdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            phdr.setSectionResizeMode(c, QHeaderView.Fixed)
            self._perf_table.setColumnWidth(c, 110)
        self._perf_table.setMinimumHeight(200)
        pv.addWidget(self._perf_table)
        perf_hint = QLabel("«مستنفد» = 3 دورات متتالية بلا أي قانون جديد — "
                          "يُستبعد تلقائياً من بذر الطابور")
        perf_hint.setProperty("class", "hint")
        pv.addWidget(perf_hint)
        bottom_row.addWidget(perf_card, 2)

        dedup_card, dv = card("تنقيح التكرار (مطابقة القاعدة)")
        self._dedup_total = QLabel("—")
        self._dedup_total.setProperty("class", "statValue")
        dv.addWidget(self._dedup_total)
        self._dedup_list = QListWidget()
        self._dedup_list.setMinimumHeight(150)
        dv.addWidget(self._dedup_list)
        bottom_row.addWidget(dedup_card, 1)
        root.addLayout(bottom_row, 1)

        refresh_row = QHBoxLayout()
        refresh = QPushButton("↻  تحديث"); refresh.setProperty("class", "ghost")
        refresh.clicked.connect(self.refresh)
        refresh_row.addStretch(); refresh_row.addWidget(refresh)
        root.addLayout(refresh_row)

        self.refresh()

    def refresh(self):
        gaps = md.GAP_REPORT
        self._gap_table.setRowCount(len(gaps))
        for r, g in enumerate(gaps):
            self._gap_table.setItem(r, 0, QTableWidgetItem(g.branch))
            self._gap_table.setItem(r, 1, _gap_item(str(g.count), g.is_gap))
            self._gap_table.setItem(
                r, 2, _gap_item(f"{g.expected_min:g}", g.is_gap))
            self._gap_table.setRowHeight(r, 36)

        self._queries.clear()
        queries = md.GAP_QUERIES
        if not queries:
            self._queries.addItem("لا فجوات فعلية حالياً — أو القاعدة فارغة")
        for q in queries:
            self._queries.addItem(q)

        perf = md.SOURCE_PERFORMANCE
        self._perf_table.setRowCount(len(perf))
        for r, p in enumerate(perf):
            self._perf_table.setItem(r, 0, QTableWidgetItem(p.name))
            n = QTableWidgetItem(str(p.runs_count))
            n.setTextAlignment(Qt.AlignCenter)
            self._perf_table.setItem(r, 1, n)
            ni = QTableWidgetItem(str(p.new_identities_total))
            ni.setTextAlignment(Qt.AlignCenter)
            self._perf_table.setItem(r, 2, ni)
            status_ar = "مستنفد" if p.learned_status == "exhausted" else "نشط"
            self._perf_table.setItem(
                r, 3, _gap_item(status_ar, p.learned_status == "exhausted"))
            self._perf_table.setRowHeight(r, 34)
        if not perf:
            self._perf_table.setRowCount(1)
            self._perf_table.setItem(
                0, 0, QTableWidgetItem("لا بيانات أداء بعد — شغّل دورة اكتشاف"))

        stats = md.DEDUP_STATS
        self._dedup_total.setText(str(stats["total"]))
        self._dedup_list.clear()
        if not stats["recent"]:
            self._dedup_list.addItem("لا قرارات تنقيح مسجَّلة بعد")
        for d in stats["recent"]:
            self._dedup_list.addItem(
                f"{d['identity_key']} — حُسم بـ{d['decisive_criterion']}")
