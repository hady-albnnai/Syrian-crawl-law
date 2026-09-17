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

        # جذر ميزان: يُسأل المستخدم ولا يُخترع مسار افتراضي — الكتابة على مستودع
        # آخر فعل صريح. config.MIZAN_ROOT أو MIZAN_ROOT بالمحيط يملآنه مسبقاً.
        row2 = QHBoxLayout(); row2.setSpacing(10)
        row2.addWidget(QLabel("جذر ميزان:"))
        self.mizan_root = QLineEdit(self._default_mizan_root())
        self.mizan_root.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mizan_root.setPlaceholderText(
            "جذر مستودع lawyer-office2 — المجلد الذي يحوي content/ "
            "(أو اضبط MIZAN_ROOT في config.py)")
        row2.addWidget(self.mizan_root, 1)
        self.pick_root_btn = QPushButton("اختيار المجلد")
        self.pick_root_btn.setProperty("class", "ghost")
        self.pick_root_btn.setMinimumWidth(112)
        self.pick_root_btn.setToolTip("اختر مجلد مستودع ميزان")
        self.pick_root_btn.clicked.connect(self._pick_mizan_root)
        row2.addWidget(self.pick_root_btn)
        av.addLayout(row2)

        btns = QHBoxLayout(); btns.setSpacing(10)
        self.build_btn = QPushButton("⟳  توليد الحزمة وقياس بوابتها")
        self.build_btn.setProperty("class", "primary")
        self.build_btn.clicked.connect(self._build_package)
        self.open_btn = QPushButton("فتح مجلد الحزمة")
        self.open_btn.setProperty("class", "ghost")
        self.open_btn.clicked.connect(self._open_folder)
        self.copy_btn = QPushButton("⇩  حقن في ميزان (فحص ثم دمج)")
        self.copy_btn.setProperty("class", "ghost")
        self.copy_btn.setToolTip(
            "لا ينسخ فوق فهرسهم: يدمج صفوفه مع صفوفك، ويطلب بوابة خضراء، "
            "ويكتب إيصالية بما جرى")
        self.copy_btn.clicked.connect(self._inject_into_mizan)
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

    @staticmethod
    def _default_mizan_root() -> str:
        try:
            from config import MIZAN_ROOT
            return MIZAN_ROOT or ""
        except Exception:  # noqa: BLE001 — الإعداد اختياري
            return ""

    def _pick_mizan_root(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "اختر جذر مستودع ميزان (المجلد الذي يحوي content/)",
            self.mizan_root.text().strip() or ".")
        if d:
            self.mizan_root.setText(d)

    def _inject_into_mizan(self) -> None:
        """معاينة → تأكيد صريح → تنفيذ. يرفض بوابة حمراء (بلا خيار صامت).

        الفرق عن «النسخ» الذي حلّ محله: النسخ كان يكتب فهرسنا فوق فهرسهم
        فيُيتّم صفوفهم (قِيست: 29 صفاً عندهم، منها 12 pdf لا يولّدها الزاحف).
        الحقن يدمج، ويحدّث ملفاتنا فقط، ويقيس الوجهة بعد الكتابة.
        """
        import mizan_injector as inj
        from PySide6.QtWidgets import QMessageBox
        src = self.out_dir.text().strip() or "export/content_package"
        root = self.mizan_root.text().strip()
        if not root:
            QMessageBox.information(
                self, "جذر ميزان", "اختر مجلد مستودع ميزان أولاً — لا مسار "
                "افتراضي مخبّأ ولا كتابة على مكان مجهول.")
            return
        try:
            plan = inj.plan(src, root)
        except (FileNotFoundError, OSError) as exc:
            self.status.setText(f"✗ {exc}")
            QMessageBox.warning(self, "تعذّرت المعاينة", str(exc))
            return
        self.copy_btn.setEnabled(False)
        try:
            if not plan["gate_green"]:
                self.status.setText(
                    "✗ البوابة حمراء — الحقن مرفوض. صحّح الحزمة أولًا "
                    "(`python -m cli verify`) أو استخدم `cli inject --force`.")
                QMessageBox.warning(self, "البوابة حمراء",
                                    "فحوص راسبة:\n• " + "\n• ".join(
                                        plan["gate_failed"]) +
                                    "\n\nالحقن بهذا الحالة يعني أن ميزان سيتخطى "
                                    "صفوفًا بصمت — منعتُه.")
                return
            answer = QMessageBox.question(
                self, "تأكيد الحقن في ميزان",
                inj.summarize(plan, for_write=True) +
                "\n\nيُكتب في الوجهة: ملفات markdown + فهرس مدموج + "
                "إيصالية. قاعدة بيانات ميزان لا تُمَسّ.")
            if answer != QMessageBox.Yes:
                self.status.setText("أُلغي الحقن — لم تُكتب أي بايتات")
                return
            rec = inj.apply(src, root, prefetch=plan)
            v = rec["verify_our_rows"]
            head = (f"✓ حُقن: {rec['rows']['added']} صفاً جديداً | "
                    f"{rec['files_written']} ملف | فهرس بعد الحقن "
                    f"{rec['rows']['index_rows_after']} صفاً")
            tail = (" | ⚠︎ قياس الوجهة: " + str(v["missing"][:3]) + str(
                v["sha_mismatch"][:3])) if not v["ok"] else ""
            note = ""
            if rec["rows"]["updated_same_path"]:
                note = (f" — {rec['rows']['updated_same_path']} وثيقة معدَّلة "
                        f"بنفس filePath ستُتخطى عند استيراد ميزان؛ انظر "
                        f"{inj.UPDATE_PLAN_NAME}")
            extra = ("\n\nما على ميزان أن يفعله: "
                     + rec["next_step_in_mizan"]) if rec.get(
                         "next_step_in_mizan") else ""
            self.status.setText(head + tail + note + extra)
            QMessageBox.information(self, "تمّ الحقن",
                                    head.replace(" | ", "\n") + note
                                    .replace(" — ", "\n") + extra)
        except Exception as exc:  # noqa: BLE001 — الشاشة تعرض العطل ولا تنهار
            self.status.setText(f"✗ تعذّر الحقن: {type(exc).__name__}: {exc}")
        finally:
            self.copy_btn.setEnabled(True)
            self.refresh()

    def _back(self) -> None:
        if self.on_back:
            self.on_back()
