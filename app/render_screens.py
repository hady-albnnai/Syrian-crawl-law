# -*- coding: utf-8 -*-
"""render_screens.py — تصوير الشاشات دون شاشة عرض (offscreen) للتوثيق وCI.

الاستخدام:  QT_QPA_PLATFORM=offscreen python -m app.render_screens
"""
import sys
from pathlib import Path

from app.main import MainWindow, build_app

OUT = Path(__file__).parent.parent / "docs" / "screenshots"
# دفعة 3: الحزمة شاشة قائمة بذاتها — يجب أن تُصوَّر هي أيضاً (البوابة والعدادات
# هي ما يراه المالك قبل أن يرفع شيئاً إلى الميزان).
# دفعة 5: المصادر صارت شاشة — ما لم يُصوَّر لا يُصدَّق أنه موجود.
NAMES = ["01-home", "02-sources", "03-review", "04-package"]
# لقطة إضافية داخل شاشة: (فهرس الشاشة، فهرس التبويب، الاسم). بدونها تبقى
# شغل الدفعة السادسة (جدول الطابور في «تقريرat الدورات») غير مرئية في التوثيق.
EXTRA: list[tuple[int, int, str]] = [(2, 2, "03b-review-reports")]


def main() -> int:
    app = build_app()
    win = MainWindow()
    win.resize(1360, 860)
    win.show()
    OUT.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(NAMES):
        win.goto(i)
        for _ in range(4):
            app.processEvents()
        pix = win.grab()
        path = OUT / f"{name}.png"
        pix.save(str(path))
        print(f"saved {path}")
    for page_i, tab_i, name in EXTRA:
        win.goto(page_i)
        tabs = getattr(win.stack.currentWidget(), "tabs", None)
        if tabs is None or tab_i >= tabs.count():
            print(f"⊘ تخطيت {name}: لا تبويب برقم {tab_i}")
            continue
        tabs.setCurrentIndex(tab_i)
        for _ in range(4):
            app.processEvents()
        path = OUT / f"{name}.png"
        win.grab().save(str(path))
        print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
