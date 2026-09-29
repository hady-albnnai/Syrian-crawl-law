from jurisdiction import assess_jurisdiction as j


def test_syrian_official_text_is_syrian():
    r = j("https://example.org/x", "قانون", "الجمهورية العربية السورية مرسوم تشريعي رقم 84 لعام 1949 "
          "القانون المدني السوري")
    assert r["verdict"] == "syrian"


def test_sy_domain_alone_reaches_syrian():
    assert j("https://www.moj.gov.sy/law", "", "")["verdict"] == "syrian"


def test_egyptian_text_is_foreign_and_named():
    r = j("https://example.org", "", "جمهورية مصر العربية القانون المصري رقم 5 محكمة النقض المصرية")
    assert r["verdict"] == "foreign" and r["foreign_country"] == "مصر"


def test_foreign_tld_is_only_a_hint_not_enough_alone():
    assert j("https://law.gov.eg/x", "", "")["verdict"] == "unknown"


def test_regional_portal_with_both_is_mixed():
    text = ("الجمهورية العربية السورية مرسوم تشريعي القانون السوري نقض سوري "
            "جمهورية مصر العربية القانون المصري محكمة النقض المصرية الوقائع المصرية")
    assert j("https://arab-law.example", "", text)["verdict"] == "mixed"


def test_mere_mention_of_syria_is_not_syrian():
    r = j("https://news.example", "", "زار الوفد سوريا وسوريا وسوريا وسورية")
    assert r["verdict"] == "unknown"


def test_lebanese_legislative_decree_marker_is_foreign():
    r = j("https://example.org", "", "الجمهورية اللبنانية مرسوم اشتراعي القانون اللبناني")
    assert r["verdict"] == "foreign"


def test_no_evidence_is_unknown_not_syrian():
    assert j("https://example.org", "قانون العقوبات", "المادة 1 ...")["verdict"] == "unknown"
