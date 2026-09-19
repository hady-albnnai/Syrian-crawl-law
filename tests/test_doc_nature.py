# -*- coding: utf-8 -*-
"""ف٤ — طبيعة الوثيقة. الحالات كلها عناوين/مطالع حقيقية من عيّنة المالك
(unidentified.txt، 2026-09-19: 262 وثيقة «بلا هوية»)، لا اختراع."""
import sqlite3

import pytest

import doc_nature as dn
from doc_nature import classify_nature


# --- travaux: 208 من 262 -------------------------------------------------
@pytest.mark.parametrize("title,body,art", [
    ("الأعمال التحضيرية للقانون المدني المتعلقة بالمادة    70",
     "الأعمال التحضيرية: وردت أحكام هذه المادة في المشروع التمهيدي تحت رقم 1412",
     70),
    ("الأعمال التحضيرية للقانون المدني المتعلقة بالمادة    1120", "", 1120),
    # مطلع مبتور الهمزة كما ورد فعلاً بالقاعدة: «لأعمال التحضيرية:»
    ("عنوان مفقود",
     "لأعمال التحضيرية: وردت هذه المادة في المشروع التمهيدي تحت رقم 277",
     None),
    ("عنوان مفقود", "الرأي الفقهي: يتبين من نص المادة 196 أنه يفرض", None),
])
def test_travaux_detected_with_parent_and_article(title, body, art):
    c = classify_nature(title, body)
    assert c["nature"] == "travaux"
    assert c["article_no"] == art
    if "القانون المدني" in title:
        assert c["parent_hint"] == "القانون المدني"


# --- index_page / draft / non_legal ---------------------------------------
def test_index_pages_by_title_or_pagination_body():
    assert classify_nature("استشارات قانونية مجانية",
                           "تصنيف : المكتبة القانونية (الصفحة 1 من 675) …"
                           )["nature"] == "index_page"
    assert classify_nature("أي عنوان",
                           "وسم : العقوبات (الصفحة 1 من 38) قانون العقوبات"
                           )["nature"] == "index_page"


def test_draft_law_is_not_an_instrument():
    assert classify_nature("مشروع قانون الاحوال الشخصية السوري",
                           "الكتاب الرابع , انحلال الزواج")["nature"] == "draft"


@pytest.mark.parametrize("title,body", [
    ("توتر كبير بين نقابة المحامين الفلسطيين ومجلس القضاء الاعلى بسبب تفتيش المحامي",
     "توتر كبير 28 يونيو، 2025 / شادي عبد الفتاح / لا تعليقات بعد"),
    # حروف عرض (Presentation Forms) كما جاءت من PDF
    ("ﺍﻟﺠﺮﻳﻤﺔ ﺍﻟﻤﻌﻠﻮﻣﺎﺗﻴﺔ .ﺭﺳﺎﻟﺔ ﻣﺎﺟﺴﺘﻴﺮ ﻟﻠﻂﺎﻟﺐ براء ﺍﻟﺤﺮﻳﺮﻱ.",
     "لمحة عامة عن مضمون الرساله"),
    ("نظام بودابست - النظام الدولي لإيداع الكائنات الدقيقة", ""),
    ("اهمية التحكيم", "اهمية التحكيم 5 مايو، 2020 / احمد / لا تعليقات بعد التحكيم"),
])
def test_non_legal(title, body):
    assert classify_nature(title, body)["nature"] == "non_legal"


# --- instrument: لا نُخرج صكاً بالشك ---------------------------------------
@pytest.mark.parametrize("title,body", [
    ("قانون تنظيم مهنة المحاماة لعام 2010",
     "الجمهورية العربية السورية القانون رقم 30 رئيس الجمهورية"),
    # مقال منصة يعيد نشر نص قانون كامل — رأسه صك ومتنه مواد ⇒ صك
    ("نصوص و مواد قانون العقوبات السوري",
     "نصوص و مواد قانون العقوبات السوري 23 فبراير، 2017 / ايثار موسى / "
     "لا تعليقات بعد قانون العقوبات السوري المادة 1 1 لا تفرض عقوبة"),
    ("ﻗﺎﻧﻮﻥ أﺻﻮﻝ ﺍﻟﻤﺤﺎﻛﻤﺎﺕ ﺍﻟﺴﻮﺭﻱ 2016", "الباب الثاني : الحجز"),
    ("الأحوال الشخصية للطائفة الدرزية", "المادة 1- يحوز الخاطب"),
    ("نظام سر الزواج للكنيسة الشرقية", "المادة 1 1- قد رفع"),
    ("لائحة التفتيش القضائي", "المادة 1 مع عدم الإخلال"),
    ("اللائحة التنفيذية لقانون السجل العقاري", "المادة 1 يتألف"),
    ("دستور الجمهورية العربية السورية،الجمهورية العربية السورية",
     "دستور الجمهورية العربية السورية 2012 المرسوم 94 لعام 2012"),
    ("وثيقة قانونية سورية", "القانون رقم 38 المادة 77- بعد تسجيل"),
    ("بالترخيص لمصارف سورية خاصة أو مشتركة وفق النص المرفق .", "المادة 2 ت"),
    ("المرسوم التشريعى رقم/30 المتعلق بامصرف الزراعي التعاوني", "المادة 1"),
])
def test_instruments_stay_instruments(title, body):
    assert classify_nature(title, body)["nature"] == "instrument"


