# -*- coding: utf-8 -*-
"""ف٦ — عيّنة المالك «بلا هوية» (unidentified.txt، 2026-09-19): 46 صكاً.

كل نص هنا حرفي من الملف المرفق. القاعدة المكرَّرة: المقتطفات المصطنعة تنجح
والنص الحقيقي يفشل — فلا اختبار إلا على النص الحقيقي.
"""
import pytest

from doc_nature import classify_nature
from law_identity import (extract_law_identity, title_only_identity,
                          triage_unidentified)


# --- الفئة ب: صيغ رقمية كانت غير مدعومة --------------------------------------
@pytest.mark.parametrize("title,key", [
    ("قانون قمع التهريب13 - 1974", "القانون:13:1974"),          # #108 رقم ملتصق + شرطة
    ("قانون النقد الأساسي 23-2002", "القانون:23:2002"),          # #165 شرطة بلا فراغ
])
def test_dash_format_gives_full_identity(title, key):
    assert extract_law_identity(title, "")["identity_key"] == key


def test_dash_format_does_not_steal_from_referenced_instrument():
    # الرقم بعد اسم صك آخر في الفجوة → ليس هويتنا
    t = "قانون العقوبات المعدل بالمرسوم 12-2001"
    assert extract_law_identity(t, "")["identity_key"] is None


@pytest.mark.parametrize("title,number,year", [
    ("قانون البينات 359 تاريخ 10", 359, None),                              # #140
    ("قانون الأحوال الشخصية الصادر بالمرسوم التشريعي رقم 59", 59, None),   # #147 صيغة إصدار
    ("نظام احتكار التبغ والتنباك الصادر بالقرار رقم 16 ل", 16, None),       # #103
    ("قانون التجارة رقم 33, الجمهورية العربية السورية", 33, None),          # #95
    ("المرسوم رقم (30)", 30, None),                                         # #119
])
def test_title_partial_number(title, number, year):
    fb = title_only_identity(title)
    assert (fb["law_number"], fb["law_year"]) == (number, year)


def test_regulation_does_not_take_parent_law_number():
    # #101: رقم /24/ للقانون الأم لا للتعليمات — النافذة الكاملة قبل الرقم
    t = "التعليمات التنفيذية لقانون الضريبة على الدخل رقم /24/ لعام 2003"
    fb = title_only_identity(t)
    assert fb["law_number"] is None
    assert extract_law_identity(t, "")["identity_key"] is None


def test_issued_by_exception_still_gives_full_identity():
    # ما كان يعمل يبقى: صيغة إصدار كاملة برقم وسنة
    t = "قانون التأمينات الاجتماعية الصادر بالمرسوم التشريعي رقم 92 لعام 1959"
    assert extract_law_identity(t, "")["identity_key"] == "المرسوم التشريعي:92:1959"


def test_reference_in_title_still_rejected():
    # حارس ف١ لا يُكسر بتوسيع النافذة
    t = "قانون العقوبات المعدل بالمرسوم رقم 12 لعام 2001"
    assert title_only_identity(t)["law_number"] is None


# --- الفئة أ: ليست صكوكاً — تخرج بتصنيف الطبيعة -------------------------------
@pytest.mark.parametrize("title,head,nature", [
    ("استشارات قانونية مجانية",
     "تصنيف : مكتبة القوانين السورية – قوانين سوريا (الصفحة 1 من 108) رقم مكافحة الابتزاز",
     "index_page"),                                                          # #61
    ("استشارات قانونية مجانية",
     "وسم : العقوبات (الصفحة 1 من 38) قانون العقوبات الاماراتي يجرم", "index_page"),  # #63
    ("توتر كبير بين نقابة المحامين الفلسطيين ومجلس القضاء الاعلى بسبب تفتيش المحامي",
     "", "non_legal"),                                                       # #73
    ("ﺍﻟﺠﺮﻳﻤﺔ ﺍﻟﻤﻌﻠﻮﻣﺎﺗﻴﺔ .ﺭﺳﺎﻟﺔ ﻣﺎﺟﺴﺘﻴﺮ ﻟﻠﻂﺎﻟﺐ براء ﺍﻟﺤﺮﻳﺮﻱ.", "", "non_legal"),  # #79
    ("نظام بودابست - النظام الدولي لإيداع الكائنات الدقيقة", "", "non_legal"),  # #84
    ("مشروع قانون الاحوال الشخصية السوري", "", "draft"),                     # #81
])
def test_non_instruments_leave_the_unidentified_pool(title, head, nature):
    assert classify_nature(title, head)["nature"] == nature


# --- الفرز --------------------------------------------------------------------
@pytest.mark.parametrize("title,head,cat", [
    ("المرسوم التشريعي رقم 6: قانون مكافحة الإتجار بالبشر- 2010",
     "المرسوم التشريعي رقم (3) رئيس الجمهورية بناء على أحكام الدستور يرسم ما يلي",
     "title_preamble_clash"),                                                # #19
    ("نصوص و مواد قانون العقوبات السوري", "", "likely_duplicate"),           # #50
    ("المادة 1 ـ أصول تسليم المجرمين العاديين والملاحقين قضائيا", "", "likely_duplicate"),  # #148
    ("اللائحة التنفيذية لقانون السجل العقاري", "", "regulation"),            # #137
    ("التعليمات التوضيحية والتنفيذية لقانون تنظيم التواصل على الشبكة", "", "regulation"),  # #89
    ("وثيقة قانونية سورية", "", "fragment"),                                 # #158
    ("بالترخيص لمصارف سورية خاصة أو مشتركة وفق النص المرفق .", "", "fragment"),  # #163
    ("قانون التجارة رقم 33, الجمهورية العربية السورية", "", "partial_number_year"),  # #95
    ("قانون حماية حقوق المؤلف في سورية 2001", "", "partial_number_year"),   # #42
    ("قانون مجلس الدولة", "", "named_law"),                                  # #151
    ("قانون العقوبات الاقتصادية في سورية", "المادة 1 أ- يقصد بالدولة", "named_law"),  # #11
])
def test_triage_categories(title, head, cat):
    assert triage_unidentified(title, head)["category"] == cat


def test_triage_never_writes_identity():
    tri = triage_unidentified("قانون التجارة رقم 33, الجمهورية العربية السورية", "")
    assert "identity_key" not in tri
