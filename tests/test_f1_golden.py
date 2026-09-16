# -*- coding: utf-8 -*-
"""الطقم الذهبي لف١ — وثائق حقيقية محفوظة كـfixtures، تُقاس عليها كل
تغييرات المستخرج والهوية (لا انحدار صامت بعد اليوم).

المصادر (جُلبت 2026-09-16):
- tests/fixtures/tss/labor_law_17_2010.html — قانون العمل 17/2010 بنص
  كامل من tss-est.net: 88 مادة بجودة 0.95 ومسار هرمي حقيقي.
- tests/fixtures/moj/*.html — ثلاث صفحات حقيقية من moj.gov.sy (قراران
  وتعميم): المصدر الرسمي الأول بف١.
"""
from pathlib import Path

from extractor_v4 import extract_main_content
from law_identity import extract_law_identity

FIXTURES = Path(__file__).parent / "fixtures"
TSS_LAW = FIXTURES / "tss" / "labor_law_17_2010.html"
MOJ_DECISION = FIXTURES / "moj" / "decision_349_2026.html"
MOJ_CIRCULAR = FIXTURES / "moj" / "circular_3_2026.html"


# ───────────────────────── قانون كامل (الطقم الذهبي) ─────────────────────────

def test_labor_law_full_extraction():
    html = TSS_LAW.read_text(encoding="utf-8")
    r = extract_main_content(html, "https://tss-est.net/worker/Laws/20/43/Ar")
    assert r["success"] is True
    real = [a for a in r["articles"] if not a.get("is_preamble")]
    assert len(real) >= 80            # 88 مادة عند التثبيت
    assert r["quality_score"] >= 0.9  # 0.95 عند التثبيت
    # المسار الهرمي (كتاب/باب/فصل/مبحث) موجود فعلياً بالمواد
    assert any(a.get("hierarchy_path") for a in real)


def test_labor_law_identity_after_articleless_fix():
    """الاختبار الذي كشف خطأ أل التعريف: هذا العنوان كان يفقد هويته
    كاملة قبل ف١ — الآن مفتاحه مستقر."""
    html = TSS_LAW.read_text(encoding="utf-8")
    r = extract_main_content(html, "https://tss-est.net/worker/Laws/20/43/Ar")
    ident = extract_law_identity(r["title"], r["clean_text"])
    assert ident["identity_key"] == "القانون:17:2010"
    assert ident["identity_confidence"] == "number_year"


# ───────────────────────── صفحات moj الرسمية ─────────────────────────

def test_moj_decision_title_and_identity():
    html = MOJ_DECISION.read_text(encoding="utf-8")
    r = extract_main_content(html, "https://moj.gov.sy/decision/x/")
    assert r["success"] is True
    assert "قرار وزارة العدل" in r["title"]
    ident = extract_law_identity(r["title"], r["clean_text"])
    assert ident["identity_key"] == "القرار:349:2026"


def test_moj_circular_title_and_identity():
    html = MOJ_CIRCULAR.read_text(encoding="utf-8")
    r = extract_main_content(html, "https://moj.gov.sy/circular/x/")
    assert r["success"] is True
    ident = extract_law_identity(r["title"], r["clean_text"])
    assert ident["identity_key"] == "التعميم:3:2026"
