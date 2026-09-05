# -*- coding: utf-8 -*-
"""الشاشة 5 — الإعدادات: كيف تتصرف الأداة؟"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from ._common import card, page_header


def _slider_row(title: str, lo: int, hi: int, val: int) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
    head = QHBoxLayout()
    t = QLabel(title)
    val_lbl = QLabel(f"{val/10:.1f} ث")
    val_lbl.setStyleSheet("font-weight:700;")
    head.addWidget(t); head.addStretch(); head.addWidget(val_lbl)
    v.addLayout(head)
    s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(val)
    v.addWidget(s)
    return w


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("الإعدادات", "آداب الزحف والبيانات والإصدارات"))

        polite, pv = card("آداب الزحف — غير قابلة للتعطيل في إصدار التوزيع")
        pv.addWidget(_slider_row("الحد الأدنى للتأخير بين الطلبات", 5, 100, 20))
        pv.addWidget(_slider_row("الحد الأعلى للتأخير", 10, 200, 45))
        robots = QCheckBox("احترام robots.txt")
        robots.setChecked(True); robots.setEnabled(False)
        pv.addWidget(robots)
        note = QLabel("robots.txt مطبق فعلياً عبر RobotFileParser (دفعة P0) — تعطيله ممنوع دستورياً في الإنتاج")
        note.setProperty("class", "hint")
        pv.addWidget(note)
        ua_row = QHBoxLayout()
        ua_row.addWidget(QLabel("User-Agent:"))
        ua = QLineEdit("MizanHarvester/1.0 (Legal Archive; contact: …)")
        ua_row.addWidget(ua, 1)
        pv.addLayout(ua_row)
        root.addWidget(polite_card := polite)

        data, dv = card("البيانات")
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("مجلد البيانات:"))
        path = QLineEdit("C:\\Users\\Lawyer\\AppData\\Local\\MizanHarvester\\data")
        browse = QPushButton("استعراض…"); browse.setProperty("class", "ghost")
        d_row.addWidget(path, 1); d_row.addWidget(browse)
        dv.addLayout(d_row)
        hint = QLabel("قاعدة SQLite + snapshots الخام (خارج Git) + الحزم المولدة")
        hint.setProperty("class", "hint")
        dv.addWidget(hint)
        root.addWidget(data)

        ver, vv = card("الإصدارات")
        for k, v in [("حاصدة ميزان", "0.1.0 — نموذج أولي"),
                     ("المستخرج (extractor)", "v3.4"),
                     ("عقد حزمة ميزان", "1.0 (laws_decrees_index.csv)"),
                     ("Python / Qt", f"{sys.version_info.major}.{sys.version_info.minor} / Qt6")]:
            row = QHBoxLayout()
            kl = QLabel(k); kl.setStyleSheet("color:#6C757D;")
            vl = QLabel(v); vl.setStyleSheet("font-weight:700;")
            row.addWidget(kl); row.addStretch(); row.addWidget(vl)
            vv.addLayout(row)
        root.addWidget(ver)

        disclaimer = QLabel("تنبيه: النصوص المستخرجة مادة أرشيفية للبحث — ليست حكماً بالنفاذ أو التعديل أو الإلغاء (ROADMAP §4.4)")
        disclaimer.setProperty("class", "hint")
        root.addWidget(disclaimer)
        root.addStretch()
