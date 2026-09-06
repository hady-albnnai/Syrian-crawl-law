# -*- coding: utf-8 -*-
"""learning.py — التعلّم من التجارب السابقة (DELIVERY/DESIGN-SELF-DISCOVERY.md
§5): عدّاد شفاف بالكامل، بلا نموذج تعلّم آلي حقيقي (قرار مقصود موثّق
بالتصميم — الشفافية وقابلية التفسير أولى من أي تعقيد إحصائي هنا).

يقيس أداء كل مصدر معتمد بعدد القوانين الفريدة الجديدة (identity_key غير
مكرر) التي أنتجها عبر الزمن، ويحدّث حالة تعلّم بسيطة (active/exhausted)
بعد عدد من الدورات الفارغة المتتالية.

ربط مصدر بوثيقة: بمطابقة نطاق (netloc) source_url للوثيقة مع نطاق
sources.base_url — لا عمود جديد على documents يربط id المصدر مباشرة (لا
تغيير إضافي على المخطط أكثر من اللازم؛ هذا استعلام كافٍ لحجم المتن الحالي).
"""
from datetime import datetime
from urllib.parse import urlparse

# عدد الدورات الفارغة المتتالية قبل اعتبار مصدر «مستنفداً» — خط أساس
# محافظ شائع بأنظمة retry/backoff (موثّق بالتصميم §9).
EXHAUSTION_THRESHOLD = 3

# التعلّم من رفض المراجعة البشرية (طلب المالك 2026-09-06): كل رفض
# لوثيقة ينزّل مصداقية مصدرها — قرار بشري صريح أقوى من عدّاد آلي فارغ.
REJECTION_CREDIBILITY_PENALTY = 0.1
MIN_CREDIBILITY = 0.1
# 3 رفضات متراكمة من نفس المصدر ⇒ يُستبعد كلياً من البذر القادم (نفس
# منطق «مصدر مستنفد» أعلاه، لكن مصدره قرار بشري لا عدّاد فارغ).
REJECTION_EXCLUDE_THRESHOLD = 3

REJECTION_CATEGORIES = {
    "not_legal": "ليس نصاً قانونياً فعلاً (دعاية/منتدى عام)",
    "duplicate": "مكرر مع وثيقة موجودة أصلاً",
    "bad_extraction": "جودة استخراج رديئة (نص مبعثر/ناقص)",
    "untrusted_source": "مصدر غير موثوق أصلاً",
}


