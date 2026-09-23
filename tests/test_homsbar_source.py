# -*- coding: utf-8 -*-
import io
import zipfile

import homsbar_source as hb
from database import create_tables, get_connection

# ثلاثة استشهادات سورية كاملة الأركان (نفس نمط اختبارات بلوغر المعتمدة)
SY_LINES = [
    "إن الإكراه لا يجعل العقود المبرمة تحت سلطانه باطلة بطلاناً مطلقاً.",
    "(نقض مدني سوري 247 أساس 481 تاريخ 27/3/1961)",
    "الاكراه المعطل للرضا لا يتحقق إلا بالتهديد الذي يكون من نتيجته خوف شديد.",
    "(نقض رقم 3182 اساس 10376 تاريخ 4/11/1991 سجلات النقض)",
    "يتوجب اعادة ما ليس مستحقاً إذا دفع تحت الاكراه ولمحكمة الموضوع السلطة التامة.",
    "(قرار نقض رقم 575 أساس 3323 تاريخ 4 / 6 / 1978)",
]

INDEX = ('<sitemapindex xmlns="x">'
         '<sitemap><loc>https://homsbar.org/wp-sitemap-posts-law-1.xml</loc></sitemap>'
         '<sitemap><loc>https://homsbar.org/wp-sitemap-posts-juris_article-1.xml</loc></sitemap>'
         '</sitemapindex>')
JURIS_MAP = ('<urlset xmlns="x"><url><loc>https://homsbar.org/juris_article/هيئة-عامة/</loc></url>'
             '<url><loc>https://homsbar.org/juris_article/فارغ/</loc></url></urlset>')
PAGE = ('<html><body><h1>اجتهادات هيئة عامة فقط 2003 وماقبل</h1>'
        '<a href="https://homsbar.org/wp-content/uploads/2015/08/هيئة-عامة.docx">انقر هنا للتحميل</a>'
        '</body></html>')
PAGE_EMPTY = '<html><body><h1>مقال بلا مرفقات</h1></body></html>'


def _docx(lines) -> bytes:
    paras = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in lines)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{paras}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _http_text(url):
    if url.endswith("/wp-sitemap.xml"):
        return (200, INDEX, {})
    if url.endswith("juris_article-1.xml"):
        return (200, JURIS_MAP, {})
    if url.endswith("/%D9%87%D9%8A%D8%A6%D8%A9-%D8%B9%D8%A7%D9%85%D8%A9/") or url.endswith("هيئة-عامة/"):
        return (200, PAGE, {})
    return (200, PAGE_EMPTY, {})


def _http_bytes(url):
    if url.endswith(".docx"):
        return (200, _docx(SY_LINES), {})
    return (404, b"", {})


def test_homsbar_harvest_end_to_end(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()
    st = hb.harvest(conn, http_get_text=_http_text, http_get_bytes=_http_bytes)
    assert st["juris_pages"] == 2
    assert st["attachments"] == 1 and st["downloaded"] == 1
    assert st["candidates"] == 1 and st["written"] == 3
    # الاستئناف: المقال نفسه لا يُعاد تنزيله
    st2 = hb.harvest(conn, http_get_text=_http_text, http_get_bytes=_http_bytes)
    assert st2["seen"] == 1 and st2["written"] == 0
    conn.close()


def test_homsbar_dry_run_no_write(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()
    st = hb.harvest(conn, http_get_text=_http_text, http_get_bytes=_http_bytes, dry_run=True)
    assert st["citations"] == 3 and st["pages_written"] == 0
    conn.close()


def test_page_attachments_resolves_and_dedupes():
    html = ('<a href="/wp-content/uploads/a.doc">١</a>'
            '<a href="https://homsbar.org/wp-content/uploads/a.doc">٢</a>'
            '<a href="/wp-content/uploads/b.zip">٣</a>'
            '<img src="/wp-content/uploads/x.png">')
    atts = hb.page_attachments(html)
    assert len(atts) == 2  # a.doc بعد الدمج == المكرر المطلق؛ وb.zip؛ وصور مرفوضة
    assert all(u.startswith("https://homsbar.org/wp-content/uploads/") for u in atts)


def test_extract_docx_and_zip_and_legacy():
    docx = _docx(SY_LINES)
    assert "نقض مدني سوري 247" in hb.extract_text(docx)
    # أرشيف مضغوط يحوي docx في داخله
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("اجتهادات/ملف.docx", docx)
    assert "نقض" in hb.extract_text(buf.getvalue())
    # Word ثنائي قديم: نص عربي داخل ضجيج ثنائي بترميز UTF-16LE
    inner = "قرار الهيئة العامة لمحكمة النقض رقم 123 أساس 456 لعام 2000 مبدأ قانوني مستقر"
    raw = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00\x07\x05" * 40 \
        + inner.encode("utf-16-le") + b"\xff\xfe\x01" * 40
    assert "الهيئة العامة" in hb.extract_text(raw)


def test_list_juris_filters_only_juris_maps():
    urls = hb.list_juris_urls(http_get_text=_http_text)
    assert len(urls) == 2 and all("/juris_article/" in u for u in urls)


def test_harvest_file_writes_and_resumes(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    create_tables()
    conn = get_connection()
    f = tmp_path / "مجموعة-درايف.docx"
    f.write_bytes(_docx(SY_LINES))
    st = hb.harvest_file(conn, str(f))
    assert st["citations"] == 3 and st["written"] == 3
    st2 = hb.harvest_file(conn, str(f))
    assert st2["seen"] == 1 and st2["written"] == 0
    conn.close()
