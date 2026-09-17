# -*- coding: utf-8 -*-
"""شاشة «نتائج الزحف» — المراجعة + صورة المتن + تقارير الدورات.

التصميم من المالك (2026-09-06): شاشتان لا خمس، والتسلسل خطّي
(البداية ← النتائج). هذا الملف لا ينقض ذلك: يبقى صفّان أساسيان —
«النتائج» و«الحزمة» — وما يُضاف هنا **تبويبات داخل نفس الشاشة** لبيانات
محفوظة أصلاً ولا شاشة لها (طلب المالك 2026-09-17: قسم تقارير لسجل الدورات
وتوزيع أسباب الفشل — البيانات جاهزة في crawl_runs وcrawl_tasks.last_error).

ما تغيّر جوهرياً (وليس شكلياً) — ثلاث علل مقاسة:
 1) الجدول كان QTableWidget يُعاد بناؤه كاملاً كل 4 ثوانٍ؛ صار نموذجاً
    (QAbstractTableModel) + QSortFilterProxyModel: إعادة البناء عند تغيّر
    البيانات فقط، مع بحث وترشيح وتعدّد تحديد وفرز بالنقر.
 2) المعاينة كانت تقرأ clean_content كاملاً (حتى 2,000,000 حرف) في محرر
    نص عند كل نقرة؛ صارت مثقلة كسولياً بسقف معلن (document_text مع LENGTH).
 3) الأعمدة كانت 4 ولا تعرض ما يميّز صكّاً حقيقياً: صار معها الهوية
    (نوع:رقم:سنة)، الحالة القانونية، وطبقة الرسمية — كلها محفوظة ولا تُعرض.

زرّ «موافقة/رفض» يعمل على المحدد كله (لم يكن كذلك: صَفّ واحد بالأسطر)،
وبوابة الحزمة تُفتح من الأسفل بدل أن يكون «التجهيز لميزان» زراً معطَّلاً.
"""
import sqlite3

from PySide6.QtCore import (QAbstractItemModel, QAbstractTableModel,
                            QModelIndex, Qt, QTimer, QSortFilterProxyModel)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox,
                               QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit,
                               QPushButton, QRadioButton, QTabWidget,
                               QTableView, QTextEdit, QVBoxLayout, QWidget)

from app import core_data as md

# سقف أسطر الطابور المعروضة — معلن في البطاقة، لا صامت
QUEUE_VIEW_LIMIT = 400
from ._common import card, page_header

# PySide6 الحديثة تنقل أزرار الحوار إلى QDialogButtonBox.StandardButton —
# مصدر واحد هنا بدل تفريع متناثر في الكود (يُستخدم في الحوار والفحص معاً).
_STD = getattr(QDialogButtonBox, "StandardButton", QDialogButtonBox)
OK_BUTTON = _STD.Ok
from PySide6.QtWidgets import QAbstractItemView  # noqa: E402
try:  # يختلف موضع العلم بين إصدارات Qt for Python
    _MODEL_CHECK_ALL = QAbstractItemModel.ModelCheckFlag.All
except AttributeError:  # noqa: PERF203
    try:
        from PySide6.QtCore import QAbstractItemModel as _QIM
        _MODEL_CHECK_ALL = _QIM.All
    except AttributeError:
        _MODEL_CHECK_ALL = None

COLUMNS = ["العنوان", "الفرع", "المواد", "الحالة", "الهوية",
           "الحالة القانونية", "التير"]
_COL_KEY = {0: "title", 1: "branch", 2: "articles", 3: "status",
            4: "identity_key", 5: "legal_status", 6: "domain_tier"}
STATUS_LABELS = {
    "human_verified": ("مُعتمَد ✓", "#28A745"),
    "needs_review": ("يحتاج مراجعة", "#C08A00"),
    "rejected": ("مرفوض ✗", "#DC3545"),
    "auto_extracted": ("استخراج آلي", "#17A2B8"),
}
_FILTERS = [("كل الحالات", ""), ("يحتاج مراجعة", "needs_review"),
            ("استخراج آلي", "auto_extracted"), ("مُعتمَد", "human_verified"),
            ("مرفوض", "rejected")]
PREVIEW_CAP = 20_000


