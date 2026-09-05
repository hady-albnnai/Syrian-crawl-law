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
    (§5.1: «لا يُعاد تقييمه تلقائياً كل دورة»)."""
    rows = conn.execute('''
        SELECT s.base_url, s.name, s.credibility,
               COALESCE(p.new_identities_total, 0) AS total,
               p.learned_status
        FROM sources s
        LEFT JOIN source_performance p ON p.source_key = s.source_key
        WHERE s.status = 'approved'
          AND (p.learned_status IS NULL OR p.learned_status != 'exhausted')
        ORDER BY total DESC
    ''').fetchall()
    return [dict(r) for r in rows]
