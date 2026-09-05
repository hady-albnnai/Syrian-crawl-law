# -*- coding: utf-8 -*-
"""
test_extraction.py
ملف اختبار: يجلب صفحة ويستخرج منها النص القانوني
"""

from fetcher import fetch
from extractor import extract_main_content, is_legal_content
from database import insert_log
import json

def test_extraction():
    print("=" * 70)
    print("بدء اختبار استخراج النصوص القانونية")
    print("=" * 70)
    
    # رابط موضوع قانوني حقيقي من الموقع (اخترناه من recon.py)
    test_url = "https://law-library.syriaforums.net/t2035-%D8%A7%D8%B3%D8%A8%D9%88%D8%B9-%D9%81%D8%B9%D8%A7%D9%84%D9%8A%D8%A7%D8%AA-%D8%A7%D9%84%D8%AA%D8%B9%D8%B1%D9%8A%D9%81-%D8%A8%D8%A7%D9%84%D9%82%D8%A7%D9%86%D9%88%D9%86-%D8%A7%D9%84%D9%85%D8%AF%D9%86%D9%8A"
    
    print(f"جاري جلب الصفحة:\n{test_url}\n")
    
    # 1. جلب الصفحة
    result = fetch(test_url)
    
    if not result["ok"]:
        print("❌ فشل في جلب الصفحة")
        return
    
    print(f"✅ تم جلب الصفحة بنجاح ({result['ms']} مللي ثانية)\n")
    
    # 2. استخراج النص
    extraction = extract_main_content(result["html"], test_url)
    
    if not extraction["success"]:
        print("❌ فشل في استخراج المحتوى")
        print(f"السبب: {extraction['error']}")
        return
    
    clean_text = extraction["clean_text"]
    
    print(f"✅ تم استخراج النص بنجاح!")
    print(f"   الـ Selector المستخدم: {extraction['used_selector']}")
    print(f"   طول النص: {extraction['text_length']} حرف\n")
    
    print("-" * 50)
    print("أول 300 حرف من النص المستخرج:")
    print("-" * 50)
    print(clean_text[:300] + "...")
    print("-" * 50)
    
    # 3. فحص إذا كان النص قانوني
    is_legal = is_legal_content(clean_text)
    print(f"\nهل يبدو النص قانونياً؟ {'✅ نعم' if is_legal else '❌ لا'}")
    
    # 4. حفظ النتيجة في ملف للمراجعة
    output = {
        "url": test_url,
        "used_selector": extraction["used_selector"],
        "text_length": extraction["text_length"],
        "is_legal": is_legal,
        "first_500_chars": clean_text[:500]
    }
    
    with open("test_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ تم حفظ النتيجة في ملف: test_output.json")
    print("\nهل تريد أن نستمر في بناء الملف الرئيسي (crawler.py)؟")


if __name__ == "__main__":
    test_extraction()