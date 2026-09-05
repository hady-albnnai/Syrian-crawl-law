# -*- coding: utf-8 -*-
"""الشاشة 4 — التصدير: توليد فعلي لحزمة ميزان + بوابة تحقق حقيقية."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from app import core_data as md
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

        self.stats_row = QHBoxLayout(); self.stats_row.setSpacing(16)
        root.addLayout(self.stats_row)

        row = QHBoxLayout(); row.setSpacing(18)
        tree_card, self.tv = card("معاينة الحزمة")
        row.addWidget(tree_card, 3)
        val_card, self.vv = card("بوابة التحقق")
        row.addWidget(val_card, 2)
        root.addLayout(row, 1)

        btns = QHBoxLayout()
        self.gen = QPushButton("توليد الحزمة  ◀"); self.gen.setProperty("class", "gold")
        self.gen.setMinimumHeight(48); self.gen.setMinimumWidth(220)
        self.gen.clicked.connect(self._generate)
        folder = QPushButton("فتح مجلد الحزم"); folder.setProperty("class", "ghost")
        folder.clicked.connect(self._open_folder)
        btns.addStretch(); btns.addWidget(folder); btns.addWidget(self.gen)
        root.addLayout(btns)

        hint = QLabel("بعد التوليد: انسخ المجلد إلى ميزان — الاستيراد التلقائي يحتاج مستورد CSV في ميزان (موثق في ADR-001)")
        hint.setProperty("class", "hint")
        root.addWidget(hint)

        self.refresh()

    def _clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def refresh(self):
        s = md.RUN_STATS or {}
        q = s.get("queue", {})
        self._clear(self.stats_row)
        self.stats_row.addWidget(_stat(str(s.get("docs", 0)), "وثائق في القاعدة"))
        self.stats_row.addWidget(_stat(str(s.get("articles", 0)), "مواد مستخرجة"))
        self.stats_row.addWidget(_stat(str(q.get("needs_review", 0)),
                                       "تحتاج مراجعة (تُستثنى آلياً)", "#DC3545"))
        self._clear(self.tv)
        for line, is_root in md.PACKAGE_TREE:
            lbl = QLabel(line)
            lbl.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
            if is_root:
                lbl.setStyleSheet(lbl.styleSheet() + " font-weight: 800;")
            self.tv.addWidget(lbl)
        self.tv.addStretch()
        self._clear(self.vv)
        for text, ok in md.VALIDATION_CHECKS:
            mark = "✓" if ok else "✗"
            color = "#28A745" if ok else "#DC3545"
            item = QLabel(f'<span style="color:{color}; font-weight:800;">{mark}</span>  {text}')
            self.vv.addWidget(item)
        self.vv.addStretch()

    def _generate(self):
        from exporter import build_package
        self.gen.setEnabled(False); self.gen.setText("جارٍ التوليد…")
        try:
            build_package()  # نفس مسار cli export — مصدر حقيقة واحد
        finally:
            self.gen.setEnabled(True); self.gen.setText("توليد الحزمة  ◀")
        self.refresh()

    def _open_folder(self):
        target = md.PACKAGE_DIR if md.PACKAGE_DIR.exists() else Path(".")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))
