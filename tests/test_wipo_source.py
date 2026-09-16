# -*- coding: utf-8 -*-
"""اختبارات wipo_source — مصدر ويبو ليكس (ف١-ب). محلية بالكامل بلا شبكة:
الـPDF وصفحة التفاصيل محفوظة كطقم ذهبي (tests/fixtures/wipo/)."""
import re

import pytest

pymupdf = pytest.importorskip("pymupdf")  # المكتبة اختيارية للتشغيل لا للاختبار

import wipo_source as ws
from extractor_v4 import extract_main_content
from law_identity import extract_law_identity

FIX = "tests/fixtures/wipo"
DETAILS_URL = "https://www.wipo.int/wipolex/ar/legislation/details/10918"


def _details_html():
    return open(f"{FIX}/penal_details_ar.html", encoding="utf-8").read()


def _pdf_bytes():
    return open(f"{FIX}/penal_code_148_1949.pdf", "rb").read()


def _pipeline_result():
    return ws.as_pipeline_result(
        DETAILS_URL, _details_html(),
        get_bytes=lambda u, referer=None: (200, _pdf_bytes()))


# ─────────────────────── التعرف والعنوان والرابط ───────────────────────

def test_is_wipo_details():
    assert ws.is_wipo_details(DETAILS_URL)
    assert ws.is_wipo_details("https://www.wipo.int/wipolex/en/legislation/details/20741")
    assert not ws.is_wipo_details("https://moj.gov.sy/decision/x/")
    assert not ws.is_wipo_details("")


def test_extract_title_arabic_with_citation():
    t = ws.extract_title(_details_html())
    assert "المرسوم التشريعي رقم 148/1949" in t
    assert "WIPO Lex" not in t


def test_extract_signed_pdf_url():
    url = ws.extract_signed_pdf_url(_details_html())
    assert url.startswith("https://wipolex-res.wipo.int/edocs/lexdocs/laws/ar/")
    assert ".pdf" in url


# ─────────────────────── تنظيف الـPDF (أثر مقيس) ───────────────────────

def test_clean_joins_article_number_and_drops_page_number():
    t = ws.clean_pdf_text("المادة \n1 1\n نص المادة الأولى هنا بما يكي.", "ع")
    assert "المادة 1" in t
    assert "\n1\n" not in t  # رقم الصفحة لم يبق سطراً


def test_clean_reverses_visual_digit_runs():
    # قياس فعلي: المواد 166-170 تظهر خاماً 661/761/861/961/071
    t = ws.clean_pdf_text("المادة \n661\n نص كافٍ للمادة هنا بمحتوى قانوني.", "ع")
    assert "المادة 166" in t


def test_clean_drops_decorative_rule_lines():
    t = ws.clean_pdf_text("نص قبل الفاصل\n----------\nنص بعد الفاصل", "ع")
    assert "----------" not in t
    assert "نص قبل الفاصل" in t and "نص بعد الفاصل" in t


def test_clean_drops_repeated_page_header():
    title = "القانون الجنائي (الصادر بالمرسوم التشريعي رقم 148/1949), الجمهورية العربية السورية"
    t = ws.clean_pdf_text("المادة 1 نص\n" + title + "\nالمادة 2 نص", title)
    assert t.count("القانون الجنائي") == 0


def test_to_pipeline_html_each_line_its_own_element():
    h = ws.to_pipeline_html("عنوان", "سطر أول\nسطر ثانٍ")
    assert "<p>سطر أول</p>" in h and "<p>سطر ثانٍ</p>" in h


def test_to_pipeline_html_hierarchy_heading():
    h = ws.to_pipeline_html("عنوان", "الباب الأول في العقوبات")
    assert "<h3>الباب الأول في العقوبات</h3>" in h


# ─────────────────────── المسار كاملاً (الطقم الذهبي) ───────────────────────

def test_golden_pipeline_articles_and_quality():
    """الطقم الذهبي لقانون العقوبات: 775 مادة عبر الأنبوب كاملاً عند
    التثبيت — أي تراجع كبير (أنماط الضجيج، دمج الأسطر، انعكاس الأرقام)
    يُمسك هنا فوراً."""
    result = _pipeline_result()
    assert result["ok"] is True
    ext = extract_main_content(result["html"], DETAILS_URL)
    assert ext["success"] is True
    real = [a for a in ext["articles"] if not a.get("is_preamble")]
    assert len(real) >= 700
    assert ext["quality_score"] >= 0.8
    nums = {a["article_number"] for a in real if a.get("article_number")}
    assert {166, 170, 305} <= nums          # أرقام كانت معكوسة بصرياً
    assert 1 in nums and max(nums) >= 540   # قانون شبه كامل


