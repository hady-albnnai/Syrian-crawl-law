"""B-2: مصدر بنود — صفحة حقيقية (م.ت/القانون 115/1953 خدمة العلم، 2026-09-19)."""
from pathlib import Path

import bunud_source as b
from extractor_v4 import extract_main_content
from law_identity import extract_law_identity

FIX = Path(__file__).parent / "fixtures" / "bunud_law_115_1953.html"


def test_url_recognition():
    assert b.is_bunud_law("https://www.bunud.ai/sy/laws/military-service-law-2")
    assert not b.is_bunud_law("https://www.bunud.ai/sy/laws/categories/civil_laws")
    assert not b.is_bunud_law("https://www.bunud.ai/sy/laws")


def test_parse_real_page():
    p = b.parse_law_page(FIX.read_text(encoding="utf-8"))
    assert p["title"] == "المرسوم التشريعي 115 لعام 1953 المتضمن قانون خدمة العلم"
    assert (p["doc_type"], p["number"], p["year"]) == ("المرسوم التشريعي", 115, 1953)  # النص: «هذا المرسوم التشريعي»
    assert p["source_status"] == "ملغى"
    assert len(p["articles"]) == 93
    assert p["articles"][0] == ("المادة 1", "يطلق على هذا المرسوم التشريعي اسم (قانون خدمة العلم).")
    assert p["articles"][-1][0] == "المادة 93"
    assert b.identity_of(p) == "المرسوم التشريعي:115:1953"


def test_pipeline_html_goes_through_standard_extractor():
    r = b.as_pipeline_result("https://www.bunud.ai/sy/laws/military-service-law-2",
                             FIX.read_text(encoding="utf-8"))
    assert r["ok"] and r["source_status"] == "ملغى"
    e = extract_main_content(r["html"], r["final_url"])
    assert e["success"] and len(e["articles"]) == 93
    ident = extract_law_identity(e["title"], e["clean_text"])
    assert ident["identity_key"] == "المرسوم التشريعي:115:1953"


def test_non_law_page_rejected():
    assert b.as_pipeline_result("https://www.bunud.ai/sy/laws/x", "<html><h1>x</h1></html>")["ok"] is False


def test_sitemap_walk():
    idx = "<urlset><loc>https://www.bunud.ai/sitemaps/static/1</loc><loc>https://www.bunud.ai/sitemaps/laws/sy/1</loc></urlset>"
    sub = "<loc>https://www.bunud.ai/sy/laws/customs-law</loc><loc>https://www.bunud.ai/sy/laws/categories/x</loc>"
    got = b.sitemap_law_urls(idx, lambda u: sub if u.endswith("/laws/sy/1") else "")
    assert got == ["https://www.bunud.ai/sy/laws/customs-law"]


def test_article_rows_without_al_and_hierarchy_headings():
    # crawl_bunud 2026-09-19: «1 · مادة 1» بلا أل + عناوين الباب/الفصل بين المواد → كانت تُرفض
    h = (Path(__file__).parent / "fixtures" / "bunud_accounting_system.html").read_text(encoding="utf-8")
    p = b.parse_law_page(h)
    assert (p["doc_type"], p["number"], p["year"]) == ("المرسوم التشريعي", 488, 2007)
    real = [a for a in p["articles"] if a[0].startswith("المادة")]
    assert len(real) == 50 and real[0][0] == "المادة 1"
    e = extract_main_content(b.as_pipeline_result("u", h)["html"], "u")
    assert len(e["articles"]) == 50
    assert any(a.get("hierarchy_path") for a in e["articles"])
