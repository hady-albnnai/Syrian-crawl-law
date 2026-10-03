# -*- coding: utf-8 -*-
"""bunud.ai يقتطع الأرقام ذات الخانتين: المادة 11 تظهر «المادة 1» وأول سطر نصها «1»."""
import argparse
import bunud_source as b
import config, database, cli
from extractor_v4 import extract_main_content, extract_articles_v4


def test_truncated_two_digit_numbers_are_rebuilt_from_label_and_first_line():
    arts = [["المادة 9", ["نص تاسع"]], ["المادة 10", ["نص عاشر"]],
            ["المادة 1", ["1", "نص حادي عشر"]], ["المادة 1", ["2", "نص ثاني عشر"]],
            ["المادة 20", ["نص عشرون"]], ["المادة 2", ["1", "نص واحد وعشرون"]]]
    assert b._repair_truncated_numbers(arts) == 3
    assert [a[0] for a in arts] == ["المادة 9", "المادة 10", "المادة 11", "المادة 12",
                                     "المادة 20", "المادة 21"]
    assert arts[2][1] == ["نص حادي عشر"]          # سطر الخانة المنزلقة يُنزع


def test_repair_never_invents_numbers_outside_a_strict_sequence():
    # مادة أولى حقيقية بنصها «1- …» ليست خانة منزلقة؛ والمركّب 51 لا يلي 2
    arts = [["المادة 1", ["نص أول"]], ["المادة 2", ["نص ثان"]], ["المادة 5", ["1", "نص"]]]
    assert b._repair_truncated_numbers(arts) == 0
    assert [a[0] for a in arts] == ["المادة 1", "المادة 2", "المادة 5"]
    # أول مادة بلا سابق: لا إصلاح
    one = [["المادة 1", ["1", "نص"]]]
    assert b._repair_truncated_numbers(one) == 0 and one[0][1] == ["1", "نص"]


def test_item_suffix_is_kept_in_label_and_not_treated_as_stray():
    parts = []
    for n in range(1, 13):
        parts += [f"المادة {n}", f"نص المادة رقم {n} وفيه كلام كافٍ ليتجاوز الحد الأدنى للطول."]
        if n == 2:
            for k in (1, 1, 2):
                parts += [f"المادة 2 - بند {k}", f"صف جدول {k} وفيه كلام كافٍ ليتجاوز الحد الأدنى للطول."]
    _pre, arts = extract_articles_v4("\n".join(parts))
    labels = [a["label"] for a in arts]
    assert labels.count("2 - بند 1") == 2 and "2 - بند 2" in labels
    assert len(arts) == 15


def test_declared_line_anchored_ignores_inline_refs_below_70_percent():
    """قِيس 2026-10-03: 16 مادة حقيقية + 7 إحالات داخل المتن = 69.6% مطابقات على
    أول السطر؛ الحارس العام (≥70%) كان يسقط فتنشطر المواد بأرقام مكررة."""
    from extractor_v4 import extract_articles_v4
    lines = []
    for n in range(1, 17):
        lines.append(f"المادة {n}")
        body = f"نص المادة رقم {n} من هذا المرسوم التشريعي كامل"
        if n in (2, 3, 5, 6, 9, 10, 12):
            body += " وفق أحكام المادة (9) من هذا"
            body += " المرسوم ويطبق"
        lines.append(body)
    text = "\n".join(lines)
    _, arts = extract_articles_v4(text, line_anchored=True)
    nums = [a["article_number"] for a in arts]
    assert nums == list(range(1, 17))
    # بلا إعلان المصدر يبقى السلوك القديم (لا مساس بالمصادر الأخرى)
    _, arts_plain = extract_articles_v4(text, line_anchored=False)
    assert len(arts_plain) >= 16


def test_part_suffix_keeps_segmented_articles_distinct():
    """«المادة 2 - الجزء N» أجزاء مشروعة لمادة طويلة (قانون 10/2018): لا تُحذف ولا تُعدّ تكراراً."""
    from extractor_v4 import extract_articles_v4
    lines = []
    for n in range(1, 13):
        lines.append(f"المادة {n}")
        lines.append(f"نص المادة رقم {n} من هذا القانون كامل ويتجاوز الحد الأدنى للطول")
        if n == 2:
            for k in (1, 2, 3):
                lines.append(f"المادة 2 - الجزء {k}")
                lines.append(f"نص الجزء رقم {k} من المادة الثانية ويتجاوز الحد الأدنى للطول")
    _, arts = extract_articles_v4("\n".join(lines), line_anchored=True)
    labels = [a["label"] for a in arts]
    assert "2 الجزء 1" in labels or any("جزء" in l for l in labels)
    keys = [(a["article_number"], a["label"]) for a in arts]
    assert len(keys) == len(set(keys))


def test_inline_self_reference_does_not_split_article():
    """«المادة 7 … الواردة في المادة 7»: إشارة وسط السطر تكرر الرقم السابق ليست مادة."""
    from extractor_v4 import extract_articles_v4
    lines = []
    for n in range(1, 21):
        lines.append(f"المادة {n}")
        lines.append(f"نص المادة رقم {n} كامل ويتجاوز الحد الأدنى للطول وفق الشروط الواردة في المادة {n} من هذا القانون وتتمة")
    _, arts = extract_articles_v4("\n".join(lines))
    assert [a["article_number"] for a in arts] == list(range(1, 21))


def test_same_number_twice_on_line_start_is_kept():
    """الحارس الجديد لا يمس تكرار الرقم على أول سطر (القرار فيه لقواعد أخرى)."""
    from extractor_v4 import ARTICLE_RE, drop_inline_self_refs
    text = "المادة 5\nنص كامل هنا\nالمادة 5\nنص آخر كامل\nوفق المادة 5 من هذا"
    ms = list(ARTICLE_RE.finditer(text))
    kept = drop_inline_self_refs(text, ms)
    assert len(ms) == 3 and len(kept) == 2


def test_inline_reference_to_other_article_is_dropped_but_inline_real_article_kept():
    from extractor_v4 import extract_articles_v4
    lines = []
    for n in range(1, 21):
        lines.append(f"المادة {n}")
        body = f"نص المادة رقم {n} كامل ويتجاوز الحد الأدنى للطول"
        if n in (3, 8, 14):
            body += " وفق أحكام المادة 20 من هذا القانون وبعد الإحالة إلى المادة 2 منه تتمة"
        lines.append(body)
    # مادة 11 حقيقية سقط فاصل السطر قبلها (وسط السطر بين 10 و12) — يجب أن تبقى
    text = "\n".join(lines).replace("\nالمادة 11\n", " المادة 11 ")
    _, arts = extract_articles_v4(text)
    nums = [a["article_number"] for a in arts]
    assert nums == list(range(1, 21))


def test_bunud_sy_path_counts_as_syrian_source_but_foreign_evidence_still_wins():
    from jurisdiction import assess_jurisdiction
    j = assess_jurisdiction("https://www.bunud.ai/sy/laws/maritime-law", "القانون 63 لعام 1961 النقل البحري", "نص", "")
    assert j["verdict"] == "syrian"
    j2 = assess_jurisdiction("https://www.bunud.ai/eg/laws/x", "قانون", "نص", "")
    assert j2["verdict"] != "syrian"