class _DocTableModel(QAbstractTableModel):
    """نموذج على قائمة DocumentRow — تحديثه يستبدل الصفوف دفعة واحدة، فلا
    إعادة بناء عنصر لكل صَفْر في كل نبضة مؤقّت (علة النسخة القديمة)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    @property
    def rows(self) -> list:
        return self._rows

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = _COL_KEY[index.column()]
        value = getattr(row, key, "")
        if role == Qt.DisplayRole:
            if key == "status":
                return STATUS_LABELS.get(value, ("استخراج آلي", None))[0]
            if key == "articles":
                return str(value) if value else "—"
            if key == "domain_tier":
                return str(value) if value else "—"
            return str(value or "")
        if role == Qt.ForegroundRole and key == "status":
            color = STATUS_LABELS.get(value, (None, None))[1]
            if color:
                f = QColor(color)
                return f
        if role == Qt.FontRole and key == "status":
            from PySide6.QtGui import QFont
            f = QFont(); f.setBold(True)
            return f
        if role == Qt.TextAlignmentRole and key in ("articles", "domain_tier",
                                                     "legal_status"):
            return int(Qt.AlignCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None


class _DocFilterProxy(QSortFilterProxyModel):
    """بحث في العنوان/الفرع/الهوية + ترشيح بالحالة — بلا إعادة استعلام."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needle = ""
        self._status = ""
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def _recheck(self) -> None:
        # PySide6 الحديثة: invalidate_rows(QModelIndex(), All). القديمة (أو
        # عند غياب الأرقام) تسقط إلى invalidateFilter مع كتم تحذير الخمول —
        # لا نترك ضجيجاً في مخرجات CI.
        if _MODEL_CHECK_ALL is None:
            self.beginResetModel(); self.endResetModel(); return
        try:
            self.invalidate_rows(QModelIndex(), _MODEL_CHECK_ALL)
        except (AttributeError, TypeError):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                self.invalidateFilter()

    def set_search(self, text: str) -> None:
        self._needle = (text or "").strip().lower()
        self._recheck()

    def set_status(self, status: str) -> None:
        self._status = status or ""
        self._recheck()

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        model = self.sourceModel()
        row = model.rows[source_row]
        if self._status and getattr(row, "status", "") != self._status:
            return False
        if self._needle:
            hay = " ".join(str(getattr(row, k, "") or "")
                           for k in ("title", "branch", "identity_key",
                                     "legal_status")).lower()
            if self._needle not in hay:
                return False
        return True


class RejectionReasonDialog(QDialog):
    """يفرض اختيار سبب رفض قبل التأكيد (طلب المالك 2026-09-06): «حتى يتعلم
    الزاحف للمرات القادمة» — لا رفض بلا سبب صريح؛ زر التأكيد يبقى معطَّلاً
    حتى تُختار فئة واحدة على الأقل."""

    def __init__(self, doc_title: str, count: int = 1, parent=None):
        super().__init__(parent)
        self.setWindowTitle("سبب الرفض")
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        what = f"«{doc_title[:60]}»" if count == 1 else f"{count} وثيقة محدَّدة"
        v.addWidget(QLabel(f"لماذا تُرفض {what}؟"))
        self._group = QButtonGroup(self)
        self._radios = {}
        from learning import REJECTION_CATEGORIES
        for code, label in REJECTION_CATEGORIES.items():
            rb = QRadioButton(label)
            self._group.addButton(rb)
            self._radios[rb] = code
            v.addWidget(rb)
        self._group.buttonToggled.connect(self._on_toggled)
        v.addWidget(QLabel("ملاحظة إضافية (اختياري):"))
        self.note = QTextEdit(); self.note.setMaximumHeight(70)
        v.addWidget(self.note)
        self.buttons = QDialogButtonBox(_STD.Ok | _STD.Cancel)
        self.ok_btn = self.buttons.button(OK_BUTTON)
        self.ok_btn.setText("تأكيد الرفض")
        self.buttons.button(_STD.Cancel).setText("إلغاء")
        self.ok_btn.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)

    def _on_toggled(self, _btn, checked):
        if checked:
            self.ok_btn.setEnabled(True)

    def selected_category(self) -> str | None:
        for rb, code in self._radios.items():
            if rb.isChecked():
                return code
        return None

    def note_text(self) -> str:
        return self.note.toPlainText().strip()


