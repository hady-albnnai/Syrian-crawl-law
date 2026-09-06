# -*- coding: utf-8 -*-
"""run_state.py — حالة تشغيل تُقرأ فعلياً عند بدء دورة زحف حقيقية
(نفس crawler.start_crawling المستخدم بالـCLI، لا queue بديل).

ملاحظة تصحيح (2026-09-06): كانت هذه الحالة تحمل mode بثلاث قيم
(dry/limited/full) توحي للمستخدم بثلاثة سلوكيات مختلفة — بينما الزاحف
الحقيقي (crawler.start_crawling) لا يميّز فعلياً إلا بين قيمة واحدة
منطقية: dry_run (بلا حفظ) أو حفظ فعلي. "محدود" و"كامل" كانا نفس
السلوك تماماً بفارق تسمية فقط — عنصر واجهة وهمي أُزيل لصدق العرض.
"""
from dataclasses import dataclass


@dataclass
class RunSettings:
    max_pages: int = 25   # يُمرَّر فعلياً كـ max_pages لـ crawler.start_crawling
    dry_run: bool = True  # يُمرَّر فعلياً كـ dry_run — الفرق الحقيقي الوحيد بالسلوك


SETTINGS = RunSettings()
