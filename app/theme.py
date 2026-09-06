# -*- coding: utf-8 -*-
"""theme.py — الهوية البصرية لحاصدة ميزان.

الألوان مطابقة لدستور ميزان (CONSTITUTION.md في lawyer-office2):
كحلي + ذهبي فقط، وبطاقات بيضاء بنصف قطر ≥ 16، وألوان الحالة وظيفية فقط.
"""
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ── ألوان الدستور ──
PRIMARY_NAVY = "#1A2332"
NAVY_LIGHT = "#243044"
NAVY_LIGHTER = "#2E3D57"
SECONDARY_GOLD = "#C9A961"
GOLD_DARK = "#A8893F"
CARD_BG = "#FFFFFF"
APP_BG = "#F4F5F7"
TEXT_PRIMARY = "#2C3E50"
TEXT_SECONDARY = "#6C757D"
SUCCESS = "#28A745"
ERROR = "#DC3545"
WARNING = "#FFC107"
INFO = "#17A2B8"

def _assets_fonts_dir() -> Path:
    """مسار الخطوط يعمل مصدراً ومجمداً (PyInstaller onedir)."""
    here = Path(__file__).parent / "assets" / "fonts"
    if here.exists():
        return here
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "app" / "assets" / "fonts"
        if frozen.exists():
            return frozen
    return here


FONT_DIR = _assets_fonts_dir()
FONT_FAMILY = "Noto Naskh Arabic"
FALLBACK_FAMILIES = ["Segoe UI", "Tahoma", "Arial"]


def register_fonts(app: QApplication) -> str:
    """يسجل الخط العربي المرفق ويعيد اسم العائلة الفعلية المستخدمة.

    على Windows توجد خطوط عربية نظامية، لكن الخط المرفق يضمن تطابق
    المظهر بين لقطات CI وجهاز المستخدم.
    """
    for ttf in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))
    available = set(QFontDatabase.families())
    family = FONT_FAMILY if FONT_FAMILY in available else (
        next((f for f in FALLBACK_FAMILIES if f in available), app.font().family()))
    font = QFont(family, 11)
    app.setFont(font)
    return family


