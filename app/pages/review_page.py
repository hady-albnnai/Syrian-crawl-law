# -*- coding: utf-8 -*-
"""شاشة «نتائج الزحف» — التصميم المطلوب من المالك (2026-09-06):

تُفتح بالضغط على «نتائج الزحف» من شاشة البداية بعد انتهاء الزحف. تعرض
قائمة كل ما جُمع، إمكانية فتح كل نتيجة ومعاينة نصها الكامل، تمييز ما
يحتاج مراجعة صراحة، وزرَّي موافقة/رفض لكل نتيجة.

زر «اعتماد وتجهيز لميزان» النهائي مُعطَّل حالياً بقرار صريح من المالك:
الأولوية الآن لدقّة واستقرار نتائج الزحف نفسها؛ صيغة التصدير الفعلية
لميزان (استيراد مباشر أو ملفات بصيغة يقبلها التطبيق) ستُحسم لاحقاً بعد
قراءة تطبيق ميزان فعلياً — لا تخمين لصيغة غير مؤكدة الآن.
"""
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header

COLUMNS = ["العنوان", "الفرع", "المواد", "الحالة"]

SUCCESS = QColor("#28A745"); WARNING = QColor("#C08A00"); ERROR = QColor("#DC3545")


def _status_item(status: str) -> QTableWidgetItem:
    label, color = {
        "human_verified": ("مُعتمَد ✓", SUCCESS),
        "needs_review": ("يحتاج مراجعة", WARNING),
        "rejected": ("مرفوض ✗", ERROR),
    }.get(status, ("استخراج آلي", QColor("#17A2B8")))
    it = QTableWidgetItem(label)
    it.setForeground(color)
    f = it.font(); f.setBold(True); it.setFont(f)
    it.setTextAlignment(Qt.AlignCenter)
    return it


class ReviewPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_back = None  # MainWindow يربطها بالعودة لشاشة البداية
        self._docs = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.addWidget(page_header(
            "نتائج الزحف",
            "راجع ما جُمع — افتح أي نتيجة لمعاينة نصها كاملاً قبل الاعتماد"))
        top.addStretch()
        back = QPushButton("◀  رجوع للبداية"); back.setProperty("class", "ghost")
        back.clicked.connect(self._back)
        top.addWidget(back)
        root.addLayout(top)

        body = QHBoxLayout(); body.setSpacing(18)

        list_card, lv = card("القائمة")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setMinimumSectionSize(48)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        for c, w in zip(range(1, len(COLUMNS)), (110, 64, 130)):
            self.table.setColumnWidth(c, w)
        self.table.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self.table)
        body.addWidget(list_card, 2)

        preview_card, pv = card("معاينة النص الكامل")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumWidth(360)
        pv.addWidget(self.preview)
        actions = QHBoxLayout()
        self.approve_btn = QPushButton("موافقة ✓"); self.approve_btn.setProperty("class", "primary")
        self.reject_btn = QPushButton("رفض ✗"); self.reject_btn.setProperty("class", "ghost")
        self.approve_btn.clicked.connect(self._approve_selected)
        self.reject_btn.clicked.connect(self._reject_selected)
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        actions.addWidget(self.reject_btn); actions.addWidget(self.approve_btn)
        pv.addLayout(actions)
        body.addWidget(preview_card, 3)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.hint = QLabel(""); self.hint.setProperty("class", "hint")
        bottom.addWidget(self.hint); bottom.addStretch()
        finalize = QPushButton("اعتماد وتجهيز لميزان  ◀")
        finalize.setProperty("class", "gold")
        finalize.setEnabled(False)
        finalize.setToolTip(
            "مؤجَّل عمداً: سيُفعَّل بعد استقرار دقّة نتائج الزحف، وبعد "
            "تحديد صيغة الاستيراد التي يقبلها تطبيق ميزان فعلياً")
        bottom.addWidget(finalize)
        root.addLayout(bottom)

        self.refresh()

    def refresh(self):
        self._docs = md.DOCUMENTS
        self.table.setRowCount(len(self._docs))
        for r, d in enumerate(self._docs):
            self.table.setItem(r, 0, QTableWidgetItem(d.title))
            self.table.setItem(r, 1, QTableWidgetItem(d.branch))
            arts = QTableWidgetItem(str(d.articles) if d.articles else "—")
            arts.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 2, arts)
            self.table.setItem(r, 3, _status_item(d.status))
            self.table.setRowHeight(r, 40)
        n_review = sum(1 for d in self._docs if d.status == "needs_review")
        self.hint.setText(f"الإجمالي: {len(self._docs)} — يحتاج مراجعة: {n_review}")
        self._on_select()

    def _selected_doc(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or rows[0] >= len(self._docs):
            return None
        return self._docs[rows[0]]

    def _on_select(self):
        doc = self._selected_doc()
        if doc is None:
            self.preview.setPlainText("")
            self.approve_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            return
        text = md.document_text(doc.doc_id) if doc.doc_id else ""
        self.preview.setPlainText(text or "(لا نص محفوظ لهذه الوثيقة)")
        self.approve_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)

    def _set_review_status(self, value: str):
        doc = self._selected_doc()
        if doc is None or not doc.doc_id:
            return
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE documents SET review_status=?, updated_at=datetime('now') "
            "WHERE id=?", (value, doc.doc_id))
        conn.commit()
        conn.close()
        from database import insert_log
        insert_log("", "review", f"وثيقة #{doc.doc_id} ← review_status={value}")
        self.refresh()

    def _approve_selected(self):
        self._set_review_status("human_verified")

    def _reject_selected(self):
        doc = self._selected_doc()
        if doc is None:
            return
        reply = QMessageBox.question(
            self, "تأكيد الرفض",
            f"رفض «{doc.title[:60]}» — لن تدخل حزمة التصدير لميزان. متابعة؟")
        if reply != QMessageBox.Yes:
            return
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE documents SET status='rejected', updated_at=datetime('now') "
            "WHERE id=?", (doc.doc_id,))
        conn.commit()
        conn.close()
        from database import insert_log
        insert_log("", "review", f"وثيقة #{doc.doc_id} رُفضت من المراجعة")
        self.refresh()

    def _back(self):
        if self.on_back:
            self.on_back()
