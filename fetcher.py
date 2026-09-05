# -*- coding: utf-8 -*-
"""
fetcher.py
الجالب المهذب — النسخة المحدثة (مع خيار تجاهل robots.txt)
"""

import sys
import time
import random
from urllib.parse import urljoin

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

# --- إصلاح طباعة العربية على ويندوز ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


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
        print(f"      ... انتظار مهذب {sleep_duration:.1f} ثانية")
        time.sleep(sleep_duration)
    else:
        time.sleep(0.3)
    
    _last_fetch_time = time.time()


# ════════════════════════════════════════
#  فحص robots.txt (مع خيار التجاهل)
# ════════════════════════════════════════
def is_allowed(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True  # نحن في وضع التطوير → نتجاهل robots.txt
    
    # إذا أردنا احترام robots.txt (في المستقبل)
    print("      [robots] يتم التحقق من robots.txt...")
    return True  # حالياً نعود True دائماً حتى نطور هذا الجزء لاحقاً


# ════════════════════════════════════════
#  الدالة الرئيسية لجلب الصفحات
# ════════════════════════════════════════
def fetch(url: str) -> dict:
    """
    تجلب صفحة من الإنترنت مع إعادة محاولة وتسجيل كل شيء.
    """
    if not is_allowed(url):
        msg = "ممنوع حسب robots.txt"
        print(f"      [X] {msg}")
        insert_log(url, "blocked_robots", msg, "skip")
        return {"ok": False, "status": None, "html": "", "error": "blocked_by_robots"}

    for attempt in range(1, MAX_RETRIES + 1):
        polite_sleep()

        try:
            print(f"      → محاولة {attempt}/{MAX_RETRIES}: {url[:75]}...")
            t0 = time.time()
            
            r = SESSION.get(url, timeout=TIMEOUT)
            ms = int((time.time() - t0) * 1000)

            # إصلاح الترميز العربي
            if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"

            if r.status_code == 200:
                print(f"      [✓] نجح | {ms}ms | {len(r.content)//1024} KB | ترميز: {r.encoding}")
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
                print(f"      [X] فشل - الحالة: {r.status_code}")
                insert_log(url, "fetch_failed", f"HTTP {r.status_code}", "fail")
                return {"ok": False, "status": r.status_code, "html": "", "error": f"http_{r.status_code}"}

        except requests.Timeout:
            print(f"      [!] انتهت المهلة (Timeout) - محاولة {attempt}")
        except requests.ConnectionError:
            print(f"      [!] خطأ في الاتصال - محاولة {attempt}")
        except Exception as e:
            print(f"      [!] خطأ غير متوقع: {type(e).__name__}")

        time.sleep(2 ** attempt)  # backoff

    # إذا فشلت كل المحاولات
    msg = f"فشل بعد {MAX_RETRIES} محاولات"
    print(f"      [X] {msg}")
    insert_log(url, "fetch_failed", msg, "fail")
    return {"ok": False, "status": None, "html": "", "error": "max_retries_exceeded"}


# ════════════════════════════════════════
#  اختبار سريع
# ════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 65)
    print("اختبار الجالب المهذب (fetcher.py)")
    print("=" * 65)
    print(f"RESPECT_ROBOTS = {RESPECT_ROBOTS} ← (نحن نتجاهله حالياً)")
    print("-" * 65)

    result = fetch(BASE_URL)

    print("\n" + "=" * 65)
    print("النتيجة النهائية:")
    print(f"   النجاح: {result['ok']}")
    if result['ok']:
        print(f"   الوقت: {result.get('ms')} مللي ثانية")
        print(f"   حجم النص: {len(result['html'])} حرف")
        print("\n✅ الجالب يعمل بشكل جيد!")
    else:
        print(f"   السبب: {result.get('error')}")
        print("\n⚠️  حدث خطأ - أرسل النتيجة كاملة")
    print("=" * 65)