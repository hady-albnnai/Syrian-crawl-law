# -*- coding: utf-8 -*-
"""
fetcher.py
الجالب المهذب — احترام robots.txt والتحويلات المحكومة
"""

import sys
import time
import random
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from config import (
    BASE_URL,
    USER_AGENT,
    DELAY_MIN,
    DELAY_MAX,
    TIMEOUT,
    MAX_RETRIES,
    RESPECT_ROBOTS
)
from database import insert_log
from logging_setup import get_log
log = get_log("fetch")

# ════════════════════════════════════════
#  إعداد الجلسة (Session)
# ════════════════════════════════════════
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml",
})

_last_fetch_time = 0


# ════════════════════════════════════════
#  الانتظار المهذب بين الطلبات
# ════════════════════════════════════════
_CRAWL_DELAY: dict = {}          # origin -> ثوانٍ من توجيه Crawl-delay في robots.txt
MAX_CRAWL_DELAY = 30.0           # سقف: توجيه مبالغ فيه لا يجمّد الدورة


def crawl_delay_for(url: str) -> float:
    try:
        p = urlparse(url)
        return _CRAWL_DELAY.get(f"{p.scheme.lower()}://{p.netloc}", 0.0)
    except ValueError:
        return 0.0


_ORIGIN_LAST: dict = {}          # origin -> وقت آخر طلب لنحترم Crawl-delay لكل موقع


def honor_crawl_delay(url: str):
    """ينام ما يكفي ليفصل Crawl-delay المنشور بين طلبين لنفس الموقع (إن وُجد)."""
    delay = crawl_delay_for(url)
    if not delay:
        return
    p = urlparse(url)
    key = f"{p.scheme.lower()}://{p.netloc}"
    wait = delay - (time.time() - _ORIGIN_LAST.get(key, 0.0))
    if wait > 0:
        log.info(f"      ... Crawl-delay {delay:.0f}ث لدى {p.netloc}: انتظار {wait:.1f}ث")
        time.sleep(wait)
    _ORIGIN_LAST[key] = time.time()


def polite_sleep():
    global _last_fetch_time
    elapsed = time.time() - _last_fetch_time
    wait_time = random.uniform(DELAY_MIN, DELAY_MAX)

    if elapsed < wait_time:
        sleep_duration = wait_time - elapsed
        log.info(f"      ... انتظار مهذب {sleep_duration:.1f} ثانية")
        time.sleep(sleep_duration)
    else:
        time.sleep(0.3)

    _last_fetch_time = time.time()


# ════════════════════════════════════════
#  فحص robots.txt وتحويلات آمنة
# ════════════════════════════════════════
# المفتاح الجديد يميّز http/https؛ قراءة netloc القديم محفوظة لتوافق
# الاختبارات/المستدعين التاريخيين الذين يحقنون parser مباشرة.
_ROBOT_CACHE = {}
# سبب آخر إخفاق robots/تحويل لكل origin — للتشخيص فقط (لا يغيّر أي قرار جلب).
BLOCK_REASONS = {}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


def _deny_all_parser(robots_url: str):
    rp = RobotFileParser()
    rp.set_url(robots_url)
    rp.parse(["User-agent: *", "Disallow: /"])
    return rp


_SY_SECOND_LEVEL = {"gov", "com", "edu", "org", "net", "mil", "sch", "med"}


def _sy_registrable(host: str) -> str:
    """النطاق المسجّل لمضيف تحت .sy (gov.sy وأخواتها مستويات عامة)؛ وإلا فارغ.

    لا نوسّع إلى بقية النطاقات العليا: لا نملك قائمة لاحقات عامة، والتساهل
    مقصور على المصادر الرسمية السورية (قرار المالك 2026-10-01).
    """
    labels = [p for p in (host or "").lower().rstrip(".").split(".") if p]
    if len(labels) < 2 or labels[-1] != "sy":
        return ""
    if labels[-2] in _SY_SECOND_LEVEL:
        return ".".join(labels[-3:]) if len(labels) >= 3 else ""
    return ".".join(labels[-2:])


def _same_host_redirect(current_url: str, target_url: str,
                        allow_sy_subdomain: bool = False) -> bool:
    """يسمح بتحويل داخل المضيف نفسه، ولا يسمح بهبوط https إلى http.

    allow_sy_subdomain: لصفحات المحتوى فقط؛ يسمح بالانتقال بين مضيفين فرعيين
    من النطاق المسجّل نفسه تحت .sy (a.x.gov.sy إلى b.x.gov.sy). robots.txt
    يبقى صارماً لأن سياسته خاصة بالمضيف.
    """
    try:
        current, target = urlparse(current_url), urlparse(target_url)
        if current.scheme not in ("http", "https") or target.scheme not in ("http", "https"):
            return False
        if current.scheme == "https" and target.scheme == "http":
            return False
        if target.username or target.password or not target.hostname:
            return False
        a = (current.hostname or "").lower().rstrip(".").removeprefix("www.")
        b = (target.hostname or "").lower().rstrip(".").removeprefix("www.")
        if not a:
            return False
        if a != b:
            reg = _sy_registrable(a)
            if not (allow_sy_subdomain and reg and reg == _sy_registrable(b)):
                return False
        pa = current.port or (80 if current.scheme == "http" else 443)
        pb = target.port or (80 if target.scheme == "http" else 443)
        # انتقال المنفذ الافتراضي بين HTTP وHTTPS مسموح؛ منفذ خدمة خاص
        # لا يخرج إلى منفذ آخر تلقائياً.
        if pa != pb and {pa, pb} != {80, 443}:
            return False
        return True
    except ValueError:
        return False


