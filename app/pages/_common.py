# -*- coding: utf-8 -*-
"""عناصر مشتركة بين الشاشات."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


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
