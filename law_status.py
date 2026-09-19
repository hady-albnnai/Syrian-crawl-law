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
    r"(?:يلغ[يى]|تلغ[يى]|الغ[يى]|ألغ[يى]|إلغاء|الغاء|ينسخ|تنسخ|"
    r"ينه[يى] العمل|تنه[يى] العمل|يوقف العمل|توقف العمل)\s*"
    r"(?:ب|بأحكام\s+|باحكام\s+|نص\s+|أحكام\s+|احكام\s+)?"
    r"(?:ال)?(?:مادة|مواد|فقرة|فقرات|بند|بنود|فصل|فصول|باب|جدول|عبارة)")


# صيغة ختامية عامة توجد بكل قانون تقريباً — لا تلغي صكاً محدداً:
# «تلغى جميع الأحكام/النصوص المخالفة لهذا القانون». قِيس 2026-09-19 على
# قاعدة المالك: عُلِّم قانون العقوبات 148/1949 «ملغى» لأن قانون حق المؤلف
# أحال إلى مواده 708–715 ثم ختم بهذه الصيغة ضمن نافذة 60 حرفاً.
GENERIC_REPEAL_RE = re.compile(
    r"(?:يلغ[يى]|تلغ[يى])\s+(?:(?:جميع|كل|كافة)\s+)?"
    r"(?:ال)?(?:أحكام|احكام|نصوص|النصوص)\s+(?:ال)?مخالف")
# إحالة إلى نطاق مواد من الصك: «المواد من 708 إلى 715 من قانون…» — جزئية.
RANGE_REF_RE = re.compile(
    r"(?:ال)?موا?د[ةه]?\s*(?:من\s*)?[/(]?\s*\d+\s*[/)]?\s*"
    r"(?:إلى|الى|حتى|و|-|ـ)\s*[/(]?\s*\d+[^.؛]{0,20}\bمن\b[^.؛]{0,60}$")