def test_golden_identity_slash_year():
    result = _pipeline_result()
    ext = extract_main_content(result["html"], DETAILS_URL)
    ident = extract_law_identity(ext["title"], ext["clean_text"][:500])
    assert ident["identity_key"] == "المرسوم التشريعي:148:1949"


def test_golden_hierarchy_paths_present():
    result = _pipeline_result()
    ext = extract_main_content(result["html"], DETAILS_URL)
    real = [a for a in ext["articles"] if not a.get("is_preamble")]
    assert sum(1 for a in real if a.get("hierarchy_path")) >= 400


# ─────────────────────── إخفاقات صريحة ───────────────────────

def test_no_pdf_link_fails_cleanly():
    r = ws.as_pipeline_result(DETAILS_URL, "<html><title>بلا ملف</title></html>",
                              get_bytes=lambda u, referer=None: (200, b""))
    assert r["ok"] is False and r["error"] == "wipo_no_pdf"


def test_html_shell_instead_of_pdf_fails():
    r = ws.as_pipeline_result(
        DETAILS_URL, _details_html(),
        get_bytes=lambda u, referer=None: (200, b"<!DOCTYPE html>..."))
    assert r["ok"] is False and r["error"].startswith("wipo_pdf_fetch_")


def test_robots_blocked_fails():
    r = ws.as_pipeline_result(
        DETAILS_URL, _details_html(),
        get_bytes=lambda u, referer=None: (None, b""))
    assert r["ok"] is False and r["error"] == "wipo_blocked_robots"


# ─────────────────────── تكاملي: حفظ عبر دورة الزحف ───────────────────────

def test_wipo_doc_saved_with_tier_and_chain(tmp_path, monkeypatch):
    import crawler
    import database
    monkeypatch.setattr(database, "DB_PATH",
                        str(tmp_path / "wipo_it.db"))
    database.create_tables()
    conn = database.get_connection()

    result = _pipeline_result()
    task = {"id": 1, "url": DETAILS_URL,
            "section": "قانون العقوبات (ويبو ليكس)"}
    conn.execute(
        "INSERT INTO crawl_tasks (id, url, section, kind, status) "
        "VALUES (1, ?, ?, 'topic', 'in_progress')",
        (DETAILS_URL, task["section"]))
    stats = {"pages": 0, "docs": 0, "articles": 0, "skipped": 0, "failures": 0}
    crawler._handle_topic(conn, task, result["html"], dry_run=False,
                          stats=stats)
    assert stats["docs"] == 1 and stats["articles"] >= 700

    doc = conn.execute(
        "SELECT identity_key, source_domain_tier, source_url "
        "FROM documents").fetchone()
    assert doc["identity_key"] == "المرسوم التشريعي:148:1949"
    assert doc["source_domain_tier"] == 2        # إيداع ويبو = تير 2
    assert doc["source_url"] == DETAILS_URL

    # مستهدَف سلسلة: وثيقة معدِّلة تشير للعقوبات → حالته معدَّل
    conn.execute(
        "INSERT INTO documents (doc_id, title, source_url, clean_content, "
        "identity_key, doc_type, number, year) VALUES (?,?,?,?,?,?,?,?)",
        ("amender", "القانون رقم 3 لعام 2010",
         "https://test/amender",
         "المادة 1- تعدل المواد 12 و45 من المرسوم التشريعي رقم 148/1949.",
         "القانون:3:2010", "law", 3, 2010))
    conn.commit()
    import law_status
    law_status.rebuild_links(conn)
    law_status.compute_legal_statuses(conn)
    status = conn.execute(
        "SELECT legal_status FROM documents "
        "WHERE identity_key='المرسوم التشريعي:148:1949'").fetchone()
    assert status["legal_status"] == "معدَّل"
    chain = law_status.law_chain(conn, "المرسوم التشريعي:148:1949")
    assert any(r["action"] == "amend" for r in chain)


def test_signed_url_fully_unescaped():
    """اکتُشف بالزحف الحي: كيان «&#x3D;» الباقي يكسر توقيع CloudFront
    (403). الرابط المستخرج يجب أن يكون جاهزاً كما هو."""
    url = ws.extract_signed_pdf_url(_details_html())
    assert "&#x3D;" not in url and "&amp;" not in url and "&quot;" not in url
    assert "last-modified=" in url and "Signature=" in url
