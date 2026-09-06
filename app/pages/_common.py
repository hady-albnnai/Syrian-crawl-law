# -*- coding: utf-8 -*-
"""عناصر مشتركة بين الشاشات."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)


def page_header(title: str, subtitle: str) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    t = QLabel(title); t.setObjectName("pageTitle")
    s = QLabel(subtitle); s.setObjectName("pageSubtitle")
    v.addWidget(t); v.addWidget(s)
    return w


def card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    c = QFrame(); c.setObjectName("card"); c.setProperty("class", "card")
    c.setProperty("class", "card")
    v = QVBoxLayout(c)
    v.setContentsMargins(20, 18, 20, 18)
    v.setSpacing(10)
    if title:
        lbl = QLabel(title); lbl.setProperty("class", "cardTitle")
        v.addWidget(lbl)
    return c, v


def badge(text: str, cls: str) -> QWidget:
    lbl = QLabel(text); lbl.setProperty("class", cls)
    holder = QWidget()
    h = QHBoxLayout(holder); h.setContentsMargins(0, 0, 0, 0)
    h.addStretch(); h.addWidget(lbl); h.addStretch()
    return holder


def apply_card_style():
    """يضمن تطبيق نمط .card بعد setProperty الديناميكي."""
    pass


class Collapsible(QWidget):
    """قسم قابل للطي — الإفصاح التدريجي (Progressive Disclosure):
    يُخفي التفاصيل المتقدمة التي لا يحتاجها المستخدم العادي افتراضياً،
    ويكشفها بضغطة واحدة عند الحاجة فعلاً (طبقة إخفاء واحدة، لا أكثر).
    """

    def __init__(self, title: str = "خيارات متقدّمة", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self._btn = QPushButton(f"▸  {title}")
        self._btn.setProperty("class", "ghost")
        self._btn.setCheckable(True)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.toggled.connect(self._on_toggled)
        v.addWidget(self._btn)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 8, 4, 0)
        self.body_layout.setSpacing(10)
        self.body.setVisible(False)
        v.addWidget(self.body)

        self._title = title

    def _on_toggled(self, checked: bool):
        self.body.setVisible(checked)
        arrow = "▾" if checked else "▸"
        self._btn.setText(f"{arrow}  {self._title}")

    def addWidget(self, w):
        self.body_layout.addWidget(w)

    def addLayout(self, lay):
        self.body_layout.addLayout(lay)
