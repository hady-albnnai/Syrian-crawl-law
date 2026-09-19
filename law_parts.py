# -*- coding: utf-8 -*-
"""ف٧ — تجميع أجزاء الصك الواحد المشتّتة على عدة وثائق.

قِيس على قاعدة المالك (2026-09-19): قانون الجمارك 38 دخل شذراتٍ بعنوان عام
«وثيقة قانونية سورية» يبدأ نصها «القانون رقم 38 المادة 77…»؛ والمرسوم
التشريعي 30 (المصرف الزراعي) أربعُ نسخ كلٌّ منها يبدأ من مادة مختلفة؛ وأصول
المحاكمات 2016 وثيقةٌ تبدأ من المادة 314. هذه ليست مكرّرات (المكرَّر = نفس
sha256) بل أجزاء، وميزان يجب أن يراها صكاً واحداً بمواده مرتبة.

القاعدة (لا حسم بلا دليلين):
  1. مجموعة الأجزاء = نفس (doc_type أو None, number) مع سنة متطابقة أو غائبة
     في أحد الطرفين — والسنة لا تُخترع: الأصل يحمل سنةً إن حملها أحد الأجزاء،
     وإلا يبقى بلا identity_key (يُكمَل بالقاموس المرجعي لاحقاً).
  2. نطاقات المواد (أول مادة → آخر مادة بكل جزء) لا تتداخل بأكثر من مادتين
     — التداخل الكبير يعني نسختين لنفس النص لا جزأين، فتُترك لآلية المكرّرات.
  3. الأصل (الرأس) = الجزء الذي يبدأ بأصغر رقم مادة؛ الباقي part_of → الرأس.
     لا يُحذف شيء ولا يُدمج نص؛ العلاقة فقط، والتصدير يرتّب بها.
"""
from __future__ import annotations

import re

from extractor_v4 import ARTICLE_RE, to_western_digits

_MAX_OVERLAP = 2


def article_range(text: str) -> tuple[int, int] | None:
    """(أول رقم مادة، آخر رقم مادة) في النص، بالأرقام فقط (اللفظية تُهمل)."""
    nums = []
    for m in ARTICLE_RE.finditer(text or ""):
        if m.group(1):
            try:
                nums.append(int(to_western_digits(m.group(1))))
            except ValueError:
                pass
    if not nums:
        return None
    return (nums[0], max(nums))


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return max(0, hi - lo + 1)


def group_parts(docs: list[dict]) -> list[dict]:
    """يعيد قائمة مجموعات: {head_id, part_ids, number, year, doc_type}.

    docs: [{id, doc_type, number, year, identity_key, text}] — صكوك نشطة
    فقط. الأعضاء الوحيدون لا يُعادون (لا مجموعة من جزء واحد).
    """
    buckets: dict[int, list[dict]] = {}
    for d in docs:
        if not d.get("number"):
            continue
        rng = article_range(d.get("text") or "")
        if rng is None:
            continue
        buckets.setdefault(int(d["number"]), []).append({**d, "range": rng})

    groups = []
    for number, members in buckets.items():
        if len(members) < 2:
            continue
        # فصل حسب السنة: سنة معلومة تجمع معها الغائبة؛ سنتان مختلفتان تفترقان
        years = {m.get("year") for m in members if m.get("year")}
        if len(years) > 1:
            continue  # صكّان مختلفان بنفس الرقم — لا تخمين
        # فصل حسب النوع المعلوم
        types = {m.get("doc_type") for m in members if m.get("doc_type")}
        if len(types) > 1:
            continue
        members.sort(key=lambda m: m["range"][0])
        accepted = [members[0]]
        for m in members[1:]:
            if all(_overlap(m["range"], a["range"]) <= _MAX_OVERLAP
                   for a in accepted):
                accepted.append(m)
        if len(accepted) < 2:
            continue
        head = accepted[0]
        groups.append({
            "head_id": head["id"],
            "part_ids": [m["id"] for m in accepted[1:]],
            "number": number,
            "year": next(iter(years)) if years else None,
            "doc_type": next(iter(types)) if types else None,
            "ranges": {m["id"]: m["range"] for m in accepted},
        })
    return groups


def link_parts(conn) -> dict:
    """يحسب المجموعات ويكتب documents.part_of للأجزاء (الرأس part_of=NULL).

    يُعاد الحساب من الصفر كل مرة (يُصفَّر العمود أولاً) كي لا تبقى روابط
    يتيمة بعد تحسّن الهوية. يعيد {groups, parts_linked}.
    """
    conn.execute("UPDATE documents SET part_of=NULL")
    rows = conn.execute(
        """SELECT id, number, year, identity_key, clean_content
           FROM documents WHERE status='active'
           AND COALESCE(nature,'instrument')='instrument'
           AND number IS NOT NULL"""
    ).fetchall()
    docs = []
    for r in rows:
        dt = (r["identity_key"] or "").split(":")[0] or None
        docs.append({"id": r["id"], "doc_type": dt, "number": r["number"],
                     "year": r["year"], "identity_key": r["identity_key"],
                     "text": r["clean_content"] or ""})
    groups = group_parts(docs)
    n = 0
    for g in groups:
        for pid in g["part_ids"]:
            conn.execute("UPDATE documents SET part_of=? WHERE id=?",
                         (g["head_id"], pid))
            n += 1
        # الرأس يرث السنة/الهوية من أي جزء يحملها (بلا اختراع)
        if g["year"]:
            conn.execute(
                "UPDATE documents SET year=COALESCE(year,?) WHERE id=?",
                (g["year"], g["head_id"]))
    conn.commit()
    return {"groups": len(groups), "parts_linked": n,
            "detail": [(g["head_id"], g["number"], g["year"], g["part_ids"])
                       for g in groups]}