class _QueueModel(QAbstractTableModel):
    """صفور الطابور كما هي في `crawl_tasks` — بلا تفسير مُضاف للأسباب."""

    COLS = [("#", "id"), ("الحالة", "status"), ("الرابط", "url"),
            ("محاولات", "attempts"), ("آخر عطل", "last_error"),
            ("آخر تحديث", "updated_at")]
    STATUS_AR = {"failed": "فاشلة", "blocked": "محجوبة", "queued": "منتظرة",
                 "running": "قيد الجريان", "needs_review": "تحتاج مراجعة",
                 "success": "ناجحة"}

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
        return len(self.COLS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        r = self._rows[index.row()]
        key = self.COLS[index.column()][1]
        if key == "status":
            return self.STATUS_AR.get(r.get("status"), r.get("status") or "—")
        if key == "last_error":
            return r.get("last_error") or "لا سبب مسجل"
        if key == "updated_at":
            return (r.get("updated_at") or "")[:19].replace("T", " ") or "—"
        v = r.get(key)
        return "0" if v is None else str(v)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLS[section][0]
        return None

    def task_id(self, row: int):
        return self._rows[row].get("id") if 0 <= row < len(self._rows) else None


class ReviewPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_back = None
        self.on_open_package = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._load_preview)
        self._build()
        self.refresh()

    # ──────────────────────────────────────────── البناء
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(page_header(
            "نتائج الزحف",
            "راجع ما جُمع — البحث والترشيح والفرز على المتن المحفوظ، "
            "والاعتماد ينعكس فوراً في الفهرس المُصدَّر"))
        top.addStretch()
        self.package_btn = QPushButton("الحزمة والتصدير  ◀")
        self.package_btn.setProperty("class", "gold")
        self.package_btn.clicked.connect(self._open_package)
        back = QPushButton("◀  رجوع للبداية"); back.setProperty("class", "ghost")
        back.clicked.connect(self._back)
        top.addWidget(self.package_btn); top.addWidget(back)
        root.addLayout(top)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_review_tab(), "النتائج والمراجعة")
        self.tabs.addTab(self._build_profile_tab(), "صورة المتن")
        self.tabs.addTab(self._build_reports_tab(), "تقارير الدورات")

        foot = QHBoxLayout()
        self.hint = QLabel(""); self.hint.setProperty("class", "hint")
        foot.addWidget(self.hint); foot.addStretch()
        root.addLayout(foot)

    def _build_review_tab(self) -> QWidget:
        w = QWidget(); h = QHBoxLayout(w); h.setSpacing(16)
        list_card, lv = card("القائمة")
        tools = QHBoxLayout(); tools.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText(
            "بحث في العنوان والفرع والهوية…")
        self.search.textChanged.connect(self._on_search)
        tools.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        for label, value in _FILTERS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._on_filter)
        tools.addWidget(self.status_filter)
        lv.addLayout(tools)

        self.model = _DocTableModel(self)
        self.proxy = _DocFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setDynamicSortFilter(True)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setVisible(False)
        hdr = self.view.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, width in ((1, 120), (2, 66), (3, 120), (4, 150), (5, 110), (6, 56)):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            self.view.setColumnWidth(c, width)
        self.view.selectionModel().selectionChanged.connect(
            lambda *_a: self._preview_timer.start())
        lv.addWidget(self.view)
        h.addWidget(list_card, 5)

        right = QVBoxLayout(); right.setSpacing(14)
        pv_card, pv = card("معاينة النص")
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        pv.addWidget(self.preview)
        self.preview_hint = QLabel(""); self.preview_hint.setProperty("class", "hint")
        pv.addWidget(self.preview_hint)
        actions = QHBoxLayout()
        self.approve_btn = QPushButton("موافقة ✓")
        self.approve_btn.setProperty("class", "primary")
        self.reject_btn = QPushButton("رفض ✗")
        self.reject_btn.setProperty("class", "ghost")
        self.approve_btn.clicked.connect(self._approve_selected)
        self.reject_btn.clicked.connect(self._reject_selected)
        self.approve_btn.setEnabled(False); self.reject_btn.setEnabled(False)
        actions.addWidget(self.reject_btn); actions.addWidget(self.approve_btn)
        pv.addLayout(actions)
        right.addWidget(pv_card, 1)
        h.addLayout(right, 4)
        return w

    def _build_profile_tab(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(12, 14, 12, 12)
        prof, pv = card("من المتن المحفوظ — لا من تقدير")
        self.profile = QPlainTextEdit(); self.profile.setReadOnly(True)
        self.profile.setLineWrapMode(QPlainTextEdit.NoWrap)
        pv.addWidget(self.profile)
        v.addWidget(prof, 1)
        g, gv = card("فجوات الفروع (gap_analysis) — بوابة التوسعة التالية")
        gv.addWidget(self._mono_view("gaps"))
        v.addWidget(g, 1)
        return w

    def _build_reports_tab(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(12, 14, 12, 12)
        runs, rv = card("سجل الدورات (crawl_runs) — أرقام مقيسة لكل دورة")
        rv.addWidget(self._mono_view("runs"))
        v.addWidget(runs, 1)
        fails, fv = card("توزيع أسباب الفشل (crawl_tasks.last_error) ورفضات المراجعة")
        fv.addWidget(self._mono_view("failures"))
        v.addWidget(fails, 1)

        # سياسة الطابور الفاشل: قِيس أن 8,501 مهمة `failed` بلا أي إجراء —
        # الأمر موجود (`cli requeue`) وزرّ غائب. المعاينة قبل الفعل، والتأكيد
        # صريح، والمرجع نفسه: `crawl_queue.requeue_by`.
        rq, rvw = card("إعادة المحاولة — مهام الطابور الفاشلة/المحجوبة")
        row = QHBoxLayout(); row.setSpacing(10)
        self.requeue_note = QLabel("—")
        self.requeue_note.setProperty("class", "hint")
        self.requeue_note.setWordWrap(True)
        row.addWidget(self.requeue_note, 1)
        self.requeue_filter = QLineEdit()
        self.requeue_filter.setPlaceholderText("تصفية اختيارية بكلمة في الرابط…")
        self.requeue_filter.setMaximumWidth(230)
        row.addWidget(self.requeue_filter)
        self.requeue_btn = QPushButton("↻  أعد محاولة كل الفاشل/المحجوب")
        self.requeue_btn.setProperty("class", "ghost")
        self.requeue_btn.clicked.connect(self._requeue_failed)
        row.addWidget(self.requeue_btn)
        rvw.addLayout(row)
        v.addWidget(rq)

        # توزيع الأسباب وحده لا يكفي: كان السؤال «ولماذا فشلت هذه تحديداً؟»
        # بلا جواب في الشاشة — هذا الجدول يقرأ `crawl_tasks` كما هو.
        tq, tvw = card("مهام الطابور — الرابط وآخر عطل مسجل (‏crawl_tasks)")
        frow = QHBoxLayout(); frow.setSpacing(10)
        frow.addWidget(QLabel("الحالة:"))
        self.queue_filter = QComboBox()
        self.queue_filter.addItems(list(md.TASK_STATUSES.keys()))
        self.queue_filter.currentTextChanged.connect(self._refresh_queue)
        frow.addWidget(self.queue_filter)
        self.queue_search = QLineEdit()
        self.queue_search.setPlaceholderText("بحث بالرابط…")
        self.queue_search.textChanged.connect(self._refresh_queue)
        frow.addWidget(self.queue_search, 1)
        self.queue_reload = QPushButton("⟳  تحديث")
        self.queue_reload.setProperty("class", "ghost")
        self.queue_reload.clicked.connect(self._refresh_queue)
        frow.addWidget(self.queue_reload)
        self.requeue_sel_btn = QPushButton("↻  أعد المحاولة للمحدد")
        self.requeue_sel_btn.setProperty("class", "primary")
        self.requeue_sel_btn.clicked.connect(self._requeue_selected)
        frow.addWidget(self.requeue_sel_btn)
        tvw.addLayout(frow)

        self.queue_model = _QueueModel(self)
        self.queue_view = QTableView()
        self.queue_view.setModel(self.queue_model)
        self.queue_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_view.setAlternatingRowColors(True)
        self.queue_view.verticalHeader().setVisible(False)
        self.queue_view.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.queue_view.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        self.queue_view.selectionModel().selectionChanged.connect(
            self._sync_sel_count)
        tvw.addWidget(self.queue_view)
        self.queue_note = QLabel("—"); self.queue_note.setProperty("class", "hint")
        self.queue_note.setWordWrap(True)
        tvw.addWidget(self.queue_note)
        v.addWidget(tq, 1)
        self._refresh_queue()
        return w

    def _refresh_queue(self) -> None:
        """لائحة الطابور من `crawl_queue.list_tasks` — ولا اجتهاد في السبب."""
        status = md.TASK_STATUSES.get(self.queue_filter.currentText(), "")
        rows = md.task_rows(status=status,
                            needle=self.queue_search.text().strip(),
                            limit=QUEUE_VIEW_LIMIT)
        self.queue_model.set_rows(rows)
        q = md.queue_counts()
        text = (
            f"معروض {len(rows)} من أصل {q['total']} مهمة في الطابور "
            f"(فاشلة {q['failed']} | محجوبة {q['blocked']} | منتظرة "
            f"{q['queued']} | تحتاج مراجعة {q['needs_review']} | ناجحة "
            f"{q['success']}). السقف {QUEUE_VIEW_LIMIT} سطر — ارفع التصفية "
            "للوصول لغيره.")
        if getattr(self, "_action_msg", ""):
            # آخر فعل يبقى مقروءاً بعد التحديث الذي يُعقبه — إلا اختفت
            # الحقيقة في نص الإحصاء.
            text = f"{self._action_msg}  —  {text}"
        self.queue_note.setText(text)
        self._sync_sel_count()

    def _sync_sel_count(self) -> None:
        n = len(self.queue_view.selectionModel().selectedRows())
        self.requeue_sel_btn.setText(f"↻  أعد المحاولة للمحدد ({n})" if n
                                     else "↻  أعد المحاولة للمحدد")

    def _set_action(self, msg: str) -> None:
        """رسالة فعل، تُعرض أمام إحصاء الطابور حتى التحديث القادم."""
        self._action_msg = msg
        self._refresh_queue()

    def _requeue_selected(self) -> None:
        """إعادة المهام المحددة بالـid — معاينة العدد ثم تأكيد ثم `requeue`."""
        ids = []
        sm = self.queue_view.selectionModel()
        for idx in sm.selectedRows():
            tid = self.queue_model.task_id(idx.row())
            if tid is not None:
                ids.append(int(tid))
        if not ids:
            QMessageBox.information(self, "لا تحديد",
                                    "ظلّل مهمة أو أكثر من جدول الطابور أولاً.")
            return
        if QMessageBox.question(
                self, "تأكيد إعادة المحاولة",
                f"ستعود {len(ids)} مهمة محددة إلى الطابور (‏status=queued، "
                "attempts=0).\n"
                "لا تُحذف بيانات — تتغير الحالة فقط."
                ) != QMessageBox.Yes:
            self.queue_note.setText("أُلغيت الإعادة — المهام المحددة كما هي")
            return
        res = md.requeue_ids(ids)
        if res.get("error"):
            QMessageBox.warning(self, "تعذّر جزء من الإعادة", str(res["error"]))
        self._set_action(
            f"✓ أُعيد {res.get('revived', 0)} مهمة إلى الطابور (بأصفار "
            "المحاولات) — شغّل دورة زحف من «البداية» لتجريها"
            + (f" (لم يوجد: {res['missing']})" if res.get("missing") else ""))
        QTimer.singleShot(0, self.refresh)

    def _requeue_failed(self) -> None:
        """معاينة ← تأكيد صريح ← `crawl_queue.requeue_by` (نفس مسار CLI)."""
        contains = self.requeue_filter.text().strip() or None
        pre = md.preview_requeue(("failed", "blocked"), contains=contains)
        if not pre["total"]:
            QMessageBox.information(self, "لا شيء", "لا مهمة فاشلة/محجوبة "
                                    + (f"تحوي «{contains}»" if contains else ""))
            return
        if QMessageBox.question(
                self, "تأكيد إعادة المحاولة",
                f"سيعاد {pre['total']} مهمة إلى الطابور (failed/blocked)"
                + (f" المرشّحة بـ«{contains}»" if contains else "")
                + ".\nلن تُحذف أي بيانات — تتغير الحالة إلى queued فقط.") \
                != QMessageBox.Yes:
            self.requeue_note.setText("أُلغيت الإعادة — الطابور كما هو")
            return
        res = md.requeue_failed(("failed", "blocked"), contains=contains)
        self.requeue_note.setText(
            f"✓ أُعيد {res.get('revived', 0)} مهمة إلى الطابور — شغّل دورة "
            "زحف من «البداية» لتجريها"
            + (f" (خطأ: {res['error']})" if res.get("error") else ""))
        QTimer.singleShot(0, self.refresh)

    def _mono_view(self, name: str) -> QPlainTextEdit:
        """محرر عرض أحادي، مسجَّل على self باسمه — للاختبارات والاسترجاع."""
        ed = QPlainTextEdit(); ed.setReadOnly(True)
        ed.setProperty("view", name)
        ed.setLineWrapMode(QPlainTextEdit.NoWrap)
        setattr(self, name, ed)
        return ed

    # ──────────────────────────────────────────── التحديث
    def refresh(self) -> None:
        try:
            pre = md.preview_requeue(("failed", "blocked"),
                                     contains=self.requeue_filter.text().strip() or None)
            per = "، ".join(f"{k}: {n}" for k, n in
                            sorted(pre["by_status"].items())) or "لا شيء"
            self.requeue_note.setText(
                f"القابل لإعادة المحاولة الآن — {pre['total']} مهمة ({per}). "
                "الإعادة تصفّر عدّاد المحاولات وتعيدها للطابور؛ لا تشغّل "
                "الزحف وحدك: تابع بـ«ابدأ الزحف».")
        except Exception as exc:  # noqa: BLE001 — لا تُظلم اللائحة بسبب بطاقة
            self.requeue_note.setText(f"تعذّر قياس الطابور: {type(exc).__name__}")
        docs = md.DOCUMENTS
        sig = (len(docs), getattr(docs[-1], "doc_id", 0) if docs else 0)
        if sig != getattr(self, "_sig", None):     # لا إعادة بناء بلا سبب
            self._sig = sig
            self.model.set_rows(docs)
        n_review = sum(1 for d in docs if d.status == "needs_review")
        shown = self.proxy.rowCount()
        self.hint.setText(
            f"الإجمالي {len(docs)} — معروض بعد الترشيح {shown} — "
            f"يحتاج مراجعة {n_review} — محدَّد {len(self._selected_docs())}")
        self._reload_profile()
        self._preview_timer.start()

    def _reload_profile(self) -> None:
        prof = md.CORPUS_PROFILE or {}
        lines = [
            f"وثائق نشطة: {prof.get('documents', 0)}",
            f"لها هوية (نوع:رقم:سنة): {prof.get('with_identity', 0)}",
            f"بلا هوية ⇒ بلا حالة قانونية: "
            f"{prof.get('documents', 0) - prof.get('with_identity', 0)}",
            "",
            "الحالة القانونية: " + (" | ".join(
                f"{k}: {v}" for k, v in (prof.get("legal_status") or {}).items())
                or "محسوبة لاصفْر"),
            "المراجعة البشرية: " + (" | ".join(
                f"{k}: {v}" for k, v in (prof.get("review_status") or {}).items())
                or "لا شيء"),
            "طبقات الرسمية (تير): " + (" | ".join(
                f"تير {k}: {v}" for k, v in (prof.get("domain_tier") or {}).items())
                or "لا شيء"),
        ]
        self.profile.setPlainText("\n".join(lines))
        gaps = md.GAP_REPORT
        self.gaps.setPlainText("\n".join(
            f"{'⚠︎' if g.is_gap else '  '} {g.branch:<22} {g.count:>5} "
            f"(الحدّ المتوقع {g.expected_min:g})" for g in gaps)
            or "لا بيانات فروع بعد — شغّل `gaps` بعد أول دورة")
        runs = md.RUN_HISTORY
        self.runs.setPlainText("\n".join(
            f"#{r['id']:>3}  {str(r['started_at'])[:16]}  [{r['mode']}]  "
            f"صفحات {r['pages']} | وثائق {r['docs']} | مواد {r['articles']} | "
            f"تخطي {r['skipped']} | إخفاقات {r['failures']}" for r in runs)
            or "لا دورات مسجلة بعد")
        fb = md.FAILURE_BREAKDOWN
        rej = md.REJECTION_STATS
        flines = [f"{r['n']:>6}  [{r['status']}] {r['reason'][:90]}" for r in fb]
        flines += ["", f"أسباب الرفض البشري: {rej.get('total', 0)}"]
        flines += [f"{r['n']:>6}  {r['category']}"
                   for r in rej.get("by_category", [])]
        self.failures.setPlainText("\n".join(flines) or "لا إخفاقات مسجلة")

    # ──────────────────────────────────────────── الترشيح
    def _on_search(self, text: str) -> None:
        self.proxy.set_search(text)
        self.refresh_hint_only()

    def _on_filter(self, _idx: int) -> None:
        self.proxy.set_status(self.status_filter.currentData() or "")
        self.refresh_hint_only()

    def refresh_hint_only(self) -> None:
        self.hint.setText(f"معروض بعد الترشيح {self.proxy.rowCount()} من "
                          f"{self.model.rowCount()}")

    # ──────────────────────────────────────────── التحديد والمعاينة
    def _selected_rows(self) -> list[int]:
        return sorted({self.proxy.mapToSource(i).row()
                       for i in self.view.selectionModel().selectedRows()})

    def _selected_docs(self) -> list:
        rows = self.model.rows
        return [rows[i] for i in self._selected_rows() if i < len(rows)]

    def _load_preview(self) -> None:
        docs = self._selected_docs()
        if not docs:
            self.preview.setPlainText("")
            self.preview_hint.setText("اختر صفاً (أو عدة صفوف بـCtrl/Shift)")
            self.approve_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            return
        self.approve_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)
        d = docs[0]
        text, total = md.document_text(d.doc_id, PREVIEW_CAP) if d.doc_id else ("", 0)
        head = (f"{d.title}\n{d.branch} — {d.identity_key or 'بلا هوية'} — "
                f"الحالة: {d.legal_status or 'غير محسوبة'} — تير "
                f"{d.domain_tier or '—'} — {d.articles} مادة\n")
        self.preview.setPlainText((head + "\n" + (text or "(لا نص محفوظ)")))
        hidden = max(0, total - PREVIEW_CAP)
        self.preview_hint.setText(
            f"معاينة أول {PREVIEW_CAP:,} حرف" + (
                f" — مُخفى {hidden:,} حرف (النص الكامل في القاعدة/الحزمة)"
                if hidden else " — النص كامل"))

    # ──────────────────────────────────────────── الاعتماد/الرفض
    def _set_review_status(self, value: str) -> None:
        ids = [d.doc_id for d in self._selected_docs() if d.doc_id]
        if not ids:
            return
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.executemany(
            "UPDATE documents SET review_status=?, updated_at=datetime('now') "
            "WHERE id=?", [(value, i) for i in ids])
        conn.commit(); conn.close()
        from database import insert_log
        insert_log("", "review",
                   f"{len(ids)} وثيقة ← review_status={value}")
        self.refresh()

    def _approve_selected(self) -> None:
        self._set_review_status("human_verified")

    def _reject_selected(self) -> None:
        docs = self._selected_docs()
        if not docs:
            return
        dlg = RejectionReasonDialog(docs[0].title, len(docs), self)
        if dlg.exec() != QDialog.Accepted:
            return
        category = dlg.selected_category()
        if not category:
            return  # لا يحدث فعلياً (زر التأكيد معطَّل بلا اختيار) — درع إضافي
        note = dlg.note_text()
        from config import DB_PATH
        import learning
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        last = {}
        for d in docs:
            conn.execute("UPDATE documents SET status='rejected', "
                         "updated_at=datetime('now') WHERE id=?", (d.doc_id,))
            conn.commit()
            last = learning.record_rejection(conn, d.doc_id, d.source_url,
                                             category, note) or {}
        conn.close()
        from database import insert_log
        from learning import REJECTION_CATEGORIES
        insert_log("", "review",
                   f"{len(docs)} وثيقة رُفضت — السبب: {REJECTION_CATEGORIES[category]}")
        if last.get("source_key"):
            msg = (f"مصدر «{last['source_key']}»: المصداقية الآن "
                   f"{last['credibility']:.2f}، رفضات متراكمة "
                   f"{last['rejection_count']}")
            if last.get("excluded"):
                msg += " — استُبعد تلقائياً من الزحف القادم."
            insert_log("", "learning", msg,
                       "warning" if last.get("excluded") else "info")
        self.refresh()

    # ──────────────────────────────────────────── التنقل
    def _open_package(self) -> None:
        if self.on_open_package:
            self.on_open_package()

    def _back(self) -> None:
        if self.on_back:
            self.on_back()
