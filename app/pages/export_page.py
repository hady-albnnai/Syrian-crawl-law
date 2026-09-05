# -*- coding: utf-8 -*-
"""الشاشة 4 — التصدير: ماذا أسلّم لميزان؟"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from app import mock_data as md
from ._common import card, page_header


def _stat(value: str, label: str, color: str = None) -> QWidget:
    c, v = card()
    val = QLabel(value); val.setProperty("class", "statValue")
    if color: val.setStyleSheet(f"color: {color};")
    lab = QLabel(label); lab.setProperty("class", "statLabel")
    val.setAlignment(Qt.AlignCenter); lab.setAlignment(Qt.AlignCenter)
    v.addWidget(val); v.addWidget(lab)
    return c


class ExportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("التصدير إلى ميزان",
                                   "حزمة واحدة قابلة للنسخ — المجتاز فقط يعبر افتراضياً"))

        stats = QHBoxLayout(); stats.setSpacing(16)
        stats.addWidget(_stat("18", "وثائق للتصدير"))
        stats.addWidget(_stat("3٬092", "مواد ضمن الحزمة"))
        stats.addWidget(_stat("2", "مستثناة — تحتاج مراجعة", "#DC3545"))
        root.addLayout(stats)

        row = QHBoxLayout(); row.setSpacing(18)

        tree_card, tv = card("معاينة الحزمة")
        for line, is_root in md.PACKAGE_TREE:
            lbl = QLabel(line)
            lbl.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
            if is_root:
                lbl.setStyleSheet(lbl.styleSheet() + " font-weight: 800;")
            tv.addWidget(lbl)
        tv.addStretch()
        row.addWidget(tree_card, 3)

        val_card, vv = card("بوابة التحقق")
        for text, ok in md.VALIDATION_CHECKS:
            mark = "✓" if ok else "✗"
            color = "#28A745" if ok else "#DC3545"
            item = QLabel(f'<span style="color:{color}; font-weight:800;">{mark}</span>  {text}')
            vv.addWidget(item)
        vv.addStretch()
        row.addWidget(val_card, 2)
        root.addLayout(row, 1)

        btns = QHBoxLayout()
        gen = QPushButton("توليد الحزمة  ◀"); gen.setProperty("class", "gold")
        gen.setMinimumHeight(48); gen.setMinimumWidth(220)
        folder = QPushButton("فتح مجلد الحزم"); folder.setProperty("class", "ghost")
        btns.addStretch(); btns.addWidget(folder); btns.addWidget(gen)
        root.addLayout(btns)

        hint = QLabel("بعد التوليد: انسخ المجلد إلى ميزان — الاستيراد التلقائي يحتاج مستورد CSV في ميزان (موثق في ADR-001)")
        hint.setProperty("class", "hint")
        root.addWidget(hint)
