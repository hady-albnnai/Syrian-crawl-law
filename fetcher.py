# -*- coding: utf-8 -*-
"""
fetcher.py
الجالب المهذب — النسخة المحدثة (مع خيار تجاهل robots.txt)
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
#  فحص robots.txt (تطبيق فعلي — دفعة P0)
# ════════════════════════════════════════
# كان هذا الجزء غلافاً فارغاً يعيد True دائماً حتى مع RESPECT_ROBOTS=True.
# الآن: RobotFileParser حقيقي مع تخزين مؤقت لكل مضيف (طلب robots.txt مرة واحدة).
_ROBOT_CACHE = {}  # netloc -> RobotFileParser


def _load_robot_parser(netloc: str, scheme: str = "https"):
    """يجلب robots.txt للمضيف ويبني المحلل. سياسات الأعطال:
    - 401/403 على robots.txt → المصدر يحميه → نعتبر كل شيء ممنوعاً (الأحوط).
    - 404 أو أي 4xx آخر → لا سياسة معلنة → مسموح.
    - خطأ شبكة → لا نوقف الزحف بعطل عابر؛ نعتبره بلا سياسة ونسجل ذلك.
    """
    robots_url = f"{scheme}://{netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        resp = SESSION.get(robots_url, timeout=TIMEOUT)
        if resp.status_code in (401, 403):
            rp.parse(["Disallow: /"])
            insert_log(robots_url, "robots_protected", f"HTTP {resp.status_code} — اعتبرنا كل شيء ممنوعاً", "blocked")
        elif resp.status_code >= 400:
            rp.parse([])  # لا يوجد robots.txt
        else:
            if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "ascii"):
                resp.encoding = resp.apparent_encoding or "utf-8"
            rp.parse(resp.text.splitlines())
            insert_log(robots_url, "robots_loaded", f"HTTP {resp.status_code}", "success")
    except requests.RequestException as exc:
        rp.parse([])
        insert_log(robots_url, "robots_error", f"{type(exc).__name__} — تابعنا بلا سياسة", "warn")
    return rp


def is_allowed(url: str) -> bool:
    """يفحص إذن robots.txt للرابط عبر محلل مخزَّن لكل مضيف."""
    if not RESPECT_ROBOTS:
        return True  # وضع تطوير صريح — الافتصار الآن True في config

    parsed = urlparse(url)
    netloc = parsed.netloc
    if not netloc:
        return False
    if netloc not in _ROBOT_CACHE:
        _ROBOT_CACHE[netloc] = _load_robot_parser(netloc, parsed.scheme or "https")
    return _ROBOT_CACHE[netloc].can_fetch(USER_AGENT, url)


# ════════════════════════════════════════
#  الدالة الرئيسية لجلب الصفحات
# ════════════════════════════════════════
def fetch(url: str) -> dict:
    """
    تجلب صفحة من الإنترنت مع إعادة محاولة وتسجيل كل شيء.
    """
    if not is_allowed(url):
        msg = "ممنوع حسب robots.txt"
        log.info(f"      [X] {msg}")
        insert_log(url, "blocked_robots", msg, "skip")
        return {"ok": False, "status": None, "html": "", "error": "blocked_by_robots"}

    for attempt in range(1, MAX_RETRIES + 1):
        polite_sleep()

        try:
            log.info(f"      → محاولة {attempt}/{MAX_RETRIES}: {url[:75]}...")
            t0 = time.time()
            
            r = SESSION.get(url, timeout=TIMEOUT)
            ms = int((time.time() - t0) * 1000)

            # إصلاح الترميز العربي
            if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"

            if r.status_code == 200:
                log.info(f"      [✓] نجح | {ms}ms | {len(r.content)//1024} KB | ترميز: {r.encoding}")
                insert_log(url, "fetch_success", f"Status 200 - {ms}ms", "success")
                return {
                    "ok": True,
                    "status": 200,
                    "html": r.text,
                    "ms": ms,
                    "final_url": r.url,
                    "encoding": r.encoding,
                }
            else:
                log.info(f"      [X] فشل - الحالة: {r.status_code}")
                insert_log(url, "fetch_failed", f"HTTP {r.status_code}", "fail")
                return {"ok": False, "status": r.status_code, "html": "", "error": f"http_{r.status_code}"}

        except requests.Timeout:
            log.info(f"      [!] انتهت المهلة (Timeout) - محاولة {attempt}")
        except requests.ConnectionError:
            log.info(f"      [!] خطأ في الاتصال - محاولة {attempt}")
        except Exception as e:
            log.info(f"      [!] خطأ غير متوقع: {type(e).__name__}")

        time.sleep(2 ** attempt)  # backoff

    # إذا فشلت كل المحاولات
    msg = f"فشل بعد {MAX_RETRIES} محاولات"
    log.info(f"      [X] {msg}")
    insert_log(url, "fetch_failed", msg, "fail")
    return {"ok": False, "status": None, "html": "", "error": "max_retries_exceeded"}


# ════════════════════════════════════════
#  اختبار سريع
# ════════════════════════════════════════
if __name__ == "__main__":
    log.info("=" * 65)
    log.info("اختبار الجالب المهذب (fetcher.py)")
    log.info("=" * 65)
    log.info(f"RESPECT_ROBOTS = {RESPECT_ROBOTS} ← (نحن نتجاهله حالياً)")
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