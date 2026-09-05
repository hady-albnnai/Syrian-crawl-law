# -*- coding: utf-8 -*-
"""render_screens.py — تصوير الشاشات دون شاشة عرض (offscreen) للتوثيق وCI.

الاستخدام:  QT_QPA_PLATFORM=offscreen python -m app.render_screens
"""
import sys
from pathlib import Path

from app.main import PAGES, MainWindow, build_app

OUT = Path(__file__).parent.parent / "docs" / "screenshots"
NAMES = ["01-discovery", "02-scope", "03-run", "04-library", "05-export", "06-settings"]


def main() -> int:
    app = build_app()
    win = MainWindow()
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
