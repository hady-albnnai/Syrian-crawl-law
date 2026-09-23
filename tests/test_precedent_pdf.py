# -*- coding: utf-8 -*-
"""اختبارات محرك الاجتهادات من ملفات PDF المحلية (ف٥).

منهجية: منطق التحليل/البوابة/الكتابة/الاستئناف يُختبر بحقن مستخرج النص
(لا نتكل على توليد عربية سليمة صناعياً في بيئة الاختبار)، والتطبيع يُختبر
كدالة نقية على أشكال عرض حقيقية، ومسار القراءة الفعلي يُختبر بملف PDF حقيقي.
"""
import pymupdf as fitz

import precedent_pdf as pp
from database import create_tables, get_connection

SY = ("إن الإكراه لا يجعل العقود المبرمة تحت سلطانه باطلة بطلاناً مطلقاً.\n"
      "(نقض مدني سوري 247 أساس 481 تاريخ 27/3/1961)\n"
      "الاكراه المعطل للرضا لا يتحقق إلا بالتهديد الذي يكون من نتيجته خوف شديد.\n"
      "(نقض رقم 3182 اساس 10376 تاريخ 4/11/1991 سجلات النقض)\n"
      "يتوجب اعادة ما ليس مستحقاً إذا دفع تحت الاكراه ولمحكمة الموضوع السلطة التامة.\n"
      "(قرار نقض رقم 575 أساس 3323 تاريخ 4 / 6 / 1978)")


# --- التطبيع: دالة نقية على أشكال عرض حقيقية -----------------------------
def test_normalize_presentation_forms_to_standard():
    # أشكال عرض كما تخرجها بعض ملفات الـPDF الفعلية: «نقض مدني سوري»
    pres = ("\uFEE7\uFED8\uFEBE"        # نقض: ن ابتدائية، ق متوسطة، ض نهائية
            " \uFEE3\uFEAA\uFEE7\uFEF2"  # مدني
            " \uFEB3\uFEEE\uFEAD\uFEF2")  # سوري
    out = pp.normalize_text(pres)
    assert out == "نقض مدني سوري"
    # ودمج أسطر والتحكم بالفواصل
    assert pp.normalize_text("أ  ب\n\n\n\nج") == "أ ب\n\nج"


# --- منطق الحصاد: حقن المستخرج -------------------------------------------
def _db(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    return get_connection()


def test_harvest_writes_pending_and_resumes(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    st = pp.harvest_pdf(conn, "أطروحة.pdf",
                        source_url="https://repository.damascusuniversity.edu.sy/x",
                        extractor=lambda p: SY)
    assert st["citations"] == 3 and st["written"] == 3 and st["pages_written"] == 1
    st2 = pp.harvest_pdf(conn, "أطروحة.pdf",
                         source_url="https://repository.damascusuniversity.edu.sy/x",
                         extractor=lambda p: SY)
    assert st2["seen"] == 1 and st2["written"] == 0
    conn.close()


def test_harvest_dry_run(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    st = pp.harvest_pdf(conn, "أطروحة.pdf", dry_run=True, extractor=lambda p: SY)
    assert st["citations"] == 3 and st["written"] == 0
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
    conn.close()


def test_harvest_low_quality_skipped(tmp_path, monkeypatch):
    conn = _db(tmp_path, monkeypatch)
    weak = "مقدمة عامة عن القانون.\nالفصل الأول: تعريف الزواج وأركانه."
    st = pp.harvest_pdf(conn, "ضعيف.pdf", extractor=lambda p: weak)
    assert st["skipped_low"] == 1 and st["written"] == 0
    conn.close()


# --- مسار القراءة الفعلي عبر pymupdf --------------------------------------
def test_extract_reads_real_pdf(tmp_path):
    pdf = tmp_path / "real.pdf"
    doc = fitz.open()
    for i in range(2):
        p = doc.new_page()
        p.insert_text((72, 100), f"page marker {i} (123/456)", fontsize=12)
    doc.save(str(pdf)); doc.close()
    out = pp.extract_pdf_text(str(pdf))
    assert "page marker 0 (123/456)" in out and "page marker 1 (123/456)" in out


# --- إصلاح طبقة نص الـPDF: دوال نقية على أنماط موثقة من ملفات فعلية -------
def test_repair_strips_font_junk_between_arabic_letters():
    # دخائل خريطة الخط من ملف «البيوع العقارية» الفعلي على Drive
    assert pp.repair_pdf_text("محكمة النق¦ض") == "محكمة النقض"
    assert pp.repair_pdf_text("القضية:*أساس") == "القضية:أساس"
    assert pp.repair_pdf_text("مDDان") == "مان"
    assert "أساس" in pp.repair_pdf_text("أ6سا6س")
    # محرف الاستبدال داخل الكلمة (نمط «المبد؟أ»)
    assert pp.repair_pdf_text("بيّ\ufffdنات") == "بيّنات"


def test_repair_preserves_free_numbers():
    # الأرقام المستقلة وسلاسلها لا تُمس — الهوية خط أحمر
    assert pp.repair_pdf_text("قرار 140 لعام 2016") == "قرار 140 لعام 2016"
    assert pp.repair_pdf_text("2016/9/20") == "2016/9/20"


def test_repair_glues_split_hamza_of_mabda():
    # «المبدأ» تخرج مفصولة الهمزة في الطبقات القديمة
    assert "المبدأ:" in pp.repair_pdf_text("المبد أ: بينات")
    assert "المبدأ:" in pp.repair_pdf_text("المبد\u060dأ: بينات")
    assert "المبدأ:" in pp.repair_pdf_text("المبد\ufffdأ: بينات")


def test_repair_flips_visual_order_lines_only():
    visual = "2016 لعام159 القضية:أساس"          # مخزنة بالترتيب البصري
    assert pp.repair_pdf_text(visual) == "القضية:أساس 159 لعام 2016"
    visual2 = "2016/9/20 تاريخ"
    assert pp.repair_pdf_text(visual2) == "تاريخ 2016/9/20"
    # السطر المنطقي السليم يُترك كما هو
    logical = "محكمة النقض قرار 140 أساس 159 تاريخ 20/9/2016"
    assert pp.repair_pdf_text(logical) == logical
    # سطر بلا قرائن بنيوية لا يُقلب
    plain = "إن التعامل بالكتابة المبرر لعدم الأخذ"
    assert pp.repair_pdf_text(plain) == plain


# --- الصيغة الموثقة كاملة: ملف «البيوع العقارية» (هيئة عامة، مرتبة ١) ------
BAY = ("القضية:أساس 159 لعام 2016 :قرار 140 لعام 2016 تاريخ 2016/9/20 "
       ".الهيئة العامة /مدني – محكمة النقض المبدأ: إن التعامل بالكتابة المبرر "
       "لعدم الأخذ بالمانع الأدبي في الإثبات بالشهادة يقتضي ثبوت أكثر من تعامل "
       "ورقي واحد، وتوثيق العقود العقارية في السجل العقاري يعد نقلاً للملكية.")


def test_repair_pipeline_full_haya_identity(tmp_path, monkeypatch):
    from precedent_parser import parse_text, authority_rank
    cs = [c for c in parse_text(pp.repair_pdf_text(BAY)) if c.is_exportable()]
    assert len(cs) == 1
    assert cs[0].court == "هيئة_عامة_نقض" and authority_rank(cs[0]) == 1
    assert cs[0].decision_number == "140" and cs[0].basis_number == "159"
    assert cs[0].decision_date == "2016-09-20"
