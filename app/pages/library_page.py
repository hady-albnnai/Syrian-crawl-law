# -*- coding: utf-8 -*-
"""الشاشة 3 — المكتبة والمراجعة: بيانات حقيقية من documents/articles.

«تعليم كمراجَع» يكتب review_status=human_verified فعلياً في القاعدة —
البوابة البشرية قبل التصدير (قرار المالك: لا نص بلا تدقيق).
"""
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from PySide6.QtGui import QColor

from app import core_data as md
from ._common import card, page_header

COLUMNS = ["العنوان", "النوع", "الفرع", "السنة", "المواد", "الجودة", "الحالة"]

SUCCESS = QColor("#28A745"); INFO = QColor("#17A2B8"); WARNING = QColor("#C08A00")


def _quality_color(q: float) -> QColor:
    if q >= 0.85: return SUCCESS
    if q >= 0.75: return INFO
    return WARNING


def _colored(text: str, color: QColor) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setForeground(color)
    f = it.font(); f.setBold(True); it.setFont(f)
    it.setTextAlignment(Qt.AlignCenter)
    return it


class LibraryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._docs = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("المكتبة والمراجعة",
                                   "راجع ما جُمع قبل التصدير — الرديء لا يعبر البوابة"))

        tools, tv = card()
        row = QHBoxLayout(); row.setSpacing(12)
        self.search = QLineEdit(); self.search.setPlaceholderText("ابحث في العناوين…")
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        self.branch = QComboBox(); self.branch.addItem("كل الفروع")
        self.branch.currentIndexChanged.connect(self._apply_filter)
        self.status = QComboBox(); self.status.addItem("كل الحالات")
        self.status.addItem("يحتاج مراجعة"); self.status.addItem("استخراج آلي")
        self.status.addItem("مراجَع بشرياً")
        self.status.currentIndexChanged.connect(self._apply_filter)
        mark = QPushButton("تعليم كمراجَع ✓"); mark.setProperty("class", "ghost")
        mark.clicked.connect(self._mark_verified)
        row.addWidget(self.search, 2); row.addWidget(self.branch)
        row.addWidget(self.status)
        row.addStretch(); row.addWidget(mark)
        tv.addLayout(row)
        root.addWidget(tools)

        table_card, tbl_v = card()
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        # خط Nسخ العربي + حشوة CSS يرفعان minimumSectionSize إلى ~187 فيقتطع
        # كل الأعمدة إليه — نكسر هذه الأرضية قبل ضبط العروض الصريحة.
        hdr.setMinimumSectionSize(48)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        for c, w in zip(range(1, len(COLUMNS)), (96, 112, 64, 64, 84, 124)):
            self.table.setColumnWidth(c, w)
        tbl_v.addWidget(self.table)
        root.addWidget(table_card, 1)

        self.hint = QLabel("")
        self.hint.setProperty("class", "hint")
        root.addWidget(self.hint)

        self.refresh()

    def refresh(self):
        self._docs = md.DOCUMENTS
        branches = sorted({d.branch for d in self._docs})
        cur = self.branch.currentText()
        self.branch.blockSignals(True)
        self.branch.clear(); self.branch.addItem("كل الفروع")
        for b in branches:
            self.branch.addItem(b)
        idx = self.branch.findText(cur)
        self.branch.setCurrentIndex(max(idx, 0))
        self.branch.blockSignals(False)
        self._apply_filter()

    def _visible_docs(self):
        q = self.search.text().strip()
        br = self.branch.currentText()
        st = self.status.currentText()
        out = []
        for d in self._docs:
            if q and q not in d.title:
                continue
            if br != "كل الفروع" and d.branch != br:
                continue
            label = md.STATUS_LABELS[d.status][0]
            if st != "كل الحالات" and label != st:
                continue
            out.append(d)
        return out

    def _apply_filter(self):
        docs = self._visible_docs()
        self.table.setRowCount(len(docs))
        for r, doc in enumerate(docs):
            title = QTableWidgetItem(doc.title)
            self.table.setItem(r, 0, title)
            self.table.setItem(r, 1, QTableWidgetItem(doc.kind))
            self.table.setItem(r, 2, QTableWidgetItem(doc.branch))
            self.table.setItem(r, 3, QTableWidgetItem(str(doc.year) if doc.year else "—"))
            arts = QTableWidgetItem(str(doc.articles) if doc.articles else "—")
            arts.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 4, arts)
            self.table.setItem(r, 5, _colored(f"{doc.quality:.2f}",
                                              _quality_color(doc.quality)))
            label, _cls = md.STATUS_LABELS[doc.status]
            self.table.setItem(r, 6, _colored(label, _quality_color(
                0.9 if doc.status == "human_verified" else
                0.8 if doc.status == "auto_extracted" else 0.5)))
            self.table.setRowHeight(r, 44)
        self.hint.setText(f"المعروض: {len(docs)} من {len(self._docs)} وثيقة — "
                          "«تعليم كمراجَع» ينقل review_status إلى human_verified في القاعدة")

    def _mark_verified(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.hint.setText("حدّد صفاً أو أكثر أولاً.")
            return
        docs = self._visible_docs()
        ids = [docs[r].doc_id for r in rows if r < len(docs) and docs[r].doc_id]
        if not ids:
            self.hint.setText("الصفوف المحددة بلا معرّف وثيقة.")
            return
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.executemany(
            "UPDATE documents SET review_status='human_verified', "
            "updated_at=datetime('now') WHERE id=?", [(i,) for i in ids])
        conn.commit()
        conn.close()
        from database import insert_log  # بعد الإغلاق: لا قفلين متزامنين
        insert_log("", "review",
                   f"تعليم {len(ids)} وثيقة كمراجعة بشرياً من الواجهة")
        self.refresh()