def build_qss() -> str:
    return f"""
    * {{ font-family: "{FONT_FAMILY}", "Segoe UI", "Tahoma"; }}
    QMainWindow, QWidget#central {{ background: {APP_BG}; }}

    /* ── الشريط الجانبي ── */
    QWidget#sidebar {{ background: {PRIMARY_NAVY}; }}
    QLabel#appTitle {{ color: {SECONDARY_GOLD}; font-size: 21px; font-weight: 700; }}
    QLabel#appSubtitle {{ color: #8B96A8; font-size: 11.5px; }}
    QPushButton.nav {{
        background: transparent; color: #C7CEDA; border: none;
        text-align: right; padding: 12px 18px; font-size: 13.5px; border-radius: 12px;
    }}
    QPushButton.nav:hover {{ background: {NAVY_LIGHT}; color: #FFFFFF; }}
    QPushButton.nav:checked {{
        background: {NAVY_LIGHTER}; color: {SECONDARY_GOLD};
        font-weight: 700; border-right: 4px solid {SECONDARY_GOLD};
    }}
    QLabel#sidebarFooter {{ color: #5A6578; font-size: 10px; }}

    /* ── البطاقات ── */
    QFrame.card {{
        background: {CARD_BG}; border: 1px solid #E4E7EC; border-radius: 16px;
    }}
    QLabel.cardTitle {{ color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; }}
    QLabel.hint {{ color: {TEXT_SECONDARY}; font-size: 11.5px; }}
    QLabel.pageTitle {{ color: {TEXT_PRIMARY}; font-size: 22px; font-weight: 700; }}
    QLabel.pageSubtitle {{ color: {TEXT_SECONDARY}; font-size: 12.5px; }}

    /* ── الإدخالات ── */
    QComboBox, QLineEdit, QSpinBox {{
        background: #FFFFFF; border: 1.5px solid #D6DAE1; border-radius: 10px;
        padding: 8px 12px; color: {TEXT_PRIMARY}; font-size: 12.5px;
    }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {SECONDARY_GOLD}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QCheckBox {{ color: {TEXT_PRIMARY}; font-size: 12.5px; spacing: 8px; }}
    QRadioButton {{ color: {TEXT_PRIMARY}; font-size: 12.5px; spacing: 8px; }}

    /* ── الأزرار ── */
    QPushButton.primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {PRIMARY_NAVY}, stop:1 {NAVY_LIGHTER});
        color: {SECONDARY_GOLD}; border: none; border-radius: 12px;
        padding: 12px 28px; font-size: 14px; font-weight: 700;
    }}
    QPushButton.primary:hover {{ background: {NAVY_LIGHTER}; }}
    QPushButton.primary:disabled {{ background: #B9BFC9; color: #EDF0F4; }}
    QPushButton.gold {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {SECONDARY_GOLD}, stop:1 {GOLD_DARK});
        color: {PRIMARY_NAVY}; border: none; border-radius: 12px;
        padding: 12px 28px; font-size: 14px; font-weight: 700;
    }}
    QPushButton.ghost {{
        background: transparent; color: {TEXT_SECONDARY};
        border: 1.5px solid #D6DAE1; border-radius: 12px; padding: 9px 20px; font-size: 12.5px;
    }}
    QPushButton.ghost:hover {{ border-color: {SECONDARY_GOLD}; color: {TEXT_PRIMARY}; }}

    /* ── الإحصاءات والتقدم ── */
    QLabel.statValue {{ color: {PRIMARY_NAVY}; font-size: 26px; font-weight: 800; }}
    QLabel.statLabel {{ color: {TEXT_SECONDARY}; font-size: 11.5px; }}
    QProgressBar {{
        background: #E9ECF1; border: none; border-radius: 9px;
        height: 18px; text-align: center; color: {PRIMARY_NAVY}; font-weight: 700;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {SECONDARY_GOLD}, stop:1 {GOLD_DARK});
        border-radius: 9px;
    }}

    /* ── الجداول ── */
    QTableWidget {{
        background: {CARD_BG}; border: none; gridline-color: #EDF0F4;
        color: {TEXT_PRIMARY}; font-size: 12.5px;
    }}
    QTableWidget::item {{ padding: 8px; }}
    QTableWidget::item:selected {{ background: #F2EDDF; color: {PRIMARY_NAVY}; }}
    QHeaderView::section {{
        background: {PRIMARY_NAVY}; color: {SECONDARY_GOLD}; border: none;
        padding: 9px; font-size: 12px; font-weight: 700;
    }}

    /* ── السجل ── */
    QPlainTextEdit#logView {{
        background: {PRIMARY_NAVY}; color: #C7CEDA; border: none; border-radius: 12px;
        font-family: "Consolas", "Courier New", monospace; font-size: 11.5px; padding: 10px;
    }}

    /* ── الشارات ── */
    QLabel.badgeSuccess {{ background: #E7F6EC; color: {SUCCESS}; border-radius: 9px;
        padding: 3px 10px; font-size: 11px; font-weight: 700; }}
    QLabel.badgeWarning {{ background: #FFF6DF; color: #9A7B0A; border-radius: 9px;
        padding: 3px 10px; font-size: 11px; font-weight: 700; }}
    QLabel.badgeError {{ background: #FDE9EA; color: {ERROR}; border-radius: 9px;
        padding: 3px 10px; font-size: 11px; font-weight: 700; }}
    QLabel.badgeInfo {{ background: #E4F4F7; color: {INFO}; border-radius: 9px;
        padding: 3px 10px; font-size: 11px; font-weight: 700; }}

    QSlider::groove:horizontal {{ height: 6px; background: #E4E7EC; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: {SECONDARY_GOLD}; width: 18px; height: 18px;
        margin: -6px 0; border-radius: 9px;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: #C9CFD8; border-radius: 5px; min-height: 30px; }}

    /* ── التبويبات (شاشة متقدّم) ── */
    QTabWidget::pane {{ border: 1px solid #E4E7EC; border-radius: 12px; background: {CARD_BG}; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {TEXT_SECONDARY}; padding: 10px 18px;
        font-size: 12.5px; font-weight: 600; border: none;
    }}
    QTabBar::tab:selected {{ color: {PRIMARY_NAVY}; border-bottom: 3px solid {SECONDARY_GOLD}; }}
    QTabBar::tab:hover {{ color: {PRIMARY_NAVY}; }}
    """
