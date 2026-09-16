# -*- coding: utf-8 -*-
"""
source_matrix.py — قياس مصفوفة المصادر السورية (المرحلة ف٠).

أداة قياس جافة (dry): تقيس لكل مصدر مرشَّح من config.SOURCE_MATRIX_CANDIDATES
سبعة حقول — حل DNS (عبر DoH لتمييز موت النطاق عن حجبه عنا)، الوصول
(HTTP/HTTPS + شهادة مكسورة)، robots، المحرك (وردبريس/phpBB/عام)،
sitemap (عدد الروابط للوردبريس)، العنوان، وفئة الثقة من
source_quality.domain_tier_for_url.

لا تكتب شيئاً في أي قاعدة بيانات — مخرجاتها ملفان في output/ فقط
(JSON للآلة + Markdown للإنسان)، فتصلح لإعادة القياس من أي جهاز
(جهاز المالك تحديداً — المواقع السورية قد تقطع نقاط القياس الأجنبية).

التشغيل:  python3 source_matrix.py
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from config import (MATRIX_HTTP_TIMEOUT, MATRIX_MAX_WORKERS,
                    SOURCE_MATRIX_CANDIDATES, USER_AGENT)
from engines import detect_engine
from logging_setup import get_log
from source_quality import domain_tier_for_url

log = get_log("matrix")

OUT_DIR = Path(__file__).parent / "output"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


# ════════════════════════════ طبقة الشبكة ════════════════════════════
# دوال حقيقية قابلة للاستبدال بحقن بديائل زائفة بالاختبارات (بلا شبكة).

def _fix_encoding(response):
    """ترميز عربي سليم: بلا charset بالترويسة يفترض requests اللاتيني
    فيفسد العناوين العربية (قيس فعلياً على cb/moi/mohamah بف٠) — نفس
    إصلاح fetcher: iso-8859-1/ascii → الترميز المرصود من المحتوى."""
    if response.encoding is None or response.encoding.lower() in (
            "iso-8859-1", "ascii"):
        response.encoding = response.apparent_encoding or "utf-8"
    return response


def real_http_get(url):
    """طلب واحد مهذب. يعيد (status, html, tls_broken).

    status=None عند فشل الاتصال كلياً. الشهادة الناقصة السلسلة (شائعة
    بمواقع gov.sy) تُتَحمَّل معوسم tls_broken — القياس وثائق لا زحف.
    """
    try:
        r = _fix_encoding(requests.get(
            url, timeout=MATRIX_HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT}, allow_redirects=True))
        return r.status_code, (r.text or ""), False
    except requests.exceptions.SSLError:
        try:
            r = _fix_encoding(requests.get(
                url, timeout=MATRIX_HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True, verify=False))
            return r.status_code, (r.text or ""), True
        except requests.exceptions.RequestException:
            return None, "", False
    except requests.exceptions.RequestException:
        return None, "", False


def real_dns_lookup(domain):
    """حل DNS عبر DoH (dns.google): يميز النطاق الميت (NXDOMAIN) عن
    القطع الانتقائي لنقطة القياس. يعيد (الحالة, قائمة IP)."""
    try:
        r = requests.get(f"https://dns.google/resolve?name={domain}&type=A",
                         timeout=MATRIX_HTTP_TIMEOUT)
        data = r.json()
        if data.get("Status") == 3:
            return "nxdomain", []
        ips = [a.get("data") for a in data.get("Answer", []) if a.get("type") == 1]
        return ("ok", ips) if ips else ("nodata", [])
    except (requests.exceptions.RequestException, ValueError):
        return "error", []


# ════════════════════════════ القياس ════════════════════════════

def measure_source(url, name, category, http_get=None, dns_lookup=None):
    """قياس مصدر واحد جافاً — لا كتابة بأي مكان (ذاكرة فقط)."""
    http_get = http_get or real_http_get
    dns_lookup = dns_lookup or real_dns_lookup

    host = urlparse(url).netloc.split(":")[0]
    scheme = urlparse(url).scheme
    dns_state, ips = dns_lookup(host)

    status, html, tls_broken = http_get(url)
    title = ""
    m = _TITLE_RE.search(html or "")
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
    engine = detect_engine(html) if html else ""

    # robots: الغياب أو الخطأ يعني المسموح افتراضياً (عرف robots)
    robots_state, robots_ok = "absent", True
    rst, rhtml, _ = http_get(f"{scheme}://{host}/robots.txt")
    if rst == 200 and (rhtml or "").strip():
        parser = RobotFileParser()
        parser.parse(rhtml.splitlines())
        robots_state = "present"
        robots_ok = parser.can_fetch(USER_AGENT, url)
    elif rst is not None:
        robots_state = f"http_{rst}"

    # sitemap للوردبريس فقط (بنية معروفة تخفض كلفة ف١)
    sitemap_urls = None
    if engine == "wordpress":
        sst, shtml, _ = http_get(f"{scheme}://{host}/wp-sitemap.xml")
        sitemap_urls = shtml.count("<loc>") if sst == 200 else 0

    return {
        "name": name,
        "url": url,
        "category": category,
        "tier": domain_tier_for_url(url),
        "dns": dns_state,
        "ips": ips[:2],
        "status": status,
        "alive": bool(status is not None and 200 <= status < 400),
        "tls_broken": tls_broken,
        "title": title,
        "engine": engine,
        "robots": robots_state,
        "robots_allowed": robots_ok,
        "sitemap_urls": sitemap_urls,
    }


def run(candidates=None, http_get=None, dns_lookup=None):
    """قياس كل المرشحين وتوليد المخرجات. يعيد الصفوف للمتصل."""
    cands = list(candidates or SOURCE_MATRIX_CANDIDATES)
    rows = []
    with ThreadPoolExecutor(max_workers=MATRIX_MAX_WORKERS) as pool:
        futures = {pool.submit(measure_source, u, n, c, http_get, dns_lookup): n
                   for u, n, c in cands}
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as exc:  # مصدر واحد لا يُسقط القياس كله
                log.warning(f"فشل قياس {futures[fut]}: {exc}")
    rows.sort(key=lambda r: (r["tier"], r["category"], r["name"]))

    OUT_DIR.mkdir(exist_ok=True)
    stamp = date.today().isoformat()
    (OUT_DIR / f"source_matrix_{stamp}.json").write_text(
        json.dumps({"measured_at": stamp, "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_markdown(rows, stamp)
    (OUT_DIR / f"source_matrix_{stamp}.md").write_text(md, encoding="utf-8")

    alive = sum(1 for r in rows if r["alive"])
    dead = len(rows) - alive
    nx = sum(1 for r in rows if r["dns"] == "nxdomain")
    log.info(f"قِيست {len(rows)} مصدراً: {alive} حي، {dead} ميت/محجوب "
             f"(منها {nx} نطاق ميت NXDOMAIN)")
    log.info(f"المخرجات: output/source_matrix_{stamp}.{{json,md}}")
    return rows


# ════════════════════════════ العرض ════════════════════════════

def render_markdown(rows, stamp):
    """توليد جدول Markdown للمصفوفة + ملخص إحصائي مختصر."""
    lines = [
        "# مصفوفة المصادر السورية — قياس آلي (ف٠)",
        "",
        f"**تاريخ القياس:** {stamp} — الأداة: `source_matrix.py` (قياس جاف dry)",
        "",
        "> ⚠️ القياس من نقطة واحدة؛ مواقع gov.sy قد تقطع نقاطاً أجنبية.",
        "> الحكم النهائي لإعادة القياس من جهاز المالك.",
        "",
        "| المصدر | الفئة | تير | DNS | HTTP | TLS | المحرك | robots | sitemap | العنوان |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['category']} | {r['tier']} "
            f"| {r['dns']} | {r['status'] if r['status'] is not None else '—'} "
            f"| {'مكسور' if r['tls_broken'] else '—'} "
            f"| {r['engine'] or '—'} "
            f"| {r['robots']}{'' if r['robots_allowed'] else ' (ممنوع)'} "
            f"| {r['sitemap_urls'] if r['sitemap_urls'] is not None else '—'} "
            f"| {r['title'][:40]} |"
        )
    alive = [r for r in rows if r["alive"]]
    lines += [
        "",
        "## ملخص",
        "",
        f"- قِيست {len(rows)} مصدراً: **{len(alive)} حيّ**، {len(rows) - len(alive)} ميت/محجوب",
        f"- نطاقات ميتة (NXDOMAIN): {sum(1 for r in rows if r['dns'] == 'nxdomain')}",
        f"- يمنعنا robots: {sum(1 for r in rows if not r['robots_allowed'])}",
        f"- حسب التير: " + "، ".join(
            f"تير {t}: {sum(1 for r in rows if r['tier'] == t)}"
            for t in sorted({r['tier'] for r in rows})),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    run()
