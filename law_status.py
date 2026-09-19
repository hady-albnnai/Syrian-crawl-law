# -*- coding: utf-8 -*-
"""
law_status.py — سلسلة التعديلات والحالة القانونية (ف١ من ميثاق التوسعة).

المشكلة التي يحلّها: document_versions يتبع نسخ *النص* بين دورات الزحف،
لكن لا شيء يجيب سؤال المحامي: «هل هذا القانون ساري أم معدَّل أم ملغى؟
وما سلسلة تعديلاته؟». والميثاق صريح: «القانون المعدَّل الذي لا يقول
إنه معدَّل كذبٌ بصمت على المحامي» (EXPANSION-CHARTER §3).

المصدر: إحالات الوثائق بعضها لبعض — law_identity.extract_law_references
يستخرجها مع سياقها الخام (60 حرفاً) ويترك التصنيف الدلالي عمداً لهذه
الوحدة («تمييز عدّل عن ألغى عن استند إلى» — موثق بتصميمه). هنا:

  1. classify_context   : نية الإحالة من سياقها (repeal > amend > cite)
  2. extract_amendments : إحالات هذه الوثيقة تعديلاً/إلغاءً (بلا استشهاد
                          ولا إشارة ذاتية)
  3. record_amendments_for_doc : تسجيلها بجدول law_amendments (يستدعى من
                          دورة الزحف فور حفظ الوثيقة)
  4. compute_legal_statuses    : حالة كل وثيقة من السلسلة (ملغى إن
                          استهدفه إلغاء، وإلا معدَّل، وإلا ساري)
  5. law_chain          : سلسلة تعديلات قانون بعينه، مرتبة زمنياً

حدود صريحة: الحالة «ساري» تعني «لا إلغاء ولا تعديل *بالمتن المتوفر*» —
لا نقسم بسلامة التشريع؛ ووثيقة بلا هوية تبقى بلا حالة (لا نخمن).
"""
import re
from datetime import datetime

from law_identity import extract_law_identity, extract_law_references

# نية الفعل القانوني بسياق الإحالة. الإلغاء مقدَّم على التعديل: عبارة
# «يلغي وينسخ ويعوض» تُحتسب إلغاءً لأن الأثر الغالب للمستهدف هو الزوال.
# ملاحظة صرفية (ف١): الفعل يرد بالألف المقصورة (يلغى) كما بالياء (يلغي)
# — النمط يشمل الصورتين وإلا انزلق الإلغاء إلى استشهاد محايد.
_TASHKEEL = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # حركات + شدّة + تطويل


def _strip(s: str) -> str:
    return _TASHKEEL.sub("", s or "")


AMEND_RE = re.compile(
    r"يعدل|تعدل|تعديل|معدل|استبدال|يستبدل|تستبدل|استبدل|يستعاض|تستعاض|"
    r"تتميم|اضاف[ةى]|إضاف[ةى]|يضاف|تضاف|يحذف|تحذف")
REPEAL_RE = re.compile(
    r"يلغ[يى]|تلغ[يى]|الغ[يى]|ألغ[يى]|إلغاء|الغاء|لإلغاء|ينسخ|تنسخ|"
    r"يوقف العمل|توقف العمل|ينهى العمل")
# إلغاء **جزئي**: الفعل يقع على مادة/فقرة/بند/فصل لا على الصك كله —
# «تلغى المادة 5 من القانون 28/2001» تعديلٌ للقانون 28 لا إلغاؤه.
# قِيس 2026-09-19: النمط القديم كان يعلّم القانون كله «ملغى» فيمنع
# الاستشهاد بقانون نافذ — أخطر خطأ ممكن على المحامي.
PARTIAL_OBJECT_RE = re.compile(
    r"(?:يلغ[يى]|تلغ[يى]|الغ[يى]|ألغ[يى]|إلغاء|الغاء|ينسخ|تنسخ)\s*"
    r"(?:نص\s+|أحكام\s+|احكام\s+)?"
    r"(?:ال)?(?:مادة|مواد|فقرة|فقرات|بند|بنود|فصل|فصول|باب|جدول|عبارة)")


def classify_context(context: str) -> str:
    """تصنيف نية الإحالة من سياقها النصي الخام.

    repeal = زوال الصك كله («يلغى القانون رقم…»، «يلغى العمل بأحكام…»).
    amend  = تعديل، أو إلغاء جزئي (مواد/فقرات) — الصك يبقى نافذاً معدَّلاً.
    cite   = استشهاد محايد.
    التشكيل يُزال قبل المطابقة («تُلغى»، «يُعدَّل»).
    """
    c = _strip(context)
    if not c:
        return "cite"
    if PARTIAL_OBJECT_RE.search(c):
        return "amend"
    if REPEAL_RE.search(c):
        return "repeal"
    if AMEND_RE.search(c):
        return "amend"
    return "cite"