def _netloc(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _count_unique_identities_for_source(conn, base_url: str) -> int:
    """عدد identity_key الفريدة (غير NULL) بين وثائق نشطة/بديلة صادرة من
    نطاق هذا المصدر — لا نعدّ status='superseded' كي لا تُحسب نسخة خسرت
    المقارنة مرتين (مرة كخاسرة ومرة كموجودة أصلاً)."""
    domain = _netloc(base_url)
    if not domain:
        return 0
    rows = conn.execute(
        "SELECT DISTINCT identity_key, source_url FROM documents "
        "WHERE identity_key IS NOT NULL AND status IN ('active', 'alternate_source')"
    ).fetchall()
    return len({r[0] for r in rows if _netloc(r[1]) == domain})


def update_source_performance(conn) -> dict:
    """يُشغَّل بعد كل دورة (اكتشاف أو زحف) — يقارن العدد الحالي من القوانين
    الفريدة لكل مصدر معتمد بما كان مسجَّلاً سابقاً، ويحدّث الحالة.

    يعيد ملخصاً: {source_key: {"new_this_run": n, "learned_status": ...}}.
    """
    summary = {}
    sources = conn.execute(
        "SELECT source_key, base_url FROM sources WHERE status = 'approved'"
    ).fetchall()

    for src in sources:
        source_key, base_url = src[0], src[1]
        current_total = _count_unique_identities_for_source(conn, base_url)

        row = conn.execute(
            "SELECT new_identities_total, consecutive_empty_runs, runs_count "
            "FROM source_performance WHERE source_key = ?",
            (source_key,)).fetchone()

        if row is None:
            previous_total, consecutive_empty, runs_count = 0, 0, 0
        else:
            previous_total, consecutive_empty, runs_count = row[0], row[1], row[2]

        new_this_run = max(0, current_total - previous_total)
        consecutive_empty = 0 if new_this_run > 0 else consecutive_empty + 1
        learned_status = ("exhausted" if consecutive_empty >= EXHAUSTION_THRESHOLD
                          else "active")

        conn.execute('''
            INSERT INTO source_performance
            (source_key, runs_count, new_identities_total,
             last_run_new_identities, consecutive_empty_runs,
             last_evaluated_at, learned_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                runs_count = excluded.runs_count,
                new_identities_total = excluded.new_identities_total,
                last_run_new_identities = excluded.last_run_new_identities,
                consecutive_empty_runs = excluded.consecutive_empty_runs,
                last_evaluated_at = excluded.last_evaluated_at,
                learned_status = excluded.learned_status
        ''', (source_key, runs_count + 1, current_total, new_this_run,
              consecutive_empty, datetime.now().isoformat(), learned_status))

        summary[source_key] = {"new_this_run": new_this_run,
                               "learned_status": learned_status,
                               "consecutive_empty_runs": consecutive_empty}

    conn.commit()
    return summary


def is_source_exhausted(conn, source_key: str) -> bool:
    """يُستشار قبل إعادة تقييم/زحف عميق لمصدر — مصدر مستنفد لا يُعاد
    فحصه تلقائياً كل دورة (توفير طلبات شبكة، §5.1)."""
    row = conn.execute(
        "SELECT learned_status FROM source_performance WHERE source_key = ?",
        (source_key,)).fetchone()
    return row is not None and row[0] == "exhausted"


def prioritized_active_sources(conn) -> list:
    """المصادر المعتمدة مرتّبة: الأكثر إنتاجاً لقوانين فريدة جديداً أولاً،
    ثم المصادر بلا سجل أداء بعد (جديدة كلياً) — المستنفدة تُستبعد كلياً
    (§5.1: «لا يُعاد تقييمه تلقائياً كل دورة»)، وكذلك المصادر التي
    تراكمت عليها رفضات بشرية كافية (انظر record_rejection أدناه)."""
    rows = conn.execute('''
        SELECT s.base_url, s.name, s.credibility,
               COALESCE(p.new_identities_total, 0) AS total,
               p.learned_status
        FROM sources s
        LEFT JOIN source_performance p ON p.source_key = s.source_key
        WHERE s.status = 'approved'
          AND (p.learned_status IS NULL OR p.learned_status != 'exhausted')
          AND COALESCE(s.rejection_count, 0) < ?
        ORDER BY total DESC
    ''', (REJECTION_EXCLUDE_THRESHOLD,)).fetchall()
    return [dict(r) for r in rows]


def _source_key_by_domain(conn, doc_source_url: str) -> str | None:
    """يطابق نطاق (netloc) رابط الوثيقة الفعلي مع sources.base_url — نفس
    منطق ربط مصدر↔وثيقة في _count_unique_identities_for_source أعلاه
    (source_key الحقيقي يُحسب من base_url الجذري للمصدر، لا من رابط
    الوثيقة المحدَّد، فلا يصح hash مباشر لرابط الوثيقة)."""
    domain = _netloc(doc_source_url)
    if not domain:
        return None
    rows = conn.execute("SELECT source_key, base_url FROM sources").fetchall()
    for r in rows:
        if _netloc(r["base_url"]) == domain:
            return r["source_key"]
    return None


def record_rejection(conn, doc_id: int, source_url: str, category: str,
                     note: str = "") -> dict:
    """يُستدعى من شاشة المراجعة عند رفض نتيجة — التعلّم من التغذية
    الراجعة البشرية (طلب المالك 2026-09-06): «حتى يتعلم الزاحف للمرات
    القادمة». يسجل السبب للتدقيق، ثم:
      1. ينزّل مصداقية المصدر (credibility -= PENALTY، بحد أدنى).
      2. يزيد rejection_count تراكمياً على sources.
      3. عند بلوغ REJECTION_EXCLUDE_THRESHOLD: المصدر يُستبعد تلقائياً
         من بذر الطابور القادم (نفس فحص «مستنفد» — prioritized_active_sources).

    لا مصدر مسجَّل لنطاق هذا الرابط (وثيقة مصدرها ليس ضمن sources
    المُدارة بعد) ⇒ يُسجَّل السبب فقط للتدقيق بلا تأثير على تعلّم مصدر
    غير موجود.
    """
    if category not in REJECTION_CATEGORIES:
        raise ValueError(f"فئة رفض غير معروفة: {category}")
    source_key = _source_key_by_domain(conn, source_url) if source_url else None
    conn.execute('''
        INSERT INTO rejection_reasons (doc_id, source_key, category, note, rejected_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (doc_id, source_key, category, note, datetime.now().isoformat()))

    result = {"source_key": source_key, "credibility": None,
             "rejection_count": None, "excluded": False}
    if source_key:
        row = conn.execute(
            "SELECT credibility, rejection_count FROM sources "
            "WHERE source_key = ?", (source_key,)).fetchone()
        if row is not None:
            new_credibility = max(
                MIN_CREDIBILITY,
                (row[0] or 0.6) - REJECTION_CREDIBILITY_PENALTY)
            new_count = (row[1] or 0) + 1
            conn.execute(
                "UPDATE sources SET credibility = ?, rejection_count = ? "
                "WHERE source_key = ?",
                (new_credibility, new_count, source_key))
            result.update(credibility=new_credibility,
                          rejection_count=new_count,
                          excluded=new_count >= REJECTION_EXCLUDE_THRESHOLD)
    conn.commit()
    return result
