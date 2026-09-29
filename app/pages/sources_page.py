# -*- coding: utf-8 -*-
"""pages/sources_page.py — شاشة «المصادر»: اعتماد المصدر قرار، لا أثر جانبي.

علة وُجدت (من دفعة 3 وإغلاقها الآن): لما صار «اعتماد المصادر المكتشفة
تلقائياً» مطفأ افتراضياً — وهو الصواب لأن السياسة الموثقة أن اعتماد مصدر قرار
المالك (‏`discovery.decide_source`: «لا زحف قبل approve») — لم تعد الواجهة تملك
أي طريقة لاعتماد مصدر: المعلّقات تتراكم ولا يُنظر إليها إلا من الطرفية
(`cli sources list|approve`). شاشة «الحزمة» أغلقت حلقة التسليم؛ هذه تغلق حلقة
**الإدخال**.

مبدأ متبع من دفعة 3: لا منطق ثانٍ هنا. الاعتماد/الرفض يمرّان عبر
`core_data.decide_sources` التي تندب `discovery.decide_source` — نفس ما
يستدعيه `cli sources`، بنفس `decided_by` المسجل، فلا ينفصل مساران للقرار.
"""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from app import core_data as md
from ._common import card, page_header

COLUMNS = [
    ("الحالة", "status"),
    ("المصدر", "name"),
    ("النطاق", "base_url"),
    ("المحرك", "engine"),
    ("الوثائق", "docs"),
    ("الجدارة", "credibility"),
    ("التير", "domain_tier"),
    ("قرار", "decided_by"),
    ("التقييم الآلي", "evaluation_score"),
]
STATUS_AR = {"proposed": "معلّق", "approved": "معتمد ✓", "rejected": "مرفوض ✗",
             "auto_approved": "معتمد آلياً", "seed": "بذرة"}


class _SourceModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        key = COLUMNS[index.column()][1]
        if role == Qt.ToolTipRole and key == "evaluation_score":
            import json
            try:
                reasons = json.loads(r.get("evaluation_reasons_json") or "[]")
            except (TypeError, ValueError):
                reasons = []
            return "\n".join(reasons) or None
        if role != Qt.DisplayRole:
            return None
        v = r.get(key)
        if key == "status":
            return STATUS_AR.get(v, v or "—")
        if key == "credibility":
            return f"{v:.2f}" if isinstance(v, (int, float)) else "—"
        if key == "evaluation_score":
            if not isinstance(v, (int, float)):
                return "لم يُقيّم"
            types = {"legislation": "تشريعات", "precedent": "اجتهادات",
                     "mixed": "مختلط", "potential_legal": "قانوني محتمل",
                     "nonlegal": "غير قانوني", "unknown": "غير محدد"}
            verdicts = {"recommended": "موصى به", "needs_review": "تدقيق",
                        "rejected": "ضعيف الصلة", "blocked": "محجوب"}
            return (f"{v:.0f}/100 · "
                    f"{types.get(r.get('source_type'), r.get('source_type') or '—')} · "
                    f"{verdicts.get(r.get('evaluation_verdict'), '—')}")
        if key == "domain_tier":
            return f"تير {v}" if v not in (None, "") else "—"
        if key in ("docs",):
            return str(v or 0)
        if key == "decided_by":
            return {"user": "المالك", "auto": "طيار آلي",
                    "ui": "الواجهة"}.get(v, v or "لم يُحسم")
        return str(v) if v not in (None, "") else "—"

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section][0]
        return None

    def source_id(self, row: int):
        return self._rows[row].get("id") if 0 <= row < len(self._rows) else None


