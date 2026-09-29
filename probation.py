"""مرحلة الاختبار (probation) — اعتماد آلي مشروط بعينة حقيقية من المصدر.

لماذا؟ تقييم صفحة واحدة لا يكفي لقرار بلا إنسان. قبل أن يُعتمد مصدر مكتشف
آلياً نجلب عينة صغيرة (≈12 صفحة قانونية من نفس الموقع) **دون حفظ أي وثيقة**،
ونقيس: كم صفحة قانونية فيها، هل هي سورية، هل تتسرب إليها تشريعات دول أخرى
(كحالة «الشامل»: تشريعات سورية + 21 دولة عربية)، وكم منها جديد علينا.

القرار (كله مسجَّل في evaluation_reasons_json وقابل للعكس بـ sources approve/reject):
  promote → اعتماد (decided_by='auto-probation')
  reject  → رفض   (decided_by='auto-probation') عند تسرب أجنبي واضح
  hold    → يبقى مقترحاً (عينة قليلة/غير حاسمة) ويظهر للمراجعة

لا يمسّ مصدراً قرّره المالك يدوياً (decided_by='user').
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from discovery import _LEGAL_LINK_RE, _normal_host, evaluate_candidate
from extractor_v4 import extract_main_content
from fetcher import fetch
from jurisdiction import assess_jurisdiction
from logging_setup import get_log
from urls import canonicalize_url

log = get_log("probation")

SAMPLE_PAGES = 12            # صفحات العينة (سوى الصفحة الرئيسية)
MAX_PER_RUN = 6              # مصادر تُختبر في الدورة الواحدة
MIN_OK_PAGES = 4             # أقل عدد صفحات ناجحة لقرار
MIN_LAW_PAGES = 3            # أقل عدد صفحات قانونية (بها مواد)
MIN_COMPATIBLE_SHARE = 0.7   # حصة الصفحات القانونية غير المخالفة لسورية
MAX_FOREIGN_SHARE = 0.10     # فوقها: تسرب أجنبي → رفض


def sample_urls(html: str, base_url: str, limit: int = SAMPLE_PAGES) -> list:
    """روابط داخلية قانونية موزّعة على القائمة (لا أول N فقط)."""
    host = _normal_host(base_url)
    seen, found = {canonicalize_url(base_url)}, []
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except Exception:
        return []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, (a["href"] or "").strip())
        if urlparse(href).scheme not in ("http", "https") or _normal_host(href) != host:
            continue
        signal = a.get_text(" ", strip=True) + " " + urlparse(href).path
        if not _LEGAL_LINK_RE.search(signal):
            continue
        key = canonicalize_url(href)
        if key in seen:
            continue
        seen.add(key)
        found.append(href)
    if len(found) <= limit:
        return found
    step = len(found) / limit
    return [found[int(i * step)] for i in range(limit)]


def _is_known(conn, url: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM documents WHERE source_url = ? LIMIT 1",
                            (canonicalize_url(url),)).fetchone() is not None
    except Exception:
        return False


def measure_sample(conn, base_url: str, fetch_fn=fetch, sample_fn=sample_urls,
                   limit: int = SAMPLE_PAGES) -> dict:
    """يجلب العينة ويقيس؛ لا يكتب في DB ولا في crawl_log."""
    m = {"pages_ok": 0, "pages_failed": 0, "law_pages": 0, "syrian_pages": 0,
         "foreign_pages": 0, "compatible_law_pages": 0, "unknown_pages": 0,
         "new_pages": 0, "foreign_countries": [], "sampled": []}
    first = fetch_fn(base_url, record_log=False)
    if not first.get("ok"):
        m["error"] = first.get("error", "fetch_failed")
        return m
    urls = sample_fn(first.get("html") or "", first.get("final_url") or base_url, limit)
    pages = [(base_url, first)]
    for u in urls:
        try:
            pages.append((u, fetch_fn(u, record_log=False)))
        except Exception as exc:  # عطل صفحة لا يُسقط العينة
            pages.append((u, {"ok": False, "error": str(exc)}))
    for url, res in pages:
        if not res.get("ok"):
            m["pages_failed"] += 1
            continue
        html = res.get("html") or ""
        final = res.get("final_url") or url
        m["pages_ok"] += 1
        m["sampled"].append(final)
        ext = extract_main_content(html, final)
        arts = [a for a in (ext.get("articles") or []) if not a.get("is_preamble")] \
            if ext.get("success") else []
        soup = BeautifulSoup(html, "lxml")
        text = (soup.body or soup).get_text(" ", strip=True)
        j = assess_jurisdiction(final, ext.get("title") or "", text, "")
        v = j["verdict"]
        if v == "syrian":
            m["syrian_pages"] += 1
        elif v in ("foreign", "mixed"):
            m["foreign_pages"] += 1
            if j.get("foreign_country"):
                m["foreign_countries"].append(j["foreign_country"])
        else:
            m["unknown_pages"] += 1
        if arts:
            m["law_pages"] += 1
            if v == "syrian" or (v == "unknown" and j["foreign_score"] == 0):
                m["compatible_law_pages"] += 1
        if not _is_known(conn, final):
            m["new_pages"] += 1
    return m


def decide_from_metrics(m: dict) -> tuple:
    """(promote|reject|hold, سبب) — دالة نقية قابلة للاختبار."""
    ok = m.get("pages_ok", 0)
    if m.get("error"):
        return "hold", f"تعذر جلب المصدر: {m['error']}"
    if ok < MIN_OK_PAGES:
        return "hold", f"عينة غير كافية: {ok} صفحة ناجحة (المطلوب {MIN_OK_PAGES})"
    foreign_share = m["foreign_pages"] / ok
    if foreign_share > MAX_FOREIGN_SHARE:
        c = "، ".join(sorted(set(m.get("foreign_countries") or []))) or "غير محدد"
        return "reject", (f"تسرب أجنبي: {m['foreign_pages']}/{ok} صفحة "
                          f"({foreign_share:.0%}) — {c}")
    if m["law_pages"] < MIN_LAW_PAGES:
        return "hold", (f"صفحات بمواد قانونية {m['law_pages']} فقط "
                        f"(المطلوب {MIN_LAW_PAGES})")
    share = m["compatible_law_pages"] / m["law_pages"]
    if share < MIN_COMPATIBLE_SHARE:
        return "hold", f"الصفحات القانونية المتوافقة مع سورية {share:.0%} دون {MIN_COMPATIBLE_SHARE:.0%}"
    return "promote", (f"عينة {ok} صفحة: {m['law_pages']} قانونية "
                       f"({share:.0%} متوافقة مع سورية)، أجنبي {m['foreign_pages']}، "
                       f"جديد علينا {m['new_pages']}")


def _annotate(conn, source_id: int, note: str):
    row = conn.execute("SELECT evaluation_reasons_json FROM sources WHERE id=?",
                       (source_id,)).fetchone()
    try:
        reasons = json.loads(row[0]) if row and row[0] else []
    except (TypeError, ValueError):
        reasons = []
    reasons.insert(0, note)
    conn.execute("UPDATE sources SET evaluation_reasons_json=? WHERE id=?",
                 (json.dumps(reasons[:12], ensure_ascii=False), source_id))


def _decide(conn, source_id: int, approve: bool):
    """قرار بمعرّف المصدر (لا بمفتاح مُعاد حسابه — قد يختلف في مصادر قديمة)."""
    from datetime import datetime
    conn.execute("UPDATE sources SET status=?, decided_at=?, decided_by=? WHERE id=?",
                 ("approved" if approve else "rejected",
                  datetime.now().isoformat(), "auto-probation", source_id))


def run_probation(conn, max_sources: int = MAX_PER_RUN, dry_run: bool = False,
                  evaluate_fn=evaluate_candidate, measure_fn=measure_sample,
                  stop_event=None) -> dict:
    """يختبر المقترحات الموصى بها آلياً ويقرر. يعيد إحصاءات + قائمة القرارات."""
    from autopilot import auto_verdict   # استيراد متأخر: تفادي الدوران
    stats = {"tested": 0, "promoted": 0, "rejected": 0, "held": 0,
             "skipped_gate": 0, "decisions": []}
    rows = conn.execute(
        "SELECT id, base_url FROM sources WHERE status='proposed' "
        "AND COALESCE(decided_by,'') != 'user' "
        "AND evaluation_verdict='recommended' "
        "ORDER BY evaluation_score DESC, id LIMIT ?", (max_sources,)).fetchall()
    for row in rows:
        if stop_event is not None and stop_event.is_set():
            break
        sid, url = row["id"], row["base_url"]
        try:
            ev = evaluate_fn(url, record_log=False)
        except Exception as exc:
            log.info(f"   ❌ probation #{sid}: عطل تقييم {exc}")
            continue
        ok, why = auto_verdict(ev)
        if not ok or ev.jurisdiction != "syrian":
            stats["skipped_gate"] += 1
            reason = why if not ok else f"الاختصاص {ev.jurisdiction} لا يجتاز الاعتماد الآلي"
            stats["decisions"].append({"id": sid, "url": url, "decision": "gate",
                                       "reason": reason})
            log.info(f"   ⏸ #{sid} لم يدخل الاختبار: {reason}")
            continue
        m = measure_fn(conn, url)
        decision, reason = decide_from_metrics(m)
        stats["tested"] += 1
        stats["decisions"].append({"id": sid, "url": url, "decision": decision,
                                   "reason": reason, "metrics": m})
        log.info(f"   🧪 #{sid} {decision}: {reason}")
        if dry_run:
            continue
        note = f"اختبار آلي ({decision}): {reason}"
        _annotate(conn, sid, note)
        if decision == "promote":
            _decide(conn, sid, True)
            stats["promoted"] += 1
        elif decision == "reject":
            _decide(conn, sid, False)
            stats["rejected"] += 1
        else:
            stats["held"] += 1
        conn.commit()
    return stats
