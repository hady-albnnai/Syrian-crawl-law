"""ف٨: قاموس الصكوك المسمّاة — على عناوين ونصوص قاعدة المالك حرفياً."""
import config
import database
import pytest
from named_laws import NAMED_LAWS, lookup_named_law


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "s.db"
    monkeypatch.setattr(config, "DB_PATH", p)
    monkeypatch.setattr(database, "DB_PATH", p)
    database.create_tables()
    conn = database.get_connection()
    yield conn
    conn.close()


def test_every_entry_has_a_source():
    assert all(e.get("source") for e in NAMED_LAWS)


def test_military_penal_code_by_title():
    r = lookup_named_law("قانون العقوبات العسكري", "قانون العقوبات العسكري المادة 1 1- ينظر في القضايا العسكرية")
    assert r["identity_key"] == "المرسوم التشريعي:61:1950"


def test_marker_disambiguates_state_council_versions():
    old = "قانون مجلس الدولة المادة 1 مجلس الدولة هيئة مستقلة تلحق برئاسة مجلس الوزراء."
    new = "قانون مجلس الدولة المادة 1 مجلس الدولة هيئة قضائية واستشارية مستقلة تتولى القضاء الاداري"
    assert lookup_named_law("قانون مجلس الدولة", old)["identity_key"] == "المرسوم التشريعي:55:1959"
    assert lookup_named_law("قانون مجلس الدولة", new) is None   # 32/2019 ليس في القاموس بعد


def test_economic_penal_marker_is_1966_not_2013():
    t = "المادة 1 أ- يقصد بالدولة في معرض تطبيق هذا المرسوم التشريعي الوزارات والادارات"
    assert lookup_named_law("قانون العقوبات الاقتصادية في سورية", t)["law_year"] == 1966


def test_presentation_forms_title_2016():
    assert lookup_named_law("ﻗﺎﻧﻮﻥ أﺻﻮﻝ ﺍﻟﻤﺤﺎﻛﻤﺎﺕ ﺍﻟﺴﻮﺭﻱ 2016", "")["identity_key"] == "القانون:1:2016"


def test_truncated_title_completes_missing_year():
    r = lookup_named_law("قانون التأمينات الاجتماعية الصادر بالمرسوم التشريعي رقم 92 لعام", "")
    assert (r["law_number"], r["law_year"]) == (92, 1959)


def test_unknown_named_law_stays_unidentified():
    assert lookup_named_law("قانون مصرف التوفير", "مصرف التوفير مؤسسة عامة") is None


def test_reidentify_uses_dictionary_and_never_overrides(db):
    from law_identity import reidentify_documents
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature) VALUES "
               "(105,'قانون العقوبات العسكري','قانون العقوبات العسكري المادة 1 ينظر','active','instrument')")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature,identity_key,number,year) VALUES "
               "(9,'قانون العقوبات العسكري','المادة 1','active','instrument','القانون:9:1999',9,1999)")
    db.commit()
    st = reidentify_documents(db)
    assert st["named"] == 1
    rows = {r[0]: r[1] for r in db.execute("SELECT id, identity_key FROM documents")}
    assert rows == {105: "المرسوم التشريعي:61:1950", 9: "القانون:9:1999"}


def test_civil_procedure_1953_vs_2016_by_marker():
    old = "قانون أصول المحاكمات المادة 1 1- تسري قوانين الأصول على ما لم يكن قد فصل فيه من الدعاوى أو تم من الإجراءات قبل."
    assert lookup_named_law("قانون أصول المحاكمات", old)["identity_key"] == "المرسوم التشريعي:84:1953"
    assert lookup_named_law("قانون أصول المحاكمات", "الباب الثاني : الحجز المادة/314/") is None


def test_traffic_law_and_extradition():
    assert lookup_named_law("قانون السير والمركبات ـ", "قانون السير والمركبات مادة 1 تعتمد في تطبيق احكام هذا القانون التعاريف الآتية: 1 المركبة")["identity_key"] == "القانون:31:2004"
    assert lookup_named_law("أصول تسليم المجرمين العاديين والملاحقين قضائيا بجرائم عادية رقم 53/1955  في سورية", "")["identity_key"] == "القانون:53:1955"


# --- جولة unidentified9 (بحث معمّق) ---------------------------------------------
def test_deep_search_round_entries():
    assert lookup_named_law("قانون مصرف التوفير", "قانون مصرف التوفير المادة 1 مصرف التوفير مؤسسة عامة ذات طابع اقتصادي")["identity_key"] == "المرسوم التشريعي:29:2005"
    assert lookup_named_law("المادة 5 ـ قانون الجمعيات التعاونية السكنية رقم 13", "")["identity_key"] == "القانون:13:1981"
    assert lookup_named_law("القانون رقم 34 ‏", "القانون رقم 34 المادة 1 يقصد بالتعابير الآتية في معرض أحكام هذا القانون المعني")["identity_key"] == "القانون:34:2004"
    assert lookup_named_law("قانون الحق العائلي لطائفة الروم الأرثوذكس", "")["identity_key"] == "القانون:23:2004"


def test_generic_title_matches_text_head_only_when_allowed():
    t = "قانون الآثار مادة 1 تعتبر آثارا الممتلكات الثابتة والمنقولة التي بناها أو صنعها أو أنتجها"
    assert lookup_named_law("وثيقة قانونية سورية", t)["identity_key"] == "المرسوم التشريعي:222:1963"
    # مدخل بلا match_text_head لا يُطابَق من المطلع
    assert lookup_named_law("وثيقة قانونية سورية", "قانون مصرف التوفير المادة 1 مصرف التوفير مؤسسة عامة ذات طابع اقتصادي") is None


def test_non_syrian_instruments_stay_out():
    assert lookup_named_law("الأحوال الشخصية للطائفة الدرزية", "المادة 1- يحوز الخاطب") is None
    assert lookup_named_law("نظام سر الزواج للكنيسة الشرقية", "") is None


def test_regulations_link_to_parent(db):
    from regulations import link_regulations
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature) VALUES "
               "(137,'اللائحة التنفيذية لقانون السجل العقاري','المادة 1 يتألف سجل الملكية','active','instrument')")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature) VALUES "
               "(111,'التعليمات التنفيذية للمرسوم التشريعي ذي الرقم /55','المادة (1)','active','instrument')")
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature) VALUES "
               "(1,'قانون السير والمركبات','مادة 1','active','instrument')")
    db.commit()
    rep = link_regulations(db)
    assert rep == {"linked": 2, "own_identity": 1}
    r = {x["id"]: (x["parent_identity"], x["identity_key"]) for x in
         db.execute("SELECT id, parent_identity, identity_key FROM documents")}
    assert r[137] == ("القرار:188:1926", "القرار:189:1926")
    assert r[111] == ("المرسوم التشريعي:55:2004", None)
    assert r[1] == (None, None)


def test_dictionary_wins_over_body_reference_contradicting_title(db):
    # #162: العنوان «رقم 13»، المتن يحيل إلى «قانون العفو العام 17» (رأس إصدار غائب)
    from law_identity import reidentify_documents
    db.execute("INSERT INTO documents(id,title,clean_content,status,nature) VALUES "
               "(162,'المادة 5 ـ قانون الجمعيات التعاونية السكنية رقم 13',"
               "'المادة 5 قانون الجمعيات التعاونية السكنية رقم 13 قانون العفو العام رقم 17 لعام 1985 نص','active','instrument')")
    db.commit()
    reidentify_documents(db)
    r = db.execute("SELECT identity_key FROM documents WHERE id=162").fetchone()
    assert r["identity_key"] == "القانون:13:1981"
