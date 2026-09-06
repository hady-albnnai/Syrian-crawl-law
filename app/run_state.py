# -*- coding: utf-8 -*-
"""run_state.py — حالة تشغيل مشتركة بين شاشتي «تحديد النطاق» و«التشغيل».

قبل هذا الملف، شاشة النطاق كانت معزولة تماماً: تختار المستخدم صفحات/وضع/
مصدراً وزراً «بدء الزحف» لا يفعل شيئاً — كل الحقول عرض بلا تأثير. الآن
تُخزَّن الاختيارات هنا وتُقرأ فعلياً عند بدء دورة زحف حقيقية من شاشة
التشغيل (لا queue بديل، نفس crawler.start_crawling المستخدم بالـCLI).
"""
from dataclasses import dataclass


@dataclass
class RunSettings:
    max_pages: int = 25
    mode: str = "dry"   # dry | limited | full — يحدد dry_run فعلياً بالزاحف


SETTINGS = RunSettings()
