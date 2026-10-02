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
