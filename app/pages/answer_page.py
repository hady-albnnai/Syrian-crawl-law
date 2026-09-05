# -*- coding: utf-8 -*-
"""الشاشة 5 — جواب موثَّق: نص المادة حرفياً + استشهادات أو رفض آمن.

بلا توليد: الجواب هو المتن نفسه؛ الرفض الآمن يُعرض صراحةً (التسليم 6).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from app import core_data as md  # noqa: F401 (اتساق الشاشات: مصدر واحد)
from ._common import card, page_header


class AnswerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header(
            "جواب موثَّق",
            "الجواب = نص المادة حرفياً من المتن — لا توليد ولا استنتاج بلا مصدر"))

        qcard, qv = card("السؤال")
        row = QHBoxLayout(); row.setSpacing(12)
        self.q = QLineEdit()
        self.q.setPlaceholderText("مثال: متى تكون عقوبة الخطف الإعدام؟")
        self.q.setMinimumHeight(44)
        self.q.returnPressed.connect(self._ask)
        btn = QPushButton("أجب باستشهاد"); btn.setProperty("class", "gold")
        btn.clicked.connect(self._ask)
        row.addWidget(self.q, 2); row.addWidget(btn)
        qv.addLayout(row)
        root.addWidget(qcard)

        acard, av = card("الجواب (من المتن)")
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(220)
        av.addWidget(self.answer)
        root.addWidget(acard, 1)

        ccard, cv = card("الاستشهادات")
        self.cites = QListWidget()
        self.cites.setMinimumHeight(120)
        cv.addWidget(self.cites)
        note = QLabel("الرفض الآمن: إن لم يضرب البحث متنًا، تُعرض «لا مصدر "
                      "كافٍ» ولا يُستنتج جواب — قاعدة §8.3 في خطة ميزان.")
        note.setProperty("class", "hint")
        cv.addWidget(note)
        root.addWidget(ccard, 1)

    def _ask(self):
        from database import get_connection
        import answer as ans
        conn = get_connection()
        rep = ans.answer_question(conn, self.q.text())
        conn.close()
        self.cites.clear()
        if rep["status"] == "refused":
            self.answer.setPlainText(f"⛔ {rep['reason']}")
            self.cites.addItem("—")
            return
        self.answer.setPlainText(rep["answer"])
        for c in rep["citations"]:
            self.cites.addItem(
                f"{c['doc_title'][:50]} — {c['label']} ← {c['source_url'][:60]}")
