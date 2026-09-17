# -*- coding: utf-8 -*-
"""pages/package_page.py — شاشة «الحزمة والتصدير» (وصل ما كان مقطوعاً).

علة وُجدت: طبقة البيانات كانت جاهزة بالكامل (`core_data.validate_package`،
`PACKAGE_TREE`، وعدادات الحزمة) ومختبَرة في `test_ui_wiring` — لكن عدد
استعمالها في الشاشات كان **صفرًا** منذ حذف الشاشات في 2026-09-06. فخرج كسر
دلالة sha256 في الفهرس بعد شهر من العمل، بينما الأداة كانت تملك فاحصاً
يكشفه ولا شاشة تعرضه.

هذه الشاشة لا «تُجمّل»: تعرض **نفس** فحوص البوابة التي يمشي عليها ميزان
(`verify_package.check_package` — نسخة مطابقة لسلوك
`csv_legal_library_importer.dart`)، وزرّاً يولّد الحزمة عبر `exporter` نفسه
(لا نسخة من المنطق هنا)، ومؤشراً صريحاً على ما سيدخل التطبيق: صفوف ومواد
معدودة **من القرص** لا من القاعدة.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header

SUCCESS = QColor("#28A745"); ERROR = QColor("#DC3545"); MUTED = QColor("#6C757D")


class PackagePage(QWidget):
    """توليد حزمة ميزان + بوابتها + شجرتها، بلا بيانات ثابتة."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_back = None
        self._build()
        # التحديث عند الفتح لا بالعدّاد — التصدير فعل المستخدم لا حالة حية
        self.refresh()

    # ──────────────────────────────────────────── البناء
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(page_header(
            "الحزمة والتصدير",
            "ما سيدخل ميزان بالضبط — الفحوص هنا هي فحوص مستورد التطبيق نفسها، "
            "لا نسخة أخفّ منها"))
        self.back_btn = QPushButton("◀  رجوع للبداية")
        self.back_btn.setProperty("class", "ghost")
        self.back_btn.clicked.connect(self._back)
        top.addStretch()
        top.addWidget(self.back_btn)
        root.addLayout(top)

        act, av = card()
        row = QHBoxLayout(); row.setSpacing(10)
        row.addWidget(QLabel("حدّ المواد الأدنى لكل وثيقة:"))
        self.min_articles = QSpinBox(); self.min_articles.setRange(0, 5000)
        self.min_articles.setValue(0)
        row.addWidget(self.min_articles)
        row.addWidget(QLabel("مجلد الحزمة:"))
        self.out_dir = QLineEdit("export/content_package")
        self.out_dir.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        row.addWidget(self.out_dir, 1)
        av.addLayout(row)

        btns = QHBoxLayout(); btns.setSpacing(10)
        self.build_btn = QPushButton("⟳  توليد الحزمة وقياس بوابتها")
        self.build_btn.setProperty("class", "primary")
        self.build_btn.clicked.connect(self._build_package)
        self.open_btn = QPushButton("فتح مجلد الحزمة")
        self.open_btn.setProperty("class", "ghost")
        self.open_btn.clicked.connect(self._open_folder)
        self.copy_btn = QPushButton("نسخ الحزمة إلى مجلد ميزان…")
        self.copy_btn.setProperty("class", "ghost")
        self.copy_btn.clicked.connect(self._copy_to_mizan)
        btns.addWidget(self.build_btn); btns.addWidget(self.open_btn)
        btns.addWidget(self.copy_btn); btns.addStretch()
        av.addLayout(btns)

        self.progress = QProgressBar(); self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        av.addWidget(self.progress)
        self.status = QLabel(""); self.status.setProperty("class", "hint")
        self.status.setWordWrap(True)
        av.addWidget(self.status)
        root.addWidget(act)

        nums, nv = card()
        row2 = QHBoxLayout(); row2.setSpacing(14)
        self.cards = {}
        for key, label in (("rows", "صفوف الفهرس"),
                           ("docs_with_json", "وثائق بعقد JSON"),
                           ("articles", "مواد داخل الحزمة"),
                           ("schema_version", "عقد الحزمة")):
            c = self._stat_card(label)
            self.cards[key] = c.findChild(QLabel, "value")
            row2.addWidget(c)
        row2.addStretch()
        nv.addLayout(row2)
        self.tree = QPlainTextEdit(); self.tree.setReadOnly(True)
        self.tree.setMaximumHeight(110)
        nv.addWidget(self.tree)
        root.addWidget(nums)

        gate, gv = card("بوابة الاستيراد في ميزان (planCsvImport)")
        self.gate_banner = QLabel("—")
        self.gate_banner.setProperty("class", "cardTitle")
        self.gate_banner.setWordWrap(True)
        gv.addWidget(self.gate_banner)
        self.checks = QPlainTextEdit(); self.checks.setReadOnly(True)
        gv.addWidget(self.checks)
        root.addWidget(gate, 1)

    @staticmethod
    def _stat_card(label: str) -> QFrame:
        c = QFrame(); c.setProperty("class", "card")
        v = QVBoxLayout(c); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(4)
        val = QLabel("—"); val.setObjectName("value")
        val.setProperty("class", "statValue"); val.setAlignment(Qt.AlignCenter)
        lab = QLabel(label); lab.setProperty("class", "statLabel")
        lab.setAlignment(Qt.AlignCenter)
        v.addWidget(val); v.addWidget(lab)
        return c

    # ──────────────────────────────────────────── القياس الحيّ
    def refresh(self) -> None:
        counts = md.package_counts()
        for key, val in (("rows", counts.get("rows", 0)),
                         ("docs_with_json", counts.get("docs_with_json", 0)),
                         ("articles", counts.get("articles", 0)),
                         ("schema_version", counts.get("schema_version")
                          or "v1 (بلا مانيفست)")):
            lab = self.cards.get(key)
            if lab is not None:
                lab.setText(str(val))
        self.tree.setPlainText("\n".join(t for t, _head in md.PACKAGE_TREE))
        checks = md.VALIDATION_CHECKS
        bad = [m for m, ok in checks if not ok]
        self.checks.setPlainText("\n".join(
            f"{'✓' if ok else '✗'}  {m}" for m, ok in checks))
        if not counts.get("rows"):
            self.gate_banner.setText(
                "الحزمة لم تولَّد بعد — اضغط «توليد الحزمة وقياس بوابتها»")
            self.gate_banner.setStyleSheet(f"color: {MUTED.name()};")
        elif bad:
            self.gate_banner.setText(
                f"✗ ميزان سيتخطى صفوفًا — {len(bad)} فحص راسب. لا تُسلِّم هذه الحزمة.")
            self.gate_banner.setStyleSheet(
                f"color: {ERROR.name()}; font-weight: 700;")
        else:
            self.gate_banner.setText(
                f"✓ كل الفحوص خضراء: {counts.get('rows', 0)} صَفًّا "
                f"و{counts.get('articles', 0)} مادة ستدخل ميزان")
            self.gate_banner.setStyleSheet(
                f"color: {SUCCESS.name()}; font-weight: 700;")

    # ──────────────────────────────────────────── الأفعال
    def _build_package(self) -> None:
        """توليد حقيقي عبر exporter نفسه — الحارس نفسه الذي يحرس CLI."""
        self.build_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText("جارٍ التوليد من القاعدة…")
        try:
            from config import DB_PATH
            from exporter import build_package
            out = self.out_dir.text().strip() or "export/content_package"
            rep = build_package(db_path=DB_PATH, out_dir=out,
                                min_articles=self.min_articles.value())
            manifest = rep.get("manifest") or {}
            self.status.setText(
                f"✓ {rep.get('docs', 0)} وثيقة | "
                f"{rep.get('articles_in_package', 0)} مادة معدودة من القرص | "
                + (f"مانيفست schema v{manifest.get('schema_version')} — "
                   f"{manifest.get('files', 0)} ملف"
                   if manifest else "بلا مانيفست")
                + (f"  ⚠︎ {rep['enrich_error']}" if rep.get("enrich_error") else ""))
        except Exception as exc:  # noqa: BLE001 — الشاشة تعرض العطل ولا تنهار
            self.status.setText(f"✗ تعذّر التوليد: {type(exc).__name__}: {exc}")
        finally:
            self.progress.setVisible(False)
            self.build_btn.setEnabled(True)
            self.refresh()

    def _open_folder(self) -> None:
        import subprocess
        import sys
        from pathlib import Path
        p = Path(self.out_dir.text().strip() or "export/content_package").resolve()
        if not p.exists():
            self.status.setText(f"✗ المجلد غير موجود: {p}")
            return
        cmd = ("explorer" if sys.platform.startswith("win")
               else "open" if sys.platform == "darwin" else "xdg-open")
        try:
            subprocess.Popen([cmd, str(p)])
            self.status.setText(f"فُتح: {p}")
        except OSError as exc:
            self.status.setText(f"✗ تعذّر فتح المجلد: {exc} — المسار: {p}")

    def _copy_to_mizan(self) -> None:
        """نسخ الحزمة إلى نسخة محلية من ميزان بعد تأكيد صريح.

        لا مسار افتراضي مخبّأ ولا كتابة صامتة على مستودع آخر: المستخدم يدخل
        الجذر بنفسه، والنسخ لا يلمس شيئاً خارج
        `content/legal_library/laws_decrees/`.
        """
        import shutil
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import verify_package

        src = Path(self.out_dir.text().strip() or "export/content_package")
        if not (src / "laws_decrees_index.csv").exists():
            self.status.setText("✗ لا حزمة في المصدر — ولِّدها أولاً")
            return
        root = QFileDialog.getExistingDirectory(
            self, "اختر جذر مستودع lawyer-office2")
        if not root:
            return
        if not verify_package.gate_ok(src):
            n_bad = sum(1 for _m, ok in verify_package.check_package(src) if not ok)
            if QMessageBox.question(
                    self, "البوابة حمراء",
                    f"الحزمة لا تجتاز بوابة ميزان ({n_bad} فحص راسب) — "
                    "ستتخطى صفوفًا عند الاستيراد.\n\nهل تنسخها رغم ذلك؟") \
                    != QMessageBox.Yes:
                self.status.setText("أُلغيت النسخة — صَحِّح البوابة أولاً "
                                    "(`python -m cli verify`)")
                return
        dst = Path(root) / "content" / "legal_library" / "laws_decrees"
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for item in ("laws_decrees_index.csv", "mizan_package_manifest.json"):
            f = src / item
            if f.exists():
                shutil.copy2(f, dst / item)
                n += 1
        s = src / "markdown"
        if s.exists():
            shutil.copytree(s, dst / "markdown", dirs_exist_ok=True)
            n += sum(1 for _p in s.iterdir())
        self.status.setText(
            f"✓ نُسخ {n} عنصراً إلى {dst} — شغّل ميزان (استيراد الفهرس) وراجع "
            f"تقرير lastImportReport في التطبيق: يجب أن يكون «استُورد "
            f"{self.cards['rows'].text()}» بلا تخطيات")

    def _back(self) -> None:
        if self.on_back:
            self.on_back()
