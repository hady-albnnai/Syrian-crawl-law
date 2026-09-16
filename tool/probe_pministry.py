# -*- coding: utf-8 -*-
"""probe_pministry.py — مسبار وصول وخريطة روابط لموقع رئاسة الحكومة.

pministry.gov.sy خارج الوصول من نقطة القياس الأمريكية (فشل مصافحة
TLS حتى بكل الخيارات القديمة — قِيس 2026-09-16)، والفحص محسوم لجهاز
المالك داخل سوريا. هذا المسبار يعمل من جهازه فقط:

    python tool\\probe_pministry.py            # الافتراضي pministry.gov.sy
    python tool\\probe_pministry.py https://x  # أي موقع آخر

يطبع: حالة HTTPS/HTTP وrobots وترويسة الخادم، وروابط التشريعات
المرشحة من الصفحة الرئيسية (تشريع/قانون/مرسوم/جريدة...) — ثم تُلصق
النتيجة للمطور ليُبنى المحرك على بنية مقيسة لا تخمين.
"""
import re
import ssl
import sys
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}
KEYWORDS = ("تشريع", "قانون", "مرسوم", "قرار", "جريدة", "نظام",
            "legis", "law", "rule", "decree", "decision", "gazette")
TIMEOUT = 25


def _session():
    """جلسة تتساهل مع TLS الحكومي القديم (شهادات متقادمة/تشفير قديم)."""
    s = requests.Session()
    s.headers.update(UA)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:  # أوپن‌إس‌إل حديث يرفع SECLEVEL افتراضياً — نخفضه للمصافحة
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    class _LegacyTLS(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            kw["ssl_context"] = ctx
            return super().init_poolmanager(*a, **kw)
    s.mount("https://", _LegacyTLS())
    s.verify = False
    return s


def probe(base_url: str) -> int:
    s = _session()
    base = base_url.rstrip("/") + "/"

    for label, url in [("HTTPS", base), ("HTTP", base.replace(":443/", "/"))]:
        if url == base and label == "HTTP":
            url = base.replace("https://", "http://")
        try:
            r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
            print(f"[{label}] {r.status_code} | {len(r.content)} بايت "
                  f"| نهائي: {r.url}")
            if label == "HTTPS" and r.status_code == 200:
                html_text = r.text
                server = r.headers.get("Server", "؟")
                print(f"   الخادم: {server}")
                break
        except Exception as exc:
            print(f"[{label}] فشل: {type(exc).__name__}: {exc}")
    else:
        print("✗ لا وصول للصفحة الرئيسية — الصق هذا الخرج كما هو")
        return 1

    # robots — ماذا يسمح للمحرك المستقبلي؟
    try:
        rr = s.get(urljoin(base, "robots.txt"), timeout=TIMEOUT)
        print(f"[robots] {rr.status_code}")
        for ln in rr.text.splitlines()[:12]:
            if ln.strip():
                print(f"   {ln.strip()[:80]}")
    except Exception as exc:
        print(f"[robots] فشل: {exc}")

    # خريطة روابط التشريعات المرشحة
    links = {}
    for href, label in re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.S):
        label = re.sub(r"<[^>]+>", "", label)
        label = re.sub(r"\s+", " ", label).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base, href)
        if urlsplit(full).netloc != urlsplit(base).netloc:
            continue
        blob = (full + " " + label).lower()
        if any(k in blob for k in KEYWORDS) and full not in links:
            links[full] = label
    print(f"\nروابط تشريعية مرشحة: {len(links)}")
    for url, label in list(links.items())[:40]:
        print(f"  • {label[:55]:57s} ← {url[:85]}")
    if len(links) > 40:
        print(f"  … و{len(links) - 40} أخرى")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://pministry.gov.sy/"
    print(f"═══ مسبار: {target}")
    sys.exit(probe(target))
