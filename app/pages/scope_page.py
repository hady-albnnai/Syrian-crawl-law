# -*- coding: utf-8 -*-
"""الشاشة 1 — النطاق: ماذا أجمع؟"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QLabel, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from app import mock_data as md
from ._common import badge, card, page_header


class ScopePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("تحديد النطاق", "اختر المصدر والأقسام وحدود التشغيل — الخيار الآمن هو الافتراضي"))

        row = QHBoxLayout(); row.setSpacing(18)

        # بطاقة المصدر
        src_card, sv = card("المصدر")
        combo = QComboBox(); combo.addItem(md.SOURCE_NAME)
        sv.addWidget(combo)
        cred_row = QHBoxLayout()
        cred_row.addWidget(badge(f"المصداقية {md.SOURCE_CREDIBILITY} — مصدر منتدى: بوابة جودة صارمة", "badgeWarning"))
        cred_row.addStretch()
        sv.addLayout(cred_row)
        hint = QLabel("محوّل المصدر phpBB — تُضاف مصادر رسمية لاحقاً (قرار مفتوح في ADR-001)")
        hint.setProperty("class", "hint")
        sv.addWidget(hint)
        src_card.setMinimumWidth(430)
        row.addWidget(src_card, 3)

        # بطاقة الحدود
        lim_card, lv = card("حدود التشغيل")
        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel("أقصى عدد صفحات:"))
        spin = QSpinBox(); spin.setRange(5, 5000); spin.setValue(50)
        pages_row.addWidget(spin); pages_row.addStretch()
        lv.addLayout(pages_row)
        modes = QHBoxLayout()
        m1 = QRadioButton("تجريبي (بلا حفظ)"); m1.setChecked(True)
        m2 = QRadioButton("محدود"); m3 = QRadioButton("كامل — بعد مراجعة النتائج")
        for m in (m1, m2, m3): modes.addWidget(m)
        modes.addStretch()
        lv.addLayout(modes)
        row.addWidget(lim_card, 2)
        root.addLayout(row)

        # بطاقة الأقسام
        sec_card, secv = card("أقسام المنتدى")
        grid = QGridLayout(); grid.setSpacing(10)
        for i, name in enumerate(md.SECTIONS):
            cb = QCheckBox(name); cb.setChecked(i < 3)
            grid.addWidget(cb, i // 2, i % 2)
        secv.addLayout(grid)
        root.addWidget(sec_card)

        # زر البدء
        btn_row = QHBoxLayout()
        start = QPushButton = None
        from PySide6.QtWidgets import QPushButton
        start = QPushButton("▶  بدء الزحف"); start.setProperty("class", "primary")
        start.setMinimumHeight(48); start.setMinimumWidth(220)
        btn_row.addStretch(); btn_row.addWidget(start)
        root.addLayout(btn_row)
        root.addStretch()
