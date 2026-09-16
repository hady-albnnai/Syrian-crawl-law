# -*- coding: utf-8 -*-
"""اختبارات source_matrix — محلية بلا شبكة (حقن طبقة HTTP/DNS زائفة).

تحرس مواصفة ف٠: قياس جاف بلا كتابة، تمييز النطاق الميت عن المحجوب،
احترام robots، واكتشاف بنية الوردبريس (بوابة ف١).
"""
import source_matrix as sm
from config import DEFAULT_DOMAIN_TIER, SOURCE_MATRIX_CANDIDATES
from source_quality import OFFICIAL_DOMAIN_TIERS


# ─────────────────────── سلامة قائمة المرشحين ───────────────────────

def test_candidates_sane():
    assert len(SOURCE_MATRIX_CANDIDATES) >= 30
    for url, name, category in SOURCE_MATRIX_CANDIDATES:
        assert url.startswith(("http://", "https://"))
        assert name.strip() and category.strip()


def test_momc_removed_from_official_tiers():
    """تصحيح ف٠: momc.gov.sy وزارة الإعلام — لا تنشر تشريعات، فلا
    تبقى بقائمة الناشرين التشريعيين وتعود للفئة الافتراضية."""
    assert "momc.gov.sy" not in OFFICIAL_DOMAIN_TIERS
    from source_quality import domain_tier_for_url
    assert domain_tier_for_url("https://momc.gov.sy/x") == DEFAULT_DOMAIN_TIER


# ─────────────────────── طبقات شبكة زائفة ───────────────────────

def _wp_site(url):
    """موقع ووردبريس حي يسمح robots."""
    if url.endswith("/robots.txt"):
        return 200, "User-agent: *\nDisallow: /private/\n", False
    if url.endswith("/wp-sitemap.xml"):
        return 200, "<urlset><url><loc>a</loc></url><url><loc>b</loc></url></urlset>", False
    return 200, ('<html><head><title>وزارة العدل</title></head>'
                 '<body class="wp-content">نص</body></html>'), False


def _dead(url):
    return None, "", False


def test_measure_live_wordpress():
    row = sm.measure_source("https://moj.gov.sy/", "وزارة العدل", "تشريع",
                            http_get=_wp_site,
                            dns_lookup=lambda h: ("ok", ["1.2.3.4"]))
    assert row["alive"] is True
    assert row["engine"] == "wordpress"
    assert row["robots"] == "present" and row["robots_allowed"] is True
    assert row["sitemap_urls"] == 2
    assert row["tier"] == 2
    assert "وزارة العدل" in row["title"]


def test_measure_dead_nxdomain():
    row = sm.measure_source("https://parliament.gov.sy/", "مجلس الشعب", "تشريع",
                            http_get=_dead, dns_lookup=lambda h: ("nxdomain", []))
    assert row["dns"] == "nxdomain"
    assert row["alive"] is False
    assert row["engine"] == ""
    assert row["robots"] == "absent" and row["robots_allowed"] is True


def test_robots_disallow_blocks():
    def blocked(url):
        if url.endswith("/robots.txt"):
            return 200, "User-agent: *\nDisallow: /\n", False
        return 200, "<html><title>x</title></html>", False

    row = sm.measure_source("https://example.org/", "مثال", "تشريع",
                            http_get=blocked, dns_lookup=lambda h: ("ok", []))
    assert row["robots"] == "present"
    assert row["robots_allowed"] is False


def test_tls_broken_flagged():
    def insecure(url):
        return 200, "<html><title>رئاسة الوزراء</title></html>", True

    row = sm.measure_source("https://pministry.gov.sy/", "رئاسة الوزراء", "تشريع",
                            http_get=insecure,
                            dns_lookup=lambda h: ("ok", ["185.216.133.17"]))
    assert row["tls_broken"] is True
    assert row["alive"] is True
    assert row["tier"] == 1


# ─────────────────────── العرض ───────────────────────

def test_render_markdown_contains_rows():
    row = sm.measure_source("https://moj.gov.sy/", "وزارة العدل", "تشريع",
                            http_get=_wp_site, dns_lookup=lambda h: ("ok", []))
    md = sm.render_markdown([row], "2026-09-16")
    assert "مصفوفة المصادر" in md
    assert "وزارة العدل" in md
    assert "|---|" in md
    assert "قِيست 1 مصدراً" in md


# ─────────────────────── ترميز عربي سليم (ف١) ───────────────────────

def test_fix_encoding_overrides_latin1_default():
    class _Resp:
        encoding = "ISO-8859-1"
        apparent_encoding = "windows-1256"
    r = sm._fix_encoding(_Resp())
    assert r.encoding == "windows-1256"


def test_fix_encoding_keeps_explicit_charset():
    class _Resp:
        encoding = "utf-8"
        apparent_encoding = "windows-1256"
    r = sm._fix_encoding(_Resp())
    assert r.encoding == "utf-8"
