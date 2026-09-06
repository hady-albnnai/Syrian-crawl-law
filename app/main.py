# -*- coding: utf-8 -*-
"""main.py — نقطة دخول حاصدة ميزان.

التشغيل:
    python -m app.main            # نافذة كاملة
    python -m app.main --smoke    # بناء وفحص ثم خروج (لـ CI)

إعادة تصميم الواجهة (٢٠٢٦-٠٩) اعتماداً على أفضل ممارسات موثقة (دليل
مايكروسوفت لتصميم واجهات سطح المكتب + الإفصاح التدريجي Progressive
Disclosure): كانت الواجهة السابقة تعرض ٨ شاشات متتالية أرهقت مستخدماً
عادياً (تحديد نطاق ثم تشغيل منفصلين لمهمة واحدة، واستكشاف/فجوات في
الواجهة الرئيسية رغم أن الأداة تنفذهما تلقائياً). التصميم الجديد:
  ١. البداية   — فعل رئيسي واحد «ابدأ الزحف الآن» بإعدادات افتراضية
     جاهزة؛ التفاصيل النادرة (المصدر/الحدود/الأقسام) خلف طيّة واحدة.
  ٢. المكتبة   — مراجعة ما جُمع.
  ٣. جواب موثَّق — السؤال المباشر بالاستشهاد.
  ٤. التصدير  — إخراج الحزمة لميزان.
  ٥. متقدّم    — تبويبات (استكشاف المصادر، الفجوات والتعلّم، الإعدادات)
     لمن يريد تدخلاً يدوياً؛ الأداة تُنفّذ هذه المهام تلقائياً بخلفية
     العمل دون الحاجة لأي تدخل من مستخدم عادي.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from app import theme
from app.pages import AdvancedPage, AnswerPage, ExportPage, HomePage, LibraryPage

PAGES = [
    ("البداية", HomePage),
    ("المكتبة والمراجعة", LibraryPage),
    ("جواب موثَّق", AnswerPage),
    ("التصدير لميزان", ExportPage),
    ("متقدّم", AdvancedPage),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("حاصدة ميزان — أداة جمع التشريعات السورية")
        self.resize(1280, 800)

        central = QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── الشريط الجانبي ──
        sidebar = QWidget(); sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(212)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(18, 24, 14, 18)
        sv.setSpacing(6)
        title = QLabel("⚖  حاصدة ميزان"); title.setObjectName("appTitle")
        subtitle = QLabel("أداة جمع التشريعات السورية"); subtitle.setObjectName("appSubtitle")
        sv.addWidget(title); sv.addWidget(subtitle)
        sv.addSpacing(18)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.nav_buttons = []
        for i, (label, _) in enumerate(PAGES):
            b = QPushButton(label)
            b.setProperty("class", "nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            self.nav_buttons.append(b)
            sv.addWidget(b)
        self.nav_buttons[0].setChecked(True)
        sv.addStretch()
        footer = QLabel("متصل بقاعدة البيانات والطابور الدائم — لا بيانات تجريبية")
        footer.setObjectName("sidebarFooter")
        sv.addWidget(footer)
        root.addWidget(sidebar)

        # ── الصفحات ──
        self.stack = QStackedWidget()
        self.page_instances = []
        for _, cls in PAGES:
            inst = cls()
            self.page_instances.append(inst)
            self.stack.addWidget(inst)
        root.addWidget(self.stack, 1)

        self.group.idClicked.connect(self._on_nav_clicked)

    def _on_nav_clicked(self, index: int):
        self.stack.setCurrentIndex(index)
        w = self.page_instances[index]
        if hasattr(w, "refresh"):
            w.refresh()

    def goto(self, index: int):
        self.nav_buttons[index].setChecked(True)
        self._on_nav_clicked(index)


def build_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    theme.register_fonts(app)
    app.setStyleSheet(theme.build_qss())
    return app


def main() -> int:
    app = build_app()
    win = MainWindow()
    win.show()
    if "--smoke" in sys.argv:
        for _ in range(5):
            app.processEvents()
        print("SMOKE OK — window built:", win.windowTitle())
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
