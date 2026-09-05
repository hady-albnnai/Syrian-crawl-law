# -*- coding: utf-8 -*-
"""
database.py
مسؤول عن إنشاء قاعدة البيانات وإدارة الجداول
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

from config import DB_PATH, create_directories

# التأكد من وجود المجلدات
create_directories()


def get_connection():
    """إرجاع اتصال بقاعدة البيانات"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # لإرجاع النتائج كـ dictionary
    # تفعيل القيود الخارجية (دفعة P0): sqlite يعطّلها افتراضياً، وبدونها كانت
    # المواد اليتيمة (doc_id خاطئ) تمر بصمت عند تجاهل INSERT OR IGNORE.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables():
    """إنشاء جميع الجداول المطلوبة"""
    conn = get_connection()
    cursor = conn.cursor()

    # جدول الوثائق (Documents)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT UNIQUE,
        title TEXT,
        doc_type TEXT,
        number INTEGER,
        year INTEGER,
        branch TEXT,
        branch_confidence REAL,
        source_url TEXT UNIQUE,
        source_credibility REAL DEFAULT 0.6,
        status TEXT DEFAULT 'active',
        review_status TEXT DEFAULT 'auto_accepted',
        legal_score REAL,
        content_hash TEXT,
        scraped_at TEXT,
        updated_at TEXT,
        raw_content TEXT,
        clean_content TEXT
    )
    ''')

    # جدول المواد (Articles) - قلب النظام
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id INTEGER,
        article_number TEXT,
        article_label TEXT,
        hierarchy_path TEXT,
        text TEXT,
        paragraphs_json TEXT,
        related_articles_json TEXT,
        amended_by TEXT,
        status TEXT DEFAULT 'active',
        char_count INTEGER,
        FOREIGN KEY (doc_id) REFERENCES documents(id)
    )
    ''')

    # جدول النماذج القانونية (مهم لمشروع "ميزان")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        template_type TEXT,
        branch TEXT,
        body TEXT,
        based_on_articles_json TEXT,
        source_url TEXT,
        created_at TEXT
    )
    ''')

    # جدول الاجتهادات والأحكام
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS precedents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        court TEXT,
        judgment_number TEXT,
        judgment_year INTEGER,
        judgment_date TEXT,
        principle TEXT,
        summary TEXT,
        full_text TEXT,
        related_articles_json TEXT,
        source_url TEXT,
        scraped_at TEXT
    )
    ''')

    # جدول إدارة الزحف (لاستئناف العمل بعد الانقطاع)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS crawl_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        event_type TEXT,
        message TEXT,
        status TEXT,
        timestamp TEXT
    )
    ''')

    # جدول لتجنب تكرار الروابط
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS seen_urls (
        url_hash TEXT PRIMARY KEY,
        url TEXT,
        first_seen TEXT,
        last_visited TEXT,
        status TEXT
    )
    ''')

    conn.commit()
    conn.close()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] تم إنشاء جميع جداول قاعدة البيانات بنجاح")


def insert_log(url: str, event_type: str, message: str, status: str = "info"):
    """إدخال حدث في سجل الزحف"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO crawl_log (url, event_type, message, status, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (url, event_type, message, status, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_db_info():
    """إعطاء معلومات عن قاعدة البيانات"""
    path = Path(DB_PATH)
    if path.exists():
        size = path.stat().st_size / (1024*1024)
        print(f"قاعدة البيانات موجودة بحجم: {size:.2f} MB")
        return True
    else:
        print("قاعدة البيانات غير موجودة بعد")
        return False


# ====================== تشغيل عند فتح الملف مباشرة ======================
if __name__ == "__main__":
    print("=" * 60)
    print("إعداد قاعدة بيانات مشروع الأرشفة القانونية السورية")
    print("=" * 60)
    create_tables()
    get_db_info()
    print("\n✅ تم إعداد قاعدة البيانات بنجاح!")
    print(f"   المسار: {DB_PATH}")