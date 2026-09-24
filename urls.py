# -*- coding: utf-8 -*-
"""urls.py — تطبيع الروابط (التسليم 3). نقطة واحدة بلا استيرادات دائرية."""
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def clean_url(url: str) -> str:
    return url.split('#')[0].split('?')[0].strip()


# معاملات تحمل هوية الصفحة لا التتبع: قصّها يحوّل «قانون بعينه» إلى
# الصفحة الرئيسية (parliament.gov.sy index.php?cat=&node= — عطل 2026-09-24).
# تُحفظ دائماً، مرتّبة بالاسم لثبات المفتاح.
CONTENT_PARAMS = frozenset({
    "node", "cat", "id", "nid", "p", "page_id", "post", "t", "f",
    "article", "law", "doc", "topic", "view", "task", "option",
})


def canonicalize_url(url: str, keep_params=()) -> str:
    """تطبيع: fragment دوماً خارج، ومعاملات التتبع خارج إلا المُستثنى
    صراحة (start للـ pagination يبقى لأنه يغيّر المحتوى) ومعاملات
    المحتوى (CONTENT_PARAMS) التي تحدد الصفحة نفسها."""
    u = urlparse(url.split('#')[0].strip())
    keep = set(keep_params) | CONTENT_PARAMS
    pairs = sorted((k, v) for k, v in parse_qsl(u.query) if k in keep)
    query = urlencode(pairs)
    netloc = u.netloc.lower()
    path = u.path.rstrip('/') or '/'
    return urlunparse((u.scheme.lower(), netloc, path, '', query, ''))
