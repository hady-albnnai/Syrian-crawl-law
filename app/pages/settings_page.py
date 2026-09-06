# -*- coding: utf-8 -*-
"""تبويب «الإعدادات» (داخل شاشة متقدّم): كيف تتصرف الأداة؟ (بيانات حقيقية من config/core_data)

كانت هذه الشاشة تعرض مسار قاعدة بيانات وهمياً بالكامل (مسار ويندوز مُلفَّق
لا علاقة له بالمسار الفعلي) ورقم إصدار مختلَقاً يخالف pyproject.toml —
كلاهما استُبدل بقراءة حية من config.DB_PATH/config.VERSION.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(page_header("الإعدادات", "آداب الزحف والبيانات والإصدارات"))

        from config import DELAY_MAX, DELAY_MIN
        polite, pv = card("آداب الزحف — غير قابلة للتعطيل في إصدار التوزيع")
        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel(
            f"التأخير بين الطلبات: {DELAY_MIN:.1f} – {DELAY_MAX:.1f} ثانية "
            "(config.DELAY_MIN/DELAY_MAX)"))
        pv.addLayout(delay_row)
        robots = QCheckBox("احترام robots.txt")
        robots.setChecked(True); robots.setEnabled(False)
        pv.addWidget(robots)
        note = QLabel("robots.txt مطبق فعلياً عبر RobotFileParser — "
                      "تعطيله ممنوع دستورياً في الإنتاج")
        note.setProperty("class", "hint")
        pv.addWidget(note)
        ua_row = QHBoxLayout()
        ua_row.addWidget(QLabel("User-Agent:"))
        from config import USER_AGENT as _UA
        ua = QLineEdit(_UA); ua.setReadOnly(True)
        ua_row.addWidget(ua, 1)
        pv.addLayout(ua_row)
        root.addWidget(polite)

        data, dv = card("البيانات")
        self._db_path = QLineEdit(); self._db_path.setReadOnly(True)
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("مسار قاعدة البيانات الفعلي:"))
        d_row.addWidget(self._db_path, 1)
        dv.addLayout(d_row)
        self._db_meta = QLabel("")
        self._db_meta.setProperty("class", "hint")
        dv.addWidget(self._db_meta)
        root.addWidget(data)

        ver, self._vv = card("الإصدارات")
        root.addWidget(ver)

        disclaimer = QLabel("تنبيه: النصوص المستخرجة مادة أرشيفية للبحث — "
                            "ليست حكماً بالنفاذ أو التعديل أو الإلغاء")
        disclaimer.setProperty("class", "hint")
        root.addWidget(disclaimer)
        root.addStretch()

        self.refresh()

    def _clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def refresh(self):
        info = md.DB_INFO
        self._db_path.setText(info["path"])
        state = "موجودة" if info["exists"] else "لم تُنشأ بعد (شغّل init)"
        self._db_meta.setText(f"{state} — {info['size_mb']:.2f} MB")

        self._clear(self._vv)
        for k, v in [("حاصدة ميزان", f"{info['version']} — متصلة بالنواة"),
                     ("المستخرج (extractor)", "v4.0"),
                     ("عقد حزمة ميزان", "1.0 (laws_decrees_index.csv)"),
                     ("Python / Qt",
                      f"{sys.version_info.major}.{sys.version_info.minor} / Qt6")]:
            row = QHBoxLayout()
            kl = QLabel(k); kl.setStyleSheet("color:#6C757D;")
            vl = QLabel(v); vl.setStyleSheet("font-weight:700;")
            row.addWidget(kl); row.addStretch(); row.addWidget(vl)
            self._vv.addLayout(row)