def classify_reference(ref: dict) -> str:
    """تصنيف اتجاهي (ف٥): الفعل يجب أن يقع **قبل** الصك المستهدَف.

    - before (≤60 حرفاً قبل الإشارة) هو ما يحكم: «يلغى [القانون 91/1959]».
    - after يُستعمل فقط لتأكيد التعديل («…ويستعاض عنه») لا للإلغاء —
      إلغاءٌ يرد بعد الإشارة يعود غالباً لجملة أخرى (الصيغة الختامية).
    - إشارة تُذكر كنطاق مواد («من 708 إلى 715 من قانون العقوبات») إحالة
      جزئية: تعديل على الأكثر، لا إلغاء أبداً.
    """
    before = _strip(ref.get("before") or "")
    after = _strip(ref.get("after") or "")
    if not before and not after:
        return classify_context(ref.get("context") or "")
    # قائمة مرقّمة تحكمها جملة واحدة: «ويلغى أيضا:\n1- …\n2- …» — الفعل
    # قبل النقطتين يسري على كل بند (نص قانون الإعلام الحقيقي: البند 2
    # كان يُقطع عن الفعل بنقطة البند 1).
    lm = re.search(r"(يلغ[يى]|تلغ[يى]|يعدل|تعدل)[^:.؛]{0,40}:\s*\n"
                   r"(?:\s*\d+\s*[-ـ)][^\n]*\n)*\s*\d+\s*[-ـ)][^\n]*$", before)
    if lm:
        return "repeal" if lm.group(1)[1:].startswith("لغ") else "amend"
    # «تلغى الأحكام المخالفة … الواردة في [القانون X]»: إلغاء جزئي للصك X
    # (تعديل) — كلمة «الواردة في» قد تُبتلع داخل مطابقة الهوية فتغيب عن
    # before، لذا تُفحص على السياق الكامل قبل الإشارة.
    # مطابقة الهوية قد تبتلع «القانون الواردة في» داخل الفجوة، فتُفحص
    # الصيغة على before + مطلع السياق المطابق معاً.
    matched_head = _strip((ref.get("context") or ""))
    if re.search(r"(?:أحكام|احكام|نصوص)\s+(?:ال)?مخالف[^.؛]{0,80}الواردة\s+في\s+(?:ال)?(?:قانون|مرسوم|قرار|نظام)",
                 before + " " + matched_head[:120]) and \
            re.search(r"(?:أحكام|احكام|نصوص)\s+(?:ال)?مخالف", before):
        return "amend"
    # نأخذ آخر جملة قبل الإشارة فقط (بعد آخر نقطة/فاصلة منقوطة)
    # حدود الجملة: نقطة/فاصلة منقوطة. السطر الجديد **ليس** حداً إذا سبقته
    # نقطتان أو تلاه ترقيم قائمة («ويلغى أيضا:\n1- قانون المطبوعات…» —
    # نص قانون الإعلام الحقيقي، قِيس 2026-09-19).
    tail = re.split(r"[.؛;]|\n(?!\s*\d+\s*[-ـ)]|\s*[أ-ي]\s*[-ـ)])",
                    before.replace(":\n", ": "))[-1]
    if GENERIC_REPEAL_RE.search(tail):
        # «تلغى الأحكام المخالفة … الواردة في [القانون X]» = إلغاء جزئي
        # للصك X (تعديل)؛ «… كما يلغى [القانون X]» = إلغاء كامل معطوف
        # (نص قانون حق المؤلف الحقيقي: «كما يلغى القانون رقم 12 لعام
        # 2001»)؛ أما بلا صك محدد فصيغة ختامية عامة.
        if re.search(r"الواردة\s+في\s*(?:ال)?\w*\s*$", tail):
            return "amend"
        # الفعل المعطوف قد يُبتلع في فجوة مطابقة الهوية («…لهذا [القانون
        # كما يلغى القانون رقم 12]») فيُفحص مطلع المطابقة نفسها.
        head = _strip(ref.get("context") or "")
        head = head[len(head) - len(after) - 80: len(head) - len(after)] \
            if after else head[-80:]
        if re.search(r"(?:كما|و)\s*(?:يلغ[يى]|تلغ[يى])\s*(?:ال)?(?:قانون|مرسوم|قرار|نظام)",
                     head):
            return "repeal"
        return "cite"
    if RANGE_REF_RE.search(tail):
        # نطاق مواد من الصك: إلغاؤها/إنهاء العمل بها/تعديلها = تعديل
        # للصك (قانون العقوبات: «ينهى العمل بالمواد 708–715» — 8 مواد لا
        # القانون)؛ مجرد إحالة عقابية («يعاقب بالمواد …») = cite.
        if REPEAL_RE.search(tail) or AMEND_RE.search(tail) \
                or AMEND_RE.search(after[:40]):
            return "amend"
        return "cite"
    if PARTIAL_OBJECT_RE.search(tail):
        return "amend"
    if REPEAL_RE.search(tail):
        return "repeal"
    if AMEND_RE.search(tail) or AMEND_RE.search(after[:40]):
        return "amend"
    return "cite"


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
        action = classify_reference(ref)
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
    # حالة قديمة لا تبقى بلا دليل: تُمسح كلها ثم تُحسب من الإحالات الحالية
    # (قِيس 2026-09-19: «ملغى» 19 بالعدّ و3 بالتقرير — 16 يتيمة من حساب
    # سابق على وثائق فقدت دليلها أو هويتها).
    conn.execute("UPDATE documents SET legal_status=NULL")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    has_nature = "nature" in cols
    has_reason = "legal_status_reason" in cols
    has_issue = "issue_date" in cols
    if has_reason:
        conn.execute("UPDATE documents SET legal_status_reason=NULL")
    nature_ok = ("AND COALESCE(d.nature,'instrument')='instrument' "
                 if has_nature else "")
    # A-3: الزمن بالتاريخ الكامل حين يتوفر للطرفين، وإلا بالسنة (سنة مجهولة
    # تُقبل). الصك المستبعَد/المستبدَل لا يُعدّ دليلاً.
    issue_sel = ", d.issue_date AS a_issue" if has_issue else ", NULL AS a_issue"
    rows = conn.execute(
        "SELECT id, identity_key, year" + (", issue_date" if has_issue else ", NULL AS issue_date")
        + " FROM documents WHERE identity_key IS NOT NULL"
        " AND status IN ('active','superseded')").fetchall()
    for row in rows:
        evid = conn.execute(
            f"""SELECT a.action, a.context, d.identity_key AS a_key, d.year AS a_year,
                       d.title AS a_title{issue_sel}
                FROM law_amendments a
                JOIN documents d ON d.id = a.amending_doc_id
                WHERE a.target_identity=? {nature_ok}
                AND d.status='active'
                AND (d.year IS NULL OR ? IS NULL OR d.year >= ?)""",
            (row["identity_key"], row["year"], row["year"])).fetchall()
        # حارس التاريخ الكامل: معدِّل صدر قبل المستهدَف بتاريخ يقيني يُستبعد
        # (نفس السنة لا تكفي للترتيب — قِيس A-3)
        t_issue = row["issue_date"]
        kept = [e for e in evid
                if not (t_issue and e["a_issue"] and e["a_issue"] < t_issue)]
        actions = {e["action"] for e in kept}
        if "repeal" in actions:
            status = "ملغى"
        elif "amend" in actions:
            status = "معدَّل"
        else:
            status = "ساري"
        reason = None
        if kept:
            def _fmt(e):
                when = e["a_issue"] or (str(e["a_year"]) if e["a_year"] else "؟")
                verb = "أُلغي" if e["action"] == "repeal" else "عُدّل"
                who = e["a_key"] or (e["a_title"] or "")[:40]
                return f"{verb} بـ {who} ({when})"
            top = sorted(kept, key=lambda e: (e["action"] != "repeal",
                                              e["a_issue"] or "", e["a_year"] or 0))
            reason = "؛ ".join(dict.fromkeys(_fmt(e) for e in top[:3]))
        elif status == "ساري":
            reason = "لا دليل تعديل أو إلغاء في المتن المحصود"
        if has_reason:
            conn.execute("UPDATE documents SET legal_status=?, legal_status_reason=?"
                         " WHERE id=?", (status, reason, row["id"]))
        else:
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
           ORDER BY COALESCE(d.issue_date, ''), d.year, d.number""",
        (identity_key,)).fetchall()
