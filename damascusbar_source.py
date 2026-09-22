# -*- coding: utf-8 -*-
"""
damascusbar_source.py — ف٣ (أ-2) المصدر الثاني: منتدى محامي سوريا (damascusbar.org/AlMuntada)
عبر أرشيف Wayback — المنتدى نفسه أُزيل من الخادم (404).

المسار:
  ١. CDX مرة واحدة: كل لقطات 200 لـ showthread.php ⇒ {رقم الخيط: أحدث طابع} تُخزَّن في
     `data/damascusbar_threads.json` (4,615 خيطاً وقت القياس 2026-09-21).
  ٢. لكل خيط: `web.archive.org/web/<ts>id_/http://www.damascusbar.org/AlMuntada/showthread.php?t=N`
     — الترميز windows-1256 يُفك صراحة.
  ٣. نص المشاركات (`post_message_*`) ⇒ `precedent_parser.parse_text` ⇒ `precedent_source.upsert_citation`
     بحالة «بانتظار المراجعة»؛ كل خيط مُعالَج (ولو بلا استشهاد — ~90% منها) يُسجَّل في ملف
     التقدّم `data/damascusbar_done.json` كي لا يُجلب ثانية.
الأدب: تأخير fetcher المهذب قبل كل طلب؛ Wayback يحدّ المعدل (≈ طلب/3 ثوانٍ).
"""
from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
import config
from logging_setup import get_log
from precedent_parser import parse_text
from precedent_source import ingest_page

log = get_log("damascusbar")

SOURCE_SITE = "damascusbar.org"
MAX_CONSECUTIVE_FAILURES = 5
ORIGINAL = "http://www.damascusbar.org/AlMuntada/showthread.php?t={t}"
CDX_URL = ("https://web.archive.org/cdx/search/cdx?url=damascusbar.org/AlMuntada/showthread.php*"
           "&filter=statuscode:200&fl=original,timestamp&limit=100000")
SNAPSHOT = "https://web.archive.org/web/{ts}id_/{orig}"


def _data_dir() -> Path:            # بجوار قاعدة البيانات (يتبع config.DB_PATH في الاختبارات)
    return Path(config.DB_PATH).parent


def _threads_file() -> Path:
    return _data_dir() / "damascusbar_threads.json"


def _done_file() -> Path:
    return _data_dir() / "damascusbar_done.json"

