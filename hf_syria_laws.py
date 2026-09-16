# -*- coding: utf-8 -*-
"""
hf_syria_laws.py — تبنٍّ مرحلي محروس لمجموعة ipfs_syria_laws (ف٢).

القرار التنفيذي (المالك 2026-09-16 — «الاثنان معاً»): الصفوف الجاهزة
من المجموعة (endomorphosis/ipfs_syria_laws: 174 صكاً/7,179 مادة، مسح
بحثي لصفحات مجلس الشعب الأصلية عبر أرشيف الإنترنت) تدخل المتن الآن
عبر نفس بوابات الأنبوب حصراً — لا مسار خاص؛ وعند بناء زحف الأصول
المؤرشفة (طبقة 1) يفوز الأصل بآلية dedup فيُستبدل في المكان.

الإسناد الصادق: طبقة 3 (نص رسمي منقول عبر مجموعة مجتمعية موثوقة —
نفس منطق ar.wikisource: ليست الناشر لكنها تحمل نصه) تُمرَّر بالمهمة
صراحة؛ المهمة تحمل رابط parliament الأصلي ← doc_id مستقر ← عند زحف
الأصل لاحقاً تُطلق آلية الترقية «استُبدلت بنسخة أفضل» تلقائياً.

الصفوف الفارغة (63 صكاً بمواد صفرية — فشل مستخرج المجموعة على PDFات
jus.moj، ومرض انعكاس الأرقام ظاهر بعناوينها) تُهمل هنا وتبقى بفهرس
الاكتشاف output/hf_index.json لزحف الأرشيف اللاحق.
"""
import hashlib
from pathlib import Path

import requests

from config import (HF_ARTICLES_SHA256, HF_IMPORT_DOMAIN_TIER,
                    HF_LAWS_SHA256, HF_SYRIA_LAWS_DIR, HF_SYRIA_LAWS_REPO,
                    USER_AGENT)
from logging_setup import get_log
from urls import canonicalize_url

log = get_log("hf_import")

_BASE = f"https://huggingface.co/datasets/{HF_SYRIA_LAWS_REPO}/resolve/main"
_FILES = {"laws.parquet": HF_LAWS_SHA256,
          "articles.parquet": HF_ARTICLES_SHA256}
SECTION = "أرشيف مجلس الشعب (مجموعة HF — ف٢)"


def dataset_dir() -> Path:
    return Path(__file__).parent / HF_SYRIA_LAWS_DIR


def download_dataset() -> dict:
    """تنزيل الباركيه إن غاب + تحقق sha256 ضد مانيفست المجموعة."""
    out = dataset_dir()
    out.mkdir(parents=True, exist_ok=True)
    status = {}
    for name, digest in _FILES.items():
        path = out / name
        if path.exists() and hashlib.sha256(
                path.read_bytes()).hexdigest() == digest:
            status[name] = "موجود سابقاً"
            continue
        r = requests.get(f"{_BASE}/data/{name}", timeout=180,
                         headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        got = hashlib.sha256(r.content).hexdigest()
        if got != digest:
            raise RuntimeError(
                f"بصمة {name} مختلفة عن مانيفست المجموعة: {got} ≠ {digest}")
        path.write_bytes(r.content)
        status[name] = f"نُزّل ({len(r.content):,} بايت)"
    return status


def load_laws_with_articles(laws_path=None, articles_path=None):
    """[(law_row, [article_rows...])] بترتيب القوانين — pyarrow مؤجل."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise RuntimeError(
            "hf_parquet_module_missing — ثبّت المكتبة: pip install pyarrow")
    d = dataset_dir()
    laws = pq.read_table(laws_path or d / "laws.parquet").to_pylist()
    arts = pq.read_table(articles_path or d / "articles.parquet").to_pylist()
    by_law = {}
    for a in arts:
        by_law.setdefault(a["law_id"], []).append(a)
    return [(l, by_law.get(l["id"], [])) for l in laws]


def to_import_html(title: str, article_rows: list) -> str:
    """HTML مصنّع بنمط to_pipeline_html: سطر لكل مادة (نصوص المجموعة
    تبدأ ب«المادة N») — نفس المستخرج والبوابات والهرمية."""
    paras = [f"<p>{(a.get('text') or '').strip()}</p>"
             for a in article_rows if (a.get("text") or "").strip()]
    return (f'<html><body><article><div class="entry-content">'
            f"<h1>{title}</h1>\n" + "\n".join(paras)
            + "\n</div></article></body></html>")


def import_hf_laws(conn, laws_path=None, articles_path=None,
                   dry_run: bool = False) -> dict:
    """التبني المرحلي عبر _handle_topic بكل بواباته (لا مسار خاص).

    يعيد أعداد المصير: imported (حُفظ) / alternate (نسخة بديلة لهوية
    أفضل موجودة) / skipped (مطابق سابقاً) / needs_review / failed /
    empty (صفوف بلا مواد — تبقى بالفهرس لزحف الأرشيف). ويكتب فهرس
    الاكتشاف output/hf_index.json لكل الصكوك (174).
    """
    import json
    import crawl_queue as taskqueue
    import crawler

    pairs = load_laws_with_articles(laws_path, articles_path)
    stats = {"imported": 0, "alternate": 0, "skipped": 0,
             "needs_review": 0, "failed": 0, "empty": 0}
    index = []
    for law, arts in pairs:
        index.append({"id": law.get("id"), "title": law.get("title"),
                      "url": law.get("source_url"), "articles": len(arts)})
        if not arts:
            stats["empty"] += 1
            continue
        url = law["source_url"]
        key = canonicalize_url(url)
        taskqueue.enqueue(conn, url, SECTION, "topic")
        row = conn.execute("SELECT id FROM crawl_tasks WHERE url=?",
                           (key,)).fetchone()
        # استيراد سابق لنفس الرابط بمحتوى مطابق/أفضل: المهام success
        # لا تُعاد — والمحتوى نفسه سيُتخطى idempotently بفحص doc_id.
        task = {"id": row["id"], "url": url, "section": SECTION,
                "kind": "topic", "domain_tier": HF_IMPORT_DOMAIN_TIER}
        crawl_stats = {"pages": 0, "docs": 0, "articles": 0,
                       "skipped": 0, "failures": 0}
        if dry_run:
            crawl_stats["pages"] = 1
        crawler._handle_topic(conn, task, to_import_html(law["title"], arts),
                              dry_run, crawl_stats)
        status = conn.execute("SELECT status FROM crawl_tasks WHERE id=?",
                              (row["id"],)).fetchone()["status"]
        doc = conn.execute(
            "SELECT status FROM documents WHERE doc_id=?",
            (crawler.make_doc_id(url),)).fetchone()
        if crawl_stats["failures"]:
            stats["failed"] += 1
        elif crawl_stats["skipped"]:
            stats["skipped"] += 1
        elif status == "needs_review":
            stats["needs_review"] += 1
        elif doc is not None and doc["status"] == "alternate_source":
            stats["alternate"] += 1
        else:
            stats["imported"] += 1
    conn.commit()
    out = Path(__file__).parent / "output"
    out.mkdir(exist_ok=True)
    (out / "hf_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats
