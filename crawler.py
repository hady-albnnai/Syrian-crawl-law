# -*- coding: utf-8 -*-
"""
crawler.py — النسخة المحسنة v2.2
دفعة P0: معرّف وثيقة مستقر (sha256 للرابط المطبَّع) + حفظ idempotent
يمنع التكرار عند إعادة التشغيل + درجة قانونية محسوبة
"""

import time
import re
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

from config import BASE_URL, MIN_LEGAL_SCORE, MIN_TEXT_LENGTH
from fetcher import fetch
from extractor import extract_main_content, is_legal_content, detect_branch, legal_score
from database import get_connection, insert_log
from logging_setup import get_log
log = get_log("crawl")


def clean_url(url: str) -> str:
    return url.split('#')[0].split('?')[0].strip()


def canonicalize_url(url: str) -> str:
    """تطبيع الرابط: إزالة fragment/query، توحيد حالة المضيف، وشطب / الختامية.

    أساس هوية الوثيقة المستقرة (ROADMAP §4.2، عقد §6.1).
    """
    u = urlparse(clean_url(url))
    netloc = u.netloc.lower()
    path = u.path.rstrip('/') or '/'
    return urlunparse((u.scheme.lower(), netloc, path, '', '', ''))


def make_doc_id(url: str) -> str:
    """معرّف وثيقة مستقر مشتق من الرابط المطبَّع — لا من وقت التشغيل.

    دفعة P0 (2026-09-05): استبدلت الصيغة الزمنية المعيبة
    f"doc_{int(time.time())}" التي كانت تولّد هوية جديدة لكل إعادة زحف،
    فتكسر idempotency وتُنشئ مواد مكررة أو يتيمة.
    """
    normalized = canonicalize_url(url)
    return "sha256:" + hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def save_document(cursor, doc_id: str, title: str, url: str, branch: str,
                  confidence: float, score: float, content_hash: str,
                  clean_text: str):
    """يحفظ وثيقة إن لم تكن موجودة مسبقاً. يعيد (row_id, created).

    الحفظ idempotent: الفحص بـ doc_id المستقر، فلا اعتماد على
    INSERT OR IGNORE + lastrowid (غير موثوق عند تجاهل الإدخال).
    """
    cursor.execute("SELECT id FROM documents WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    if row is not None:
        return row["id"], False
    cursor.execute('''
        INSERT INTO documents
        (doc_id, title, source_url, branch, branch_confidence, legal_score,
         content_hash, scraped_at, clean_content, doc_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        doc_id, title, url, branch, confidence, score,
        content_hash, datetime.now().isoformat(), clean_text, "law"
    ))
    return cursor.lastrowid, True


def get_hash(text: str) -> str:
    # ملاحظة: md5 تاريخي لمحتوى clean_content — الانتقال إلى sha256 قرار ترحيل
    # مؤجل إلى التسليم 4 حتى لا تنكسر مطابقة بصمات القواعد القائمة (ADR-001).
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


def start_crawling(max_pages=40, dry_run=False):
    log.info("=" * 110)
    log.info("🚀 الزاحف المتكامل v2.1 — استخراج المواد + حفظ في قاعدة البيانات")
    log.info("=" * 110)
    log.info(f"الحد الأقصى: {max_pages} صفحة | التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("-" * 110)

    pages_crawled = 0
    documents_saved = 0
    articles_saved = 0
    would_docs = 0
    would_arts = 0
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

        log.info(f"\n[{pages_crawled}/{max_pages}] 📂 {section}")
        log.info(f"   🔗 {url}")

        result = fetch(url)
        if not result.get("ok", False):
            log.info("   ❌ فشل الجلب")
            continue

        # تجاهل صفحات الأقسام الكبيرة ومعالجتها فقط لاستخراج الروابط
        if "/f" in url and "/t" not in url:
            topic_links = extract_topic_links(result["html"], BASE_URL)
            log.info(f"   📌 تم العثور على {len(topic_links)} موضوع جديد")
            for link in topic_links:
                if link not in visited:
                    queue.append((link, section))
            continue

        # معالجة صفحات المواضيع فقط
        ext = extract_main_content(result["html"], url)
        
        if not ext["success"]:
            log.info(f"   ⚠️ فشل الاستخراج: {ext.get('error', 'unknown')}")
            continue

        title = ext["title"]
        clean_text = ext["clean_text"]
        articles = ext.get("articles", [])
        content_hash = get_hash(clean_text)

        if content_hash in seen_hashes:
            log.info("   🔁 مكرر — تخطي")
            continue
        seen_hashes.add(content_hash)

        if not is_legal_content(clean_text, title):
            log.info("   ⚠️ لم يجتز الفحص القانوني")
            continue

        branch, confidence = detect_branch(clean_text, section)
        score = legal_score(clean_text, title)
        doc_id = make_doc_id(url)

        conn = get_connection()
        cursor = conn.cursor()

        if dry_run:
            conn.close()
            would_docs += 1
            would_arts += len(articles)
            log.info(f"   [dry-run] سيُحفظ: {title[:60]} ({len(articles)} مادة، جودة {score})")
            continue

        # حفظ الوثيقة (idempotent — منع التكرار عند إعادة التشغيل، بند P0)
        doc_row_id, created = save_document(
            cursor, doc_id, title, url, branch,
            float(confidence), score, content_hash, clean_text[:15000]
        )
        if not created:
            conn.close()
            log.info("   🔁 الوثيقة محفوظة في قاعدة البيانات سابقاً — تخطي بلا تكرار")
            continue
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
        log.info(f"   ✅ تم الحفظ بنجاح! ({len(articles)} مادة)")
        log.info(f"      العنوان : {title[:75]}...")
        log.info(f"      الفرع   : {branch} (ثقة {confidence})")

        # استخراج روابط إضافية
        if "/t" not in url.lower():
            topic_links = extract_topic_links(result["html"], BASE_URL)
            log.info(f"   📌 {len(topic_links)} موضوع جديد تم إضافته للطابور")
            for link in topic_links:
                if link not in visited:
                    queue.append((link, section))

        time.sleep(1.6)

    log.info("\n" + "="*110)
    log.info("🏁 انتهى الزحف بنجاح")
    log.info(f"الصفحات المزحوفة : {pages_crawled}")
    log.info(f"الوثائق المحفوظة : {documents_saved}")
    log.info(f"إجمالي المواد     : {articles_saved}")
    log.info("="*110)

    if dry_run:
        log.info("🏁 انتهى الزحف التجريبي (dry-run) — لم يُحفظ شيء")
        log.info(f"الصفحات المزحوفة : {pages_crawled}")
        log.info(f"سيُحفظ عند التشغيل الفعلي: {would_docs} وثيقة | {would_arts} مادة")
    else:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM documents")
        docs = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) as c FROM articles")
        arts = cursor.fetchone()["c"]
        log.info(f"📊 الحالة النهائية في قاعدة البيانات: {docs} وثيقة | {arts} مادة")
        conn.close()


if __name__ == "__main__":
    start_crawling(max_pages=50)