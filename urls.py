# -*- coding: utf-8 -*-
"""urls.py — تطبيع الروابط (التسليم 3). نقطة واحدة بلا استيرادات دائرية."""
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def clean_url(url: str) -> str:
    return url.split('#')[0].split('?')[0].strip()


def canonicalize_url(url: str, keep_params=()) -> str:
    """تطبيع: fragment دوماً خارج، ومعاملات التتبع خارج إلا المُستثنى
    صراحة (start للـ pagination يبقى لأنه يغيّر المحتوى)."""
    u = urlparse(url.split('#')[0].strip())
    query = urlencode([(k, v) for k, v in parse_qsl(u.query) if k in keep_params])
    netloc = u.netloc.lower()
    path = u.path.rstrip('/') or '/'
    return urlunparse((u.scheme.lower(), netloc, path, '', query, ''))
