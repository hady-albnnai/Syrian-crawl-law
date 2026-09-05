# -*- coding: utf-8 -*-
"""
crawler.py — النسخة المحسنة v2.1
تحسينات: فلترة أفضل + استخراج روابط المواضيع + logging أوضح
"""

import time
import re
import hashlib
from datetime import datetime
from urllib.parse import urljoin

from config import BASE_URL, MIN_LEGAL_SCORE, MIN_TEXT_LENGTH
from fetcher import fetch
from extractor import extract_main_content, is_legal_content, detect_branch
from database import get_connection, insert_log


def clean_url(url: str) -> str:
    return url.split('#')[0].split('?')[0].strip()


def get_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode('utf-8')).hexdigest()


def extract_topic_links(html: str, base_url: str) -> list:
    """استخراج روابط المواضيع من صفحات الأقسام"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if re.search(r"/t\d+", href):           # روابط المواضيع
            full_url = urljoin(base_url, href)
            cleaned = clean_url(full_url)
            if cleaned not in links:
                links.append(cleaned)
    return links[:30]   # حد أعلى معقول


def start_crawling(max_pages=40):
    print("=" * 110)
    print("🚀 الزاحف المتكامل v2.1 — استخراج المواد + حفظ في قاعدة البيانات")
    print("=" * 110)
    print(f"الحد الأقصى: {max_pages} صفحة | التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 110)

    pages_crawled = 0
    documents_saved = 0
    articles_saved = 0
    visited = set()
    seen_hashes = set()

    important_forums = [
        (f"{BASE_URL}f3-montada", "القانون المدني"),
        (f"{BASE_URL}f9-montada", "القانون الجزائي"),
        (f"{BASE_URL}f15-montada", "أصول المحاكمات"),
        (f"{BASE_URL}f24-montada", "الأحوال الشخصية"),
        (f"{BASE_URL}f14-montada", "القانون التجاري"),
        (f"{BASE_URL}f4-montada", "الدساتير والقانون الدستوري"),
    ]

    queue = important_forums.copy()

    while queue and pages_crawled < max_pages:
        raw_url, section = queue.pop(0)
        url = clean_url(raw_url)
        
        if url in visited:
            continue
        visited.add(url)
        pages_crawled += 1

        print(f"\n[{pages_crawled}/{max_pages}] 📂 {section}")
        print(f"   🔗 {url}")

        result = fetch(url)
        if not result.get("ok", False):
            print("   ❌ فشل الجلب")
            continue

        # تجاهل صفحات الأقسام الكبيرة ومعالجتها فقط لاستخراج الروابط
        if "/f" in url and "/t" not in url:
            topic_links = extract_topic_links(result["html"], BASE_URL)
            print(f"   📌 تم العثور على {len(topic_links)} موضوع جديد")
            for link in topic_links:
                if link not in visited:
                    queue.append((link, section))
            continue

        # معالجة صفحات المواضيع فقط
        ext = extract_main_content(result["html"], url)
        
        if not ext["success"]:
            print(f"   ⚠️ فشل الاستخراج: {ext.get('error', 'unknown')}")
            continue

        title = ext["title"]
        clean_text = ext["clean_text"]
        articles = ext.get("articles", [])
        content_hash = get_hash(clean_text)

        if content_hash in seen_hashes:
            print("   🔁 مكرر — تخطي")
            continue
        seen_hashes.add(content_hash)

        if not is_legal_content(clean_text, title):
            print("   ⚠️ لم يجتز الفحص القانوني")
            continue

        branch, confidence = detect_branch(clean_text, section)

        conn = get_connection()
        cursor = conn.cursor()

        # حفظ الوثيقة
        cursor.execute('''
            INSERT OR IGNORE INTO documents 
            (doc_id, title, source_url, branch, branch_confidence, legal_score, 
             content_hash, scraped_at, clean_content, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            f"doc_{int(time.time())}",
            title,
            url,
            branch,
            float(confidence),
            85.0,
            content_hash,
            datetime.now().isoformat(),
            clean_text[:15000],
            "law"
        ))
        
        doc_row_id = cursor.lastrowid
        conn.commit()

        # حفظ المواد
        for art in articles:
            cursor.execute('''
                INSERT INTO articles (doc_id, article_number, article_label, 
                                    text, paragraphs_json, char_count)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                doc_row_id,
                str(art["article_number"]),
                art["label"],
                art["text"],
                "[]",                    # يمكن تطويره لاحقاً
                art["char_count"]
            ))
            articles_saved += 1

        conn.commit()
        conn.close()

        documents_saved += 1
        print(f"   ✅ تم الحفظ بنجاح! ({len(articles)} مادة)")
        print(f"      العنوان : {title[:75]}...")
        print(f"      الفرع   : {branch} (ثقة {confidence})")

        # استخراج روابط إضافية
        if "/t" not in url.lower():
            topic_links = extract_topic_links(result["html"], BASE_URL)
            print(f"   📌 {len(topic_links)} موضوع جديد تم إضافته للطابور")
            for link in topic_links:
                if link not in visited:
                    queue.append((link, section))

        time.sleep(1.6)

    print("\n" + "="*110)
    print("🏁 انتهى الزحف بنجاح")
    print(f"الصفحات المزحوفة : {pages_crawled}")
    print(f"الوثائق المحفوظة : {documents_saved}")
    print(f"إجمالي المواد     : {articles_saved}")
    print("="*110)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM documents")
    docs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM articles")
    arts = cursor.fetchone()["c"]
    print(f"📊 الحالة النهائية في قاعدة البيانات: {docs} وثيقة | {arts} مادة")
    conn.close()


if __name__ == "__main__":
    start_crawling(max_pages=50)