class SourcesPage(QWidget):
    """لائحة المصادر المعلّقة/المعتمدة/المرفوضة + اعتماد ورفض جماعي."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_back = None
        self._build()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(6000)        # الطابور يتغيّر أثناء الدورة
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(page_header(
            "المصادر",
            "ما يُسمح للزاحف أن يجمع منه — اعتماد المصدر قرار المالك، "
            "وهو نفسه قرار «cli sources» لا نسخة أخفّ منه"))
        self.back_btn = QPushButton("◀  رجوع للبداية")
        self.back_btn.setProperty("class", "ghost")
        self.back_btn.clicked.connect(self._back)
        top.addStretch(); top.addWidget(self.back_btn)
        root.addLayout(top)

        bar, bv = card()
        row = QHBoxLayout(); row.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو النطاق…")
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        row.addWidget(QLabel("الحالة:"))
        self.filter = QComboBox()
        self.filter.addItems(list(md.SOURCE_FILTERS.keys()))
        self.filter.currentTextChanged.connect(self.refresh)
        row.addWidget(self.filter)
        bv.addLayout(row)

        btns = QHBoxLayout(); btns.setSpacing(10)
        self.approve_btn = QPushButton("✓  اعتماد المحدد (يزحف منه)")
        self.approve_btn.setProperty("class", "primary")
        self.approve_btn.clicked.connect(lambda: self._decide(True))
        self.reject_btn = QPushButton("✗  رفض المحدد")
        self.reject_btn.setProperty("class", "ghost")
        self.reject_btn.clicked.connect(lambda: self._decide(False))
        self.reload_btn = QPushButton("⟳  إعادة القراءة")
        self.reload_btn.setProperty("class", "ghost")
        self.reload_btn.clicked.connect(self.refresh)
        btns.addWidget(self.approve_btn); btns.addWidget(self.reject_btn)
        btns.addWidget(self.reload_btn); btns.addStretch()
        bv.addLayout(btns)

        self.note = QLabel(""); self.note.setProperty("class", "hint")
        self.note.setWordWrap(True)
        bv.addWidget(self.note)
        root.addWidget(bar)

        table_card, tv = card()
        self.model = _SourceModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.view.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.view.verticalHeader().setVisible(False)
        tv.addWidget(self.view)
        root.addWidget(table_card, 1)

    # ─────────────────────────────────────────────────────── القياس الحيّ
    def refresh(self) -> None:
        status = md.SOURCE_FILTERS.get(self.filter.currentText(), "")
        rows = md.source_rows(status=status, needle=self.search.text().strip())
        self.model.set_rows(rows)
        st = md.sources_stats()
        line = (f"المصادر: {st['total']} — معلّق للاعتماد {st['proposed']} | "
                f"معتمد {st['approved']} | مرفوض {st['rejected']}. "
                "«معلّق» يعني أن الزاحف لا يزحف منه (لا زحف قبل اعتماد — "
                "الخيار الآمن افتراضياً). الاعتماد يضيفه لطابور الدورة القادمة.")
        if not rows:
            line += "  —  لا مصدر بهذه الحالة/البحث الآن."
        self.note.setText(line)

    # ─────────────────────────────────────────────────────── الأفعال
    def _selected_ids(self) -> list[int]:
        """الصفوف المحددة فقط، بترتيب id — لا «الصفّ الجاري» احتياطاً.

        قياس 2026-09-17 (offscreen، PySide6 6.11): بسلوك SelectRows يجعل
        `setCurrentIndex` الصفَّ محدَّداً بنفسه؛ ثم `clearSelection` (أو
        Ctrl+click على صفّ محدد) يُبقي **المؤشر صالحاً والتحديد فارغاً**. حالة
        «مؤشر بلا تحديد» موجودة إذاً، وهي بالضبط ما لا يجوز أن يمرّر قرار
        مصدر — لذا تُرفض بصوت عالٍ بدل أن تُفعل على صفّ أزاحه المستعمل عمداً.
        """
        rows = {idx.row() for idx in self.view.selectionModel().selectedRows()}
        ids = []
        for r in sorted(rows):
            sid = self.model.source_id(r)
            if sid is not None:
                ids.append(int(sid))
        return ids

    def _decide(self, approve: bool) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "لا تحديد",
                                    "ظلّل صفاً أو أكثر من اللائحة أولاً.")
            return
        verb = "اعتماد" if approve else "رفض"
        extra = ("" if approve else
                 "\nالمرفوض لا يُزحف منه، ويبقى مسجلاً بلا حذف — للمراجعة لاحقاً.")
        if QMessageBox.question(
                self, f"تأكيد ال{verb}",
                f"سيُنفَّذ {verb} على {len(ids)} مصدر عبر نفس دالة "
                f"`cli sources {'approve' if approve else 'reject'}`."
                + extra) != QMessageBox.Yes:
            self.note.setText(f"أُلغي — لا تغيير على {len(ids)} مصدر")
            return
        res = md.decide_sources(ids, approve)
        if res.get("error"):
            QMessageBox.warning(self, "تعذّر القرار", str(res["error"]))
        self.refresh()
        self.note.setText(
            f"{'✓ اعتمد' if approve else '✓ رُفض'} {res.get('changed', 0)} "
            f"مصدر" + (f" (تعذّر إيجاد: {res['missing']})"
                        if res.get("missing") else "") +
            " — القرار مسجل بـ`decided_by='ui'`.")

    def _back(self) -> None:
        if self.on_back:
            self.on_back()
