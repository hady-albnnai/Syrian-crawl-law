# -*- coding: utf-8 -*-
"""الشاشة 2 — التشغيل: التقدم الحي والإيقاف والاستئناف."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from app import mock_data as md
from ._common import card, page_header


def _stat(value: str, label: str) -> QWidget:
    c, v = card()
    val = QLabel(value); val.setProperty("class", "statValue")
    lab = QLabel(label); lab.setProperty("class", "statLabel")
    val.setAlignment(Qt.AlignCenter); lab.setAlignment(Qt.AlignCenter)
    v.addWidget(val); v.addWidget(lab)
    return c


class RunPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("التشغيل", "الطابور دائم — يمكن إغلاق الأداة واستئنافها دون تكرار وثيقة أو مادة"))

        stats = QHBoxLayout(); stats.setSpacing(16)
        stats.addWidget(_stat("34 / 50", "صفحات مزحوفة"))
        stats.addWidget(_stat("21", "وثائق محفوظة"))
        stats.addWidget(_stat("3٬142", "مواد مستخرجة"))
        stats.addWidget(_stat("3", "إخفاقات مسجلة"))
        root.addLayout(stats)

        prog_card, pv = card()
        top = QHBoxLayout()
        t = QLabel("تقدم الدورة الحالية"); t.setProperty("class", "cardTitle")
        pct = QLabel("68%"); pct.setProperty("class", "cardTitle")
        top.addWidget(t); top.addStretch(); top.addWidget(pct)
        pv.addLayout(top)
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(68); bar.setTextVisible(False)
        bar.setMinimumHeight(18)
        pv.addWidget(bar)
        root.addWidget(prog_card)

        log_card, lv = card("سجل الأحداث")
        log = QPlainTextEdit(); log.setObjectName("logView")
        log.setReadOnly(True)
        for ts, tag, msg, _ in md.LOG_EVENTS:
            log.appendPlainText(f"[{ts}] [{tag:8s}] {msg}")
        log.setMinimumHeight(220)
        lv.addWidget(log)
        root.addWidget(log_card, 1)

        btns = QHBoxLayout()
        stop = QPushButton("■  إيقاف"); stop.setProperty("class", "ghost")
        pause = QPushButton("إيقاف مؤقت"); pause.setProperty("class", "ghost")
        resume = QPushButton("▶  استئناف"); resume.setProperty("class", "primary")
        btns.addWidget(stop); btns.addWidget(pause); btns.addStretch(); btns.addWidget(resume)
        root.addLayout(btns)
