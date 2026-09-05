# -*- coding: utf-8 -*-
"""الشاشة 3 — المكتبة والمراجعة: هل الناتج صالح؟"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from PySide6.QtGui import QColor

from app import mock_data as md
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
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("المكتبة والمراجعة",
                                   "راجع ما جُمع قبل التصدير — الرديء لا يعبر البوابة"))

        tools, tv = card()
        row = QHBoxLayout(); row.setSpacing(12)
        search = QLineEdit(); search.setPlaceholderText("ابحث في العناوين…")
        search.setMinimumWidth(260)
        branch = QComboBox(); branch.addItem("كل الفروع")
        for b in sorted({d.branch for d in md.DOCUMENTS}): branch.addItem(b)
        status = QComboBox(); status.addItem("كل الحالات")
        status.addItem("يحتاج مراجعة"); status.addItem("استخراج آلي"); status.addItem("مراجَع بشرياً")
        mark = QPushButton("تعليم كمراجَع ✓"); mark.setProperty("class", "ghost")
        row.addWidget(search, 2); row.addWidget(branch); row.addWidget(status)
        row.addStretch(); row.addWidget(mark)
        tv.addLayout(row)
        root.addWidget(tools)

        table_card, tbl_v = card()
        table = QTableWidget(len(md.DOCUMENTS), len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for r, doc in enumerate(md.DOCUMENTS):
            title = QTableWidgetItem(doc.title)
            f = table.font(); f.setBold(r < 2); title.setFont(f)
            table.setItem(r, 0, title)
            table.setItem(r, 1, QTableWidgetItem(doc.kind))
            table.setItem(r, 2, QTableWidgetItem(doc.branch))
            table.setItem(r, 3, QTableWidgetItem(str(doc.year) if doc.year else "—"))
            arts = QTableWidgetItem(str(doc.articles) if doc.articles else "—")
            arts.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 4, arts)
            table.setItem(r, 5, _colored(f"{doc.quality:.2f}", _quality_color(doc.quality)))
            label, _cls = md.STATUS_LABELS[doc.status]
            table.setItem(r, 6, _colored(label, _quality_color(
                0.9 if doc.status == "human_verified" else
                0.8 if doc.status == "auto_extracted" else 0.5)))
            table.setRowHeight(r, 44)
        hdr = table.horizontalHeader()
        # خط Nسخ العربي + حشوة CSS يرفعان minimumSectionSize إلى ~187 فيقتطع
        # كل الأعمدة إليه — نكسر هذا الأرضية قبل ضبط العروض الصريحة.
        hdr.setMinimumSectionSize(48)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        for c, w in zip(range(1, len(COLUMNS)), (96, 112, 64, 64, 84, 124)):
            table.setColumnWidth(c, w)
        tbl_v.addWidget(table)
        root.addWidget(table_card, 1)

        hint = QLabel("المحدد: 3 وثائق — «تعليم كمراجَع» ينقل review_status إلى human_verified (يُسجل في السجل)")
        hint.setProperty("class", "hint")
        root.addWidget(hint)
