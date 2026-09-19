

def test_basic_law_type_folds_into_law():
    from law_identity import extract_law_identity
    r = extract_law_identity("القانون الأساسي للعاملين في الدولة رقم 50 لعام 2004", "")
    assert r["identity_key"] == "القانون:50:2004"
