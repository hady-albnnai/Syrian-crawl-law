# -*- coding: utf-8 -*-
"""drive_source.py — تنزيل ملفات جوجل درايف العامة برمجياً (ف٥، 2026-09-23).

مرفقات فرع نقابة حمص (ونحوها) مرفوعة على درايف بروابط مشاركة عامة.
الملفات الصغيرة تُنزَّل مباشرة من `uc?export=download`؛ الكبيرة يعرض درايف
بوابة تأكيد (صفحة فحص فيروسات) تُعالج هنا باستخراج رمز التأكيد من النموذج
وإعادة الطلب. قِيس ذلك فعلياً على ملفات النقابة الثمانية.

الأنواع المدعومة لاحقاً يحددها المستدعي من بصمة البايتات:
  %PDF- ⇒ PDF | PK ⇒ مضغوط/وورد | Rar! ⇒ يحتاج فكا يدويا (لا مفك في الاعتماديات).
"""
from __future__ import annotations

import re

import requests

from config import USER_AGENT
from logging_setup import get_log

log = get_log("drive_source")

_HEADERS = {"User-Agent": USER_AGENT,
            "Accept-Language": "ar,en;q=0.8"}   # بوابة التأكيد تعرب الحقول


def extract_file_id(url_or_id: str) -> str | None:
    """معرف الملف من أي صيغة مشاركة شائعة، أو المدخل نفسه إن كان معرفاً."""
    s = (url_or_id or "").strip()
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", s)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9_-]{10,}", s) else None


def _looks_like_gate(content: bytes) -> bool:
    return content[:5] != b"%PDF-" and (
        b"<html" in content[:2000].lower() or b"<!DOCTYPE" in content[:2000])


def download_drive(url_or_id: str, timeout: int = 300) -> bytes | None:
    """بايتات الملف، أو None إن تعذر (حذف/صلاحيات/بوابة لم تُحل)."""
    fid = extract_file_id(url_or_id)
    if not fid:
        log.warning(f"رابط درايف غير مفهوم: {url_or_id}")
        return None
    s = requests.Session()
    s.headers.update(_HEADERS)
    url = f"https://drive.google.com/uc?export=download&id={fid}"
    try:
        r = s.get(url, timeout=timeout)
        if r.status_code == 404:
            log.warning("الملف محذوف أو رابط المشاركة ملغى (404)")
            return None
        if not _looks_like_gate(r.content):
            return r.content
        # بوابة التأكيد: استخرج الحقول المخفية وأعد الطلب عليها (الصيغة الحديثة)
        html = r.content.decode("utf-8", "ignore")
        action = re.search(r'action="([^"]+)"', html)
        fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', html))
        if action and fields.get("id"):
            target = action.group(1).replace("&amp;", "&")
            r2 = s.get(target, params=fields, timeout=timeout)
            if not _looks_like_gate(r2.content):
                return r2.content
        # الصيغة القديمة: رمز «confirm» داخل الصفحة
        m = re.search(r'confirm=([0-9A-Za-z_-]+)', html)
        if m:
            r2 = s.get(f"{url}&confirm={m.group(1)}", timeout=timeout)
            if not _looks_like_gate(r2.content):
                return r2.content
        log.warning("بوابة تأكيد درايف لم تُحل — نزّل الملف يدوياً واستعمل precedents-file")
        return None
    except requests.RequestException as e:
        log.warning(f"فشل تنزيل درايف: {e.__class__.__name__}")
        return None


def sniff_kind(data: bytes) -> str:
    """نوع المحتوى من بصمته: pdf | zip | rar | doc | text | unknown."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[:6] == b"Rar!\x1a\x07":
        return "rar"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    try:
        head = data[:200].decode("utf-8")
        if "<html" in head.lower():
            return "html"
    except UnicodeDecodeError:
        pass
    return "unknown"