def _load_robot_parser(netloc: str, scheme: str = "https",
                       record_log: bool = True):
    """يجلب robots.txt. الإخفاق غير المحسوم مغلق افتراضياً.

    404/410 فقط تعنيان عدم وجود سياسة؛ 401/403 وبقية أخطاء HTTP أو الشبكة
    تمنع الجلب مؤقتاً. لا نتبع تحويل robots إلا داخل المضيف نفسه.
    """
    robots_url = f"{scheme}://{netloc}/robots.txt"
    emit_log = insert_log if record_log else (lambda *_a, **_k: None)
    current = robots_url
    for redirect_index in range(MAX_REDIRECTS + 1):
        try:
            polite_sleep()
            resp = SESSION.get(current, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            BLOCK_REASONS[f"{scheme}://{netloc}"] = f"robots_unreachable:{type(exc).__name__}"
            emit_log(robots_url, "robots_error",
                     f"{type(exc).__name__} — fail-closed", "blocked")
            return _deny_all_parser(robots_url)
        status = resp.status_code
        if status in _REDIRECT_STATUSES:
            location = getattr(resp, "headers", {}).get("Location")
            target = urljoin(current, location) if location else ""
            if (not target or redirect_index >= MAX_REDIRECTS or
                    not _same_host_redirect(current, target)):
                BLOCK_REASONS[f"{scheme}://{netloc}"] = f"robots_redirect_to:{target[:60]}"
                emit_log(robots_url, "robots_redirect_blocked",
                         "تحويل robots غير قابل للتحقق — fail-closed", "blocked")
                return _deny_all_parser(robots_url)
            current = target
            continue
        rp = RobotFileParser()
        rp.set_url(current)
        if status in (404, 410):
            rp.parse([])
            emit_log(robots_url, "robots_missing", f"HTTP {status} — لا سياسة منشورة", "success")
            return rp
        if status < 200 or status >= 300:
            BLOCK_REASONS[f"{scheme}://{netloc}"] = f"robots_http_{status}"
            emit_log(robots_url, "robots_protected",
                     f"HTTP {status} — fail-closed", "blocked")
            return _deny_all_parser(robots_url)
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "ascii"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        rp.parse(resp.text.splitlines())
        emit_log(robots_url, "robots_loaded", f"HTTP {status}", "success")
        return rp
    return _deny_all_parser(robots_url)


def is_allowed(url: str, record_log: bool = True) -> bool:
    """يفحص robots لكل origin؛ يمكن تعطيل كتابة سجل DB في وضع المعاينة."""
    if not RESPECT_ROBOTS:
        return True  # تعطيل صريح للتطوير/الاختبار فقط
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        scheme = parsed.scheme.lower()
        if (not parsed.hostname or scheme not in ("http", "https") or
                parsed.username or parsed.password):
            return False
    except ValueError:
        return False
    key = f"{scheme}://{netloc}"
    if key in _ROBOT_CACHE:
        parser = _ROBOT_CACHE[key]
    elif netloc in _ROBOT_CACHE:  # توافق مع cache قديم محقون بالمضيف فقط
        parser = _ROBOT_CACHE[netloc]
    else:
        parser = _load_robot_parser(netloc, scheme, record_log=record_log)
        _ROBOT_CACHE[key] = parser
    try:
        delay = parser.crawl_delay(USER_AGENT)
        if delay:
            _CRAWL_DELAY[key] = min(float(delay), MAX_CRAWL_DELAY)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        return bool(parser.can_fetch(USER_AGENT, url))
    except Exception:
        return False


def classify_error(error: str) -> str:
    """يصنف خطأ الجلب ليقرر الطابور: block / fail / retry.

    - robots                → block  (سياسة مصدر، لا إعادة)
    - 404/410/بقية 4xx      → fail   (عطل محتوي، لا معنى للإعادة)
    - 5xx / مهلة / اتصال    → retry  (عطل عابر)
    """
    if error == "blocked_by_robots" or (error or "").startswith("blocked_by_robots_redirect"):
        return "block"
    if error in {"invalid_url", "redirect_cross_origin", "redirect_loop",
                 "redirect_limit_exceeded", "redirect_missing_location"}:
        return "block"
    if error and error.startswith("http_4"):
        return "fail"
    if error and error.startswith("http_5"):
        return "retry"
    return "retry"


# ════════════════════════════════════════
#  الدالة الرئيسية لجلب الصفحات
# ════════════════════════════════════════
def _get_with_safe_redirects(url: str, record_log: bool = True):
    """يطلب صفحة بلا auto-redirect؛ يعيد (response, final_url, error)."""
    current = url
    try:
        initial = urlparse(current)
        if (initial.scheme not in ("http", "https") or not initial.hostname or
                initial.username or initial.password):
            return None, current, "invalid_url"
    except ValueError:
        return None, current, "invalid_url"
    visited = {current}
    for hop in range(MAX_REDIRECTS + 1):
        if not is_allowed(current, record_log=record_log):
            return None, current, ("blocked_by_robots" if hop == 0
                                   else "blocked_by_robots_redirect")
        polite_sleep()
        honor_crawl_delay(current)
        response = SESSION.get(current, timeout=TIMEOUT, allow_redirects=False)
        if response.status_code not in _REDIRECT_STATUSES:
            return response, current, None
        location = getattr(response, "headers", {}).get("Location")
        if not location:
            return None, current, "redirect_missing_location"
        target = urljoin(current, location)
        if not _same_host_redirect(current, target, allow_sy_subdomain=True):
            BLOCK_REASONS[f"{urlparse(current).scheme}://{urlparse(current).netloc}"] = \
                f"redirect_to:{target[:60]}"
            return None, current, "redirect_cross_origin"
        if target in visited:
            return None, current, "redirect_loop"
        if hop >= MAX_REDIRECTS:
            return None, current, "redirect_limit_exceeded"
        visited.add(target)
        current = target
    return None, current, "redirect_limit_exceeded"


def fetch(url: str, record_log: bool = True) -> dict:
    """جلب مهذب؛ يمكن منع كتابة أحداث DB عند معاينة dry-run."""
    emit_log = insert_log if record_log else (lambda *_a, **_k: None)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"      → محاولة {attempt}/{MAX_RETRIES}: {url[:75]}...")
            t0 = time.time()
            r, final_url, redirect_error = _get_with_safe_redirects(
                url, record_log=record_log)
            ms = int((time.time() - t0) * 1000)
            if redirect_error:
                is_block = classify_error(redirect_error) == "block"
                event = "fetch_policy_block" if is_block else "fetch_failed"
                emit_log(url, event, redirect_error,
                         "blocked" if is_block else "fail")
                return {"ok": False, "status": None, "html": "",
                        "error": redirect_error, "final_url": final_url}

            if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code == 200:
                log.info(f"      [✓] نجح | {ms}ms | {len(r.content)//1024} KB | ترميز: {r.encoding}")
                emit_log(url, "fetch_success", f"Status 200 - {ms}ms", "success")
                return {"ok": True, "status": 200, "html": r.text,
                        "ms": ms, "final_url": final_url,
                        "encoding": r.encoding}
            log.info(f"      [X] فشل - الحالة: {r.status_code}")
            emit_log(url, "fetch_failed", f"HTTP {r.status_code}", "fail")
            return {"ok": False, "status": r.status_code, "html": "",
                    "error": f"http_{r.status_code}", "final_url": final_url}
        except requests.Timeout:
            log.info(f"      [!] انتهت المهلة (Timeout) - محاولة {attempt}")
        except requests.ConnectionError:
            log.info(f"      [!] خطأ في الاتصال - محاولة {attempt}")
        except requests.RequestException as exc:
            log.info(f"      [!] خطأ طلب: {type(exc).__name__} - محاولة {attempt}")
        except Exception as exc:
            log.info(f"      [!] خطأ غير متوقع: {type(exc).__name__}")
        time.sleep(2 ** attempt)

    msg = f"فشل بعد {MAX_RETRIES} محاولات"
    log.info(f"      [X] {msg}")
    emit_log(url, "fetch_failed", msg, "fail")
    return {"ok": False, "status": None, "html": "",
            "error": "max_retries_exceeded"}


# ════════════════════════════════════════
#  اختبار سريع
# ════════════════════════════════════════
if __name__ == "__main__":
    log.info("=" * 65)
    log.info("اختبار الجالب المهذب (fetcher.py)")
    log.info("=" * 65)
    log.info(f"RESPECT_ROBOTS = {RESPECT_ROBOTS} ← سياسة الجلب الفعالة")
    log.info("-" * 65)

    result = fetch(BASE_URL)

    log.info("\n" + "=" * 65)
    log.info("النتيجة النهائية:")
    log.info(f"   النجاح: {result['ok']}")
    if result['ok']:
        log.info(f"   الوقت: {result.get('ms')} مللي ثانية")
        log.info(f"   حجم النص: {len(result['html'])} حرف")
        log.info("\n✅ الجالب يعمل بشكل جيد!")
    else:
        log.info(f"   السبب: {result.get('error')}")
        log.info("\n⚠️  حدث خطأ - أرسل النتيجة كاملة")
    log.info("=" * 65)
