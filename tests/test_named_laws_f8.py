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
