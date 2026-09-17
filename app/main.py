# -*- coding: utf-8 -*-
"""main.py — نقطة دخول حاصدة ميزان.

التشغيل:
    python -m app.main            # نافذة كاملة
    python -m app.main --smoke    # بناء وفحص ثم خروج (لـ CI)

تصميم الواجهة (2026-09-06 — تصميم مباشر من المالك): شاشتان فقط بلا
قائمة جانبية تقليدية — تدفّق خطي واحد:

  البداية (ابدأ الزحف / إيقاف / نتائج الزحف)
       │  الأداة تكتشف مصادرها بنفسها تلقائياً وتزحف بلا أي اختيار مسبق
       ▼
  نتائج الزحف (قائمة + معاينة نص كامل + موافقة/رفض لكل نتيجة)
       │  زر «اعتماد وتجهيز لميزان» مؤجَّل عمداً لمرحلة لاحقة (بعد
       │  استقرار دقّة الزحف وتحديد صيغة الاستيراد الفعلية لميزان)
       ▼
  رجوع للبداية

كل الشاشات الإضافية السابقة (المكتبة، جواب موثَّق، التصدير، استكشاف
المصادر، الفجوات والتعلّم، الإعدادات) أُزيلت بقرار صريح من المالك: لا
حاجة لها بهذه المرحلة — التركيز الآن فقط على دقّة نتائج الزحف نفسها.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,
                               QWidget, QVBoxLayout)

from app import theme
from app.pages import HomePage, PackagePage, ReviewPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("حاصدة ميزان — أداة جمع التشريعات السورية")
        self.resize(1280, 800)

        central = QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.home = HomePage()
        self.review = ReviewPage()
        self.package = PackagePage()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.review)
        self.stack.addWidget(self.package)

        self.home.on_open_results = self._open_results
        self.review.on_back = self._back_home
        # «اعتماد وتجهيز لميزان» لم يعد زراً معطَّلاً بلا فعل: صار بوابة
        # الحزمة نفسها (توليد + فحص بمعايير ميزان + نسخ)، لأن القرار الذي
        # كان مؤجِّلاً — صيغة الاستيراد — حُسم وقيس (ADR-001 + تصحيح sha256)
        self.review.on_open_package = self._open_package
        self.package.on_back = self._back_home

    def _open_results(self):
        self.review.refresh()
        self.stack.setCurrentWidget(self.review)

    def _back_home(self):
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def _open_package(self):
        self.package.refresh()
        self.stack.setCurrentWidget(self.package)

    def goto(self, index: int):
        """للتوافق مع render_screens.py: 0=البداية، 1=النتائج، 2=الحزمة."""
        pages = (self._back_home, self._open_results, self._open_package)
        pages[index if 0 <= index < len(pages) else 0]()


def build_app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    theme.register_fonts(app)
    app.setStyleSheet(theme.build_qss())
    return app


def main() -> int:
    # أول إقلاع على جهاز جديد: القاعدة قد لا تكون موجودة — لا نطلب من
    # المالك تشغيل `cli init` يدوياً (كان الإقلاع ينهار بـ
    # OperationalError: no such table). create_tables() idempotent أصلاً.
    try:
        from database import create_tables
        create_tables()
    except Exception as exc:  # noqa: BLE001 — تُعرض في الشاشة لا هنا
        print(f"⚠︎ تعذّر تهيئة القاعدة: {type(exc).__name__}: {exc}")
    app = build_app()
    win = MainWindow()
    win.show()
    if "--smoke" in sys.argv:
        for _ in range(5):
            app.processEvents()
        print("SMOKE OK — window built:", win.windowTitle())
        if "--smoke-all" in sys.argv:
            # كل شاشة تُبنى وتُحدَّث فعلاً — لا «نافذة تعمل» وتبويبات مكسورة
            for i, name in enumerate(("البداية", "النتائج", "الحزمة")):
                win.goto(i)
                for _ in range(3):
                    app.processEvents()
                w = win.stack.currentWidget()
                refresh = getattr(w, "refresh", None)
                if callable(refresh):
                    refresh()
                for _ in range(3):
                    app.processEvents()
                print(f"  ✓ {name} — {type(w).__name__}")
            tabs = win.review.tabs.count()
            assert tabs == 3, f"توقعنا 3 تبويبات في شاشة المراجعة، لا {tabs}"
            print(f"SMOKE OK — شاشة المراجعة: {tabs} تبويبات؛ "
                  f"أعمدة القائمة: {win.review.model.columnCount()}")
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
