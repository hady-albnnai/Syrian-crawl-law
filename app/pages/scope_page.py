# -*- coding: utf-8 -*-
"""الشاشة 1 — النطاق: ماذا أجمع؟ (يكتب فعلياً بـapp.run_state.SETTINGS،
تقرأه شاشة التشغيل عند الضغط على «بدء الزحف» — لا حقول للعرض فقط).
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from app import core_data as md
from app.run_state import SETTINGS
from ._common import badge, card, page_header

_MODE_BY_INDEX = {0: "dry", 1: "limited", 2: "full"}


class ScopePage(QWidget):
    # يُبث عند الضغط «بدء الزحف» — MainWindow يربطه بالانتقال لشاشة التشغيل
    go_to_run = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header(
            "تحديد النطاق",
            "اختر المصدر والأقسام وحدود التشغيل — الخيار الآمن هو الافتراضي"))

        row = QHBoxLayout(); row.setSpacing(18)

        # بطاقة المصدر — المصادر المعتمدة فعلياً فقط (لا وهمية)
        src_card, sv = card("المصدر")
        self.combo = QComboBox()
        approved = md.APPROVED_SOURCES
        for name in approved:
            self.combo.addItem(name)
        sv.addWidget(self.combo)
        cred = md.SOURCE_CREDIBILITY
        cred_row = QHBoxLayout()
        cred_row.addWidget(badge(f"المصداقية {cred:.2f} — بوابة جودة صارمة",
                                 "badgeWarning"))
        cred_row.addStretch()
        sv.addLayout(cred_row)
        hint = QLabel("جميع المصادر المعتمدة فعلياً تدخل الطابور — "
                     "أضف المزيد من شاشة «استكشاف المصادر»")
        hint.setProperty("class", "hint")
        sv.addWidget(hint)
        src_card.setMinimumWidth(430)
        row.addWidget(src_card, 3)

        # بطاقة الحدود
        lim_card, lv = card("حدود التشغيل")
        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel("أقصى عدد صفحات:"))
        self.spin = QSpinBox(); self.spin.setRange(5, 5000)
        self.spin.setValue(SETTINGS.max_pages)
        pages_row.addWidget(self.spin); pages_row.addStretch()
        lv.addLayout(pages_row)
        modes = QHBoxLayout()
        self.m_dry = QRadioButton("تجريبي (بلا حفظ)")
        self.m_limited = QRadioButton("محدود")
        self.m_full = QRadioButton("كامل — بعد مراجعة النتائج")
        {"dry": self.m_dry, "limited": self.m_limited,
         "full": self.m_full}[SETTINGS.mode].setChecked(True)
        for m in (self.m_dry, self.m_limited, self.m_full):
            modes.addWidget(m)
        modes.addStretch()
        lv.addLayout(modes)
        row.addWidget(lim_card, 2)
        root.addLayout(row)

        # بطاقة الأقسام — من الطابور الفعلي (crawl_tasks.section) لا ثابتة
        sec_card, secv = card("الأقسام المكتشفة فعلياً")
        grid = QGridLayout(); grid.setSpacing(10)
        for i, name in enumerate(md.SECTIONS):
            cb = QCheckBox(name); cb.setChecked(True)
            grid.addWidget(cb, i // 2, i % 2)
        secv.addLayout(grid)
        root.addWidget(sec_card)

        self._applied = QLabel("")
        self._applied.setProperty("class", "hint")
        root.addWidget(self._applied)

        btn_row = QHBoxLayout()
        start = QPushButton("▶  حفظ الإعدادات والانتقال للتشغيل")
        start.setProperty("class", "primary")
        start.setMinimumHeight(48); start.setMinimumWidth(280)
        start.clicked.connect(self._apply_and_go)
        btn_row.addStretch(); btn_row.addWidget(start)
        root.addLayout(btn_row)
        root.addStretch()

    def _apply_and_go(self):
        SETTINGS.max_pages = self.spin.value()
        if self.m_dry.isChecked():
            SETTINGS.mode = "dry"
        elif self.m_limited.isChecked():
            SETTINGS.mode = "limited"
        else:
            SETTINGS.mode = "full"
        self._applied.setText(
            f"✓ حُفظ: {SETTINGS.max_pages} صفحة — وضع "
            f"{'تجريبي' if SETTINGS.mode == 'dry' else 'محدود' if SETTINGS.mode == 'limited' else 'كامل'}")
        self.go_to_run.emit()