def extract_amendments(title: str, text: str) -> list:
    """إحالات هذه الوثيقة المصنفة تعديلاً أو إلغاءً.

    تستبعد الإشارة الذاتية (الوثيقة تذكر صكها في ديباجتها — ليس تعديلاً
    لنفسها) والاستشهادات المحايدة — لا تُسجَّل إلا العلاقات الفعلية.
    """
    own = extract_law_identity(title, text)
    out = []
    for ref in extract_law_references(text):
        if own["identity_key"] and ref["identity_key"] == own["identity_key"]:
            continue
        action = classify_context(ref["context"])
        if action == "cite":
            continue
        out.append({
            "target_identity": ref["identity_key"],
            "target_doc_type": ref["doc_type"],
            "target_number": ref["law_number"],
            "target_year": ref["law_year"],
            "action": action,
            "context": ref["context"],
        })
    return out


def record_amendments_for_doc(cursor, doc_row_id: int, title: str,
                              text: str) -> int:
    """تسجيل إحالات وثيقة محفوظة بجدول law_amendments — يعيد عدد الجديد."""
    added = 0
    for am in extract_amendments(title, text):
        exists = cursor.execute(
            "SELECT 1 FROM law_amendments WHERE amending_doc_id=? "
            "AND target_identity=? AND action=?",
            (doc_row_id, am["target_identity"], am["action"])).fetchone()
        if exists:
            continue
        cursor.execute(
            """INSERT INTO law_amendments
                 (amending_doc_id, target_identity, action, context, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_row_id, am["target_identity"], am["action"],
             am["context"], datetime.now().isoformat()))
        added += 1
    return added


def rebuild_links(conn) -> int:
    """إعادة بناء جدول الإحالات من كل الوثائق (صيانة/ترقية بعد هجرة)."""
    conn.execute("DELETE FROM law_amendments")
    total = 0
    rows = conn.execute(
        "SELECT id, title, clean_content FROM documents "
        "WHERE clean_content IS NOT NULL").fetchall()
    for row in rows:
        total += record_amendments_for_doc(
            conn.cursor(), row["id"], row["title"] or "",
            row["clean_content"])
    conn.commit()
    return total


def compute_legal_statuses(conn) -> dict:
    """حالة كل وثيقة من سلسلة الإحالات + تحديث documents.legal_status.

    الأولوية: ملغى > معدَّل > ساري. الوثيقة بلا هوية لا تُمس (بلا حالة).
    """
    counts = {"ملغى": 0, "معدَّل": 0, "ساري": 0}
    has_nature = any(r[1] == "nature" for r in
                     conn.execute("PRAGMA table_info(documents)").fetchall())
    nature_ok = ("AND COALESCE(d.nature,'instrument')='instrument' "
                 if has_nature else "")
    rows = conn.execute(
        "SELECT id, identity_key, year FROM documents "
        "WHERE identity_key IS NOT NULL").fetchall()
    for row in rows:
        # حارسان (ف٥ 2026-09-19) — من دونهما يُعلَّم قانون نافذ «ملغى»:
        # 1) المعدِّل صكٌّ (لا أعمال تحضيرية ولا مقال يذكر «يلغى»).
        # 2) الزمن: صكٌّ أقدم لا يعدّل أحدث — سنة المعدِّل ≥ سنة المستهدَف
        #    (سنة مجهولة تُقبل: لا نرفض بالجهل بل نُبقي الدليل).
        actions = {r["action"] for r in conn.execute(
            f"""SELECT a.action FROM law_amendments a
                JOIN documents d ON d.id = a.amending_doc_id
                WHERE a.target_identity=? {nature_ok}
                AND (d.year IS NULL OR ? IS NULL OR d.year >= ?)""",
            (row["identity_key"], row["year"], row["year"])).fetchall()}
        if "repeal" in actions:
            status = "ملغى"
        elif "amend" in actions:
            status = "معدَّل"
        else:
            status = "ساري"
        conn.execute("UPDATE documents SET legal_status=? WHERE id=?",
                     (status, row["id"]))
        counts[status] += 1
    # ف٤: «بلا هوية» يُحسب من الصكوك فقط — الأعمال التحضيرية وصفحات الفهارس
    # ليست صكوكاً فلا تُطلب لها هوية (كانت تُضخّم الرقم: 208 من 262).
    has_nature = any(r[1] == "nature" for r in
                     conn.execute("PRAGMA table_info(documents)").fetchall())
    if has_nature:
        counts["بلا هوية (صكوك)"] = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE identity_key IS NULL "
            "AND COALESCE(nature,'instrument')='instrument'").fetchone()[0]
        counts["ليست صكوكاً (خارج العدّ)"] = conn.execute(
            "SELECT COUNT(*) FROM documents "
            "WHERE COALESCE(nature,'instrument')<>'instrument'").fetchone()[0]
    else:
        counts["بلا هوية (بلا حالة)"] = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE identity_key IS NULL"
        ).fetchone()[0]
    conn.commit()
    return counts


def law_chain(conn, identity_key: str) -> list:
    """سلسلة تعديلات/إلغاءات صك بعينه، مرتبة بسنة الصك المعدِّل ثم رقمه."""
    return conn.execute(
        """SELECT a.action, a.context, d.doc_type, d.number,
                  d.year, d.title, d.legal_status
           FROM law_amendments a
           JOIN documents d ON d.id = a.amending_doc_id
           WHERE a.target_identity = ?
           ORDER BY d.year, d.number""",
        (identity_key,)).fetchall()