# --- الميزان الكلي على عيّنة المالك (حراسة من الانحدار) --------------------
def test_owner_sample_distribution(tmp_path):
    """توزيع مُقاس بالدليل: 208 travaux / 4 index / 1 draft / 3 non_legal /
    46 instrument (42 حقيقية + 4 «وثيقة قانونية سورية» مقطّعة من قانون).
    يُبنى من نسخة العناوين المرفقة بالاختبار حتى لا يعتمد على ملف خارجي."""
    titles = (["الأعمال التحضيرية للقانون المدني المتعلقة بالمادة    %d" % i
               for i in range(208)]
              + ["استشارات قانونية مجانية"] * 4
              + ["مشروع قانون الاحوال الشخصية السوري"]
              + ["توتر كبير بين نقابة المحامين الفلسطيين",
                 "ﺍﻟﺠﺮﻳﻤﺔ ﺍﻟﻤﻌﻠﻮﻣﺎﺗﻴﺔ .ﺭﺳﺎﻟﺔ ﻣﺎﺟﺴﺘﻴﺮ ﻟﻠﻂﺎﻟﺐ",
                 "نظام بودابست - النظام الدولي لإيداع الكائنات الدقيقة"]
              + ["قانون مصرف التوفير"] * 46)
    dist = {}
    for t in titles:
        n = classify_nature(t, "")["nature"]
        dist[n] = dist.get(n, 0) + 1
    assert dist == {"travaux": 208, "index_page": 4, "draft": 1,
                    "non_legal": 3, "instrument": 46}


# --- التكامل: هجرة + إعادة تصنيف + المصدِّر يستثني غير الصكوك ----------------
@pytest.fixture
def db(tmp_path, monkeypatch):
    import config, database
    p = tmp_path / "n.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    from crawler import save_document
    cur = conn.cursor()
    save_document(cur, "sha256:a", "قانون مصرف التوفير", "https://x/a",
                  "banking_law", 0.8, 0.9, "h1", "المادة 1 مصرف التوفير")
    save_document(cur, "sha256:b",
                  "الأعمال التحضيرية للقانون المدني المتعلقة بالمادة    70",
                  "https://x/b", "civil_law", 0.8, 0.9, "h2",
                  "الأعمال التحضيرية: وردت أحكام هذه المادة")
    save_document(cur, "sha256:c", "استشارات قانونية مجانية", "https://x/c",
                  "civil_law", 0.8, 0.9, "h3",
                  "تصنيف : المكتبة (الصفحة 1 من 9)")
    for d in ("a", "b", "c"):
        conn.execute("INSERT INTO articles (doc_id, article_number, text, "
                     "char_count) SELECT id, '1', 'نص المادة الأولى', 16 "
                     "FROM documents WHERE doc_id=?", (f"sha256:{d}",))
    conn.commit()
    return conn, p


def test_schema_has_nature_and_reclassify_writes_it(db):
    conn, _ = db
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"nature", "travaux_article"} <= cols
    rep = dn.reclassify_documents(conn)
    assert rep["distribution"]["travaux"] == 1
    assert rep["distribution"]["index_page"] == 1
    assert rep["distribution"]["instrument"] == 1
    row = conn.execute("SELECT nature, travaux_article FROM documents "
                       "WHERE doc_id='sha256:b'").fetchone()
    assert (row["nature"], row["travaux_article"]) == ("travaux", 70)


def test_exporter_excludes_non_instruments(db, tmp_path):
    conn, p = db
    dn.reclassify_documents(conn)
    from exporter import build_package
    rep = build_package(db_path=p, out_dir=tmp_path / "pkg")
    assert rep["docs"] == 1
    assert rep["non_instruments"] == 2
    csv = (tmp_path / "pkg" / "laws_decrees_index.csv").read_text("utf-8-sig")
    assert "مصرف التوفير" in csv and "التحضيرية" not in csv


def test_legal_status_counts_unidentified_instruments_only(db):
    conn, _ = db
    dn.reclassify_documents(conn)
    from law_status import compute_legal_statuses
    counts = compute_legal_statuses(conn)
    assert counts["بلا هوية (صكوك)"] == 1
    assert counts["ليست صكوكاً (خارج العدّ)"] == 2


def test_migration_007_adds_columns_to_old_db(tmp_path, monkeypatch):
    """قاعدة على الإصدار 6 (قبل ف٤) تُرقَّى بالهجرة 7 بلا فقد: الصفوف
    القديمة تصبح instrument افتراضياً."""
    import config, database
    from migrations import migrate, get_version
    p = tmp_path / "v6.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = sqlite3.connect(p)
    # نحاكي قاعدة قديمة: نزيل عمودَي ف٤ ونُرجع الإصدار إلى 6
    conn.execute("ALTER TABLE documents DROP COLUMN nature")
    conn.execute("ALTER TABLE documents DROP COLUMN travaux_article")
    conn.execute("INSERT INTO documents (doc_id, title, source_url) "
                 "VALUES ('x', 'قانون', 'https://x/1')")
    conn.execute("PRAGMA user_version = 6")
    conn.commit(); conn.close()
    migrate(p)
    conn = sqlite3.connect(p)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"nature", "travaux_article"} <= cols
    assert conn.execute("SELECT nature FROM documents").fetchone()[0] == "instrument"
    assert get_version(conn) >= 7