_T_RE = re.compile(r"[?&]t=(\d+)")
_POST_RE = re.compile(r'<div id="post_message_(\d+)">(.*?)</div>\s*</td>', re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


# ------------------------------------------------------------------ CDX → خيوط
def thread_map(cdx_text: str) -> dict[str, list]:
    """نص CDX (original timestamp لكل سطر) ⇒ {رقم الخيط: [أحدث طابع زمني, الرابط الأصلي كما أُرشف]}.

    الرابط يُحفظ حرفياً (www أو بدونه، معاملات الجلسة…) لأن الأرشيف يعيد 404 لأي صيغة أخرى."""
    best: dict[str, list] = {}
    for line in (cdx_text or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        m = _T_RE.search(parts[0])
        if not m:
            continue
        t, ts = m.group(1), parts[1]
        # الأنظف أولاً (بلا معرّف جلسة s= ولا &amp; ولا mode=)، ثم الأحدث
        rank = (_url_noise(parts[0]), -int(ts[:14] or 0))
        if t not in best or rank < best[t][2]:
            best[t] = [ts, parts[0], rank]
    return {t: v[:2] for t, v in best.items()}


def _url_noise(u: str) -> int:
    return ("&amp;" in u) * 4 + ("s=" in u) * 2 + ("mode=" in u or "goto=" in u) * 1


def load_threads(http_get_text, refresh: bool = False) -> dict[str, str]:
    """يقرأ خريطة الخيوط من الملف أو يبنيها من CDX ويخزّنها."""
    if _threads_file().exists() and not refresh:
        return json.loads(_threads_file().read_text(encoding="utf-8"))
    body = http_get_text(CDX_URL)
    m = thread_map(body or "")
    if m:
        _data_dir().mkdir(parents=True, exist_ok=True)
        _threads_file().write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def _load_done() -> dict:
    if _done_file().exists():
        return json.loads(_done_file().read_text(encoding="utf-8"))
    return {}


def _save_done(d: dict) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _done_file().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ HTML → نص
def _clean(x: str) -> str:
    x = re.sub(r"<br\s*/?>", "\n", x, flags=re.I)
    x = re.sub(r"</(p|div|tr|li|h\d)>", "\n", x, flags=re.I)
    x = re.sub(r"<[^>]+>", "", x)
    x = _html.unescape(x)
    x = re.sub(r"[ \t\xa0]+", " ", x)
    return re.sub(r"\n{3,}", "\n\n", x).strip()


def thread_text(page_html: str) -> str:
    """نص كل المشاركات في الخيط مفصولة بسطرين (المشاركة الأولى تحمل الاجتهادات غالباً)."""
    return "\n\n".join(_clean(p) for _pid, p in _POST_RE.findall(page_html or ""))


def thread_title(page_html: str) -> str:
    m = _TITLE_RE.search(page_html or "")
    return _clean(m.group(1)).replace("- منتدى محامي سوريا", "").strip() if m else ""


def decode_snapshot(raw: bytes) -> str:
    """vBulletin القديم يبث windows-1256 بلا ترويسة صحيحة."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("windows-1256", "replace")


# ------------------------------------------------------------------ الدورة
def harvest_damascusbar(conn, http_get_bytes, http_get_text=None, limit: int | None = None,
                        dry_run: bool = False, refresh_threads: bool = False) -> dict:
    """`http_get_bytes(url) -> bytes|None` للقطات، `http_get_text(url) -> str|None` لـ CDX.

    التقدّم يُحفظ في `data/damascusbar_done.json` {رقم الخيط: عدد الاستشهادات} بعد كل خيط،
    فالتوقف والاستئناف آمنان.
    """
    http_get_text = http_get_text or (lambda u: (lambda b: b.decode("utf-8", "replace") if b else None)(http_get_bytes(u)))
    threads = load_threads(http_get_text, refresh=refresh_threads)
    done = _load_done()
    report = {"threads": len(threads), "already_done": 0, "fetched": 0, "failed": 0,
              "with_precedents": 0, "citations": 0, "new_decisions": 0, "new_principles": 0,
              "unsourced": 0, "pages": []}
    n = 0
    consecutive = 0
    for t in sorted(threads, key=int):
        if limit is not None and n >= limit:
            break
        if t in done and not dry_run:
            report["already_done"] += 1
            continue
        ts, archived = threads[t]
        orig = ORIGINAL.format(t=t)          # المعرّف الثابت في citations.source_url
        raw = http_get_bytes(SNAPSHOT.format(ts=ts, orig=archived))
        n += 1
        if not raw:
            report["failed"] += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                report["aborted"] = ("توقف: %d فشل متتالٍ — أرشيف الإنترنت (web.archive.org) غير قابل للوصول "
                                     "من هذه الشبكة أو يحدّ المعدل؛ أعد المحاولة لاحقاً أو عبر شبكة أخرى" % consecutive)
                log.error(report["aborted"])
                break
            continue
        consecutive = 0
        page = decode_snapshot(raw)
        report["fetched"] += 1
        text = thread_text(page)
        if dry_run:
            cs = parse_text(text)
            st = {"thread": t, "title": thread_title(page), "citations": len(cs),
                  "exportable": sum(c.is_exportable() for c in cs),
                  "unsourced": sum(1 for c in cs if not c.identity_key())}
            report["citations"] += st["citations"]
            report["unsourced"] += st["unsourced"]
        else:
            st = ingest_page(conn, orig, page, source_site=SOURCE_SITE, snapshot_ts=ts,
                             text_fn=thread_text)
            st["thread"], st["title"] = t, thread_title(page)
            for k in ("citations", "new_decisions", "new_principles", "unsourced"):
                report[k] += st[k]
            done[t] = st["written"]
            _save_done(done)
        if st["citations"]:
            report["with_precedents"] += 1
        report["pages"].append(st)
    return report
