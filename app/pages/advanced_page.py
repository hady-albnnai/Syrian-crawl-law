# -*- coding: utf-8 -*-
"""شاشة «متقدّم» — تجميع الأقسام النادر استخدامها من المستخدم العادي:
استكشاف المصادر يدوياً، تحليل الفجوات والتعلّم، والإعدادات التقنية.

تطبيقاً لمبدأ «ركّز على المرجَّح، أخفِ غير المرجَّح» (Microsoft UX Guide):
هذه المهام تفعلها الأداة تلقائياً بالخلفية (الطيار الآلي عند كل دورة زحف)،
فلا حاجة لعرضها في التنقّل الرئيسي — تبقى متاحة هنا لمن يريد التدقيق
أو التدخل اليدوي، دون إرباك الشاشة الرئيسية.
"""
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .discovery_page import DiscoveryPage
from .insights_page import InsightsPage
from .settings_page import SettingsPage
from ._common import page_header


class AdvancedPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 16)
        root.setSpacing(12)
        root.addWidget(page_header(
            "متقدّم",
            "أقسام للتدخل اليدوي والتدقيق — الأداة تنفّذها تلقائياً بلا تدخل عادةً"))

        self.tabs = QTabWidget()
        self.discovery = DiscoveryPage()
        self.insights = InsightsPage()
        self.settings = SettingsPage()
        self.tabs.addTab(self.discovery, "استكشاف المصادر")
        self.tabs.addTab(self.insights, "الفجوات والتعلّم")
        self.tabs.addTab(self.settings, "الإعدادات")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

    def _on_tab_changed(self, index: int):
        w = self.tabs.widget(index)
        if hasattr(w, "refresh"):
            w.refresh()

    def refresh(self):
        self._on_tab_changed(self.tabs.currentIndex())
