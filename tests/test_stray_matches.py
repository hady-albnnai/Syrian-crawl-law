# -*- coding: utf-8 -*-
"""إحالات داخل المتن لا تشطر المادة (قانون العقوبات: 899 مادة مطوية بنص مختلف)."""
from extractor_v4 import extract_articles_v4


def _doc(parts):
    return "\n".join(parts)


def _body(n):
    return f"نص المادة رقم {n} وفيه كلام كافٍ ليتجاوز الحد الأدنى للطول."


def test_in_text_reference_does_not_split_the_article():
    parts = []
    for n in range(1, 16):
        parts.append(f"المادة {n}")
        if n == 5:
            parts.append(_body(n) + " ويجري ذلك وفق\nالمادة 12 من هذا القانون ويتابع النص بعدها.")
        else:
            parts.append(_body(n))
    _pre, arts = extract_articles_v4(_doc(parts), line_anchored=False)
    nums = [a["article_number"] for a in arts]
    assert nums == list(range(1, 16))
    art5 = next(a for a in arts if a["article_number"] == 5)
    assert "ويتابع النص بعدها" in art5["text"]       # لا يضيع حرف


def test_numbering_restart_sections_are_preserved():
    parts = []
    for n in list(range(1, 16)) + list(range(1, 16)):
        parts += [f"المادة {n}", _body(n)]
    _pre, arts = extract_articles_v4(_doc(parts))
    assert len(arts) == 30


def test_repeated_articles_with_suffix_are_kept():
    parts = []
    for n in range(1, 13):
        parts += [f"المادة {n}", _body(n)]
        if n == 6:
            parts += ["المادة 6 مكررة", _body(60)]
    _pre, arts = extract_articles_v4(_doc(parts))
    assert len(arts) == 13
    assert any("مكرر" in a["label"] for a in arts)


def test_short_documents_are_untouched():
    parts = []
    for n in (1, 2, 1, 3):
        parts += [f"المادة {n}", _body(n)]
    _pre, arts = extract_articles_v4(_doc(parts))
    assert len(arts) == 4
