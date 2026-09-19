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


def _contains(outer: tuple[int, int], inner: tuple[int, int]) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1] and outer != inner


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return max(0, hi - lo + 1)


_STOP = {"قانون", "القانون", "مرسوم", "المرسوم", "التشريعي", "التشريعى",
         "الاشتراعي", "رقم", "لعام", "للعام", "لسنة", "عام", "سنة", "في",
         "من", "على", "إلى", "الجمهورية", "العربية", "السورية", "سورية",
         "سوريا", "بشأن", "الخاص", "المتعلق", "القاضي", "القاضى", "وثيقة",
         "قانونية", "نصوص", "مواد", "الصادر", "بالمرسوم", "المادة"}
_COMPATIBLE = {frozenset({"القانون", "المرسوم التشريعي"})}


def _tokens(text: str) -> set[str]:
    """كلمات جوهرية (≥4 أحرف، ليست كلمات صك/وصل) — دليل اشتراك الموضوع."""
    out = set()
    for w in re.findall(r"[\u0621-\u064A]{4,}", text or ""):
        if w in _STOP:
            continue
        out.add(w[2:] if w.startswith("ال") and len(w) > 5 else w)
    return out


def _title_stem(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\d/()\[\]ـ\-–—]+", " ", title or "")).strip()


def _types_compatible(types: set) -> bool:
    ts = {t for t in types if t}
    return len(ts) <= 1 or frozenset(ts) in _COMPATIBLE


def _accept_cluster(members: list[dict]) -> dict | None:
    """يقبل عنقوداً (نفس الرقم، سنة واحدة أو غائبة، أنواع متوافقة) ويعيد
    المجموعة: الرأس = الأوسع تغطيةً (ثم الأصغر مادةً أولى)؛ الباقي أجزاء —
    سواء أكملت الرأس (نطاقات متباعدة) أو كانت محتواةً فيه (شذرات نص
    كامل، قِيس: قانون الجمارك #96 كامل و#177–179 قطعٌ منه). الأجزاء
    المحتواة لا تُكرَّر موادها عند التصدير."""
    if len(members) < 2:
        return None
    members = sorted(members, key=lambda m: (-(m["range"][1] - m["range"][0]),
                                             m["range"][0], m["id"]))
    head, rest = members[0], members[1:]
    years = {m.get("year") for m in members if m.get("year")}
    types = {m.get("doc_type") for m in members if m.get("doc_type")}
    keys = {m.get("identity_key") for m in members if m.get("identity_key")}
    return {
        "head_id": head["id"],
        "part_ids": [m["id"] for m in rest],
        "number": int(head["number"]),
        "year": next(iter(years)) if len(years) == 1 else None,
        "doc_type": head.get("doc_type") or (next(iter(types)) if types else None),
        "identity_key": next(iter(keys)) if len(keys) == 1 else None,
        "ranges": {m["id"]: m["range"] for m in members},
        "contained": [m["id"] for m in rest
                      if _overlap(m["range"], head["range"]) > _MAX_OVERLAP],
    }


def group_parts(docs: list[dict]) -> list[dict]:
    """يعيد قائمة مجموعات {head_id, part_ids, number, year, doc_type, identity_key}.

    docs: [{id, title, doc_type, number, year, identity_key, text}] صكوك نشطة.
    الخطوات (كل رقم على حدة):
      1. عناقيد بالسنة المعلومة (سنتان مختلفتان = صكّان — لا يُخلطان أبداً).
      2. وثيقة بلا سنة تنضم إلى عنقود سنةٍ فقط إذا شاركته كلمةً جوهرية
         (عنواناً أو مطلعاً): «البينات» تجمع #140 مع 359/1947؛ ولا شيء يجمع
         الأحوال الشخصية 59 (بلا سنة) مع المرسوم 59/2008.
      3. ما بقي بلا سنة يتعنقد بتطابق جذع العنوان (المرسوم 30 ×4).
      4. الأنواع: متوافقة إن كانت واحدة أو {القانون، المرسوم التشريعي}.
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
        by_year: dict[int, list[dict]] = {}
        undated: list[dict] = []
        for m in members:
            (by_year.setdefault(m["year"], []) if m.get("year") else undated).append(m)
        # 2) ضمّ بلا-سنة إلى عنقود سنة بدليل كلمة جوهرية
        still: list[dict] = []
        for u in undated:
            u_tok = _tokens((u.get("title") or "") + " " + (u.get("text") or "")[:300])
            joined = None
            for y, cl in by_year.items():
                if not _types_compatible({u.get("doc_type")} | {c.get("doc_type") for c in cl}):
                    continue
                if any(_tokens(c.get("title") or "") & u_tok for c in cl):
                    joined = y
                    break
                # دليل ثانٍ: نطاق مواد الشذرة محتوى كلياً في نطاق نصٍّ كامل
                # مؤرَّخ (قِيس: الجمارك #177 (77–188) داخل #96 (1–298))
                # يشترط: الشذرة ≥ 5 مواد (لا مادة مفردة) والكامل ≥ 20 مادة
                if (u["range"][1] - u["range"][0]) >= 4 and any(
                        _contains(c["range"], u["range"]) and
                        (c["range"][1] - c["range"][0]) >= 20 for c in cl):
                    joined = y
                    break
            (by_year[joined] if joined else still).append(u)
        # 3) بلا سنة: بتطابق جذع العنوان
        by_stem: dict[str, list[dict]] = {}
        for u in still:
            by_stem.setdefault(_title_stem(u.get("title") or ""), []).append(u)
        clusters = list(by_year.values()) + [c for c in by_stem.values() if len(c) > 1]
        for cl in clusters:
            if not _types_compatible({c.get("doc_type") for c in cl}):
                continue
            g = _accept_cluster(cl)
            if g:
                groups.append(g)
    return groups


def link_parts(conn) -> dict:
    """يحسب المجموعات ويكتب documents.part_of للأجزاء (الرأس part_of=NULL).

    يُعاد الحساب من الصفر كل مرة (يُصفَّر العمود أولاً) كي لا تبقى روابط
    يتيمة بعد تحسّن الهوية. يعيد {groups, parts_linked}.
    """
    conn.execute("UPDATE documents SET part_of=NULL")
    rows = conn.execute(
        """SELECT id, title, number, year, identity_key, clean_content
           FROM documents WHERE status='active'
           AND COALESCE(nature,'instrument')='instrument'
           AND number IS NOT NULL"""
    ).fetchall()
    docs = []
    for r in rows:
        dt = (r["identity_key"] or "").split(":")[0] or None
        docs.append({"id": r["id"], "title": r["title"] or "", "doc_type": dt,
                     "number": r["number"], "year": r["year"],
                     "identity_key": r["identity_key"],
                     "text": r["clean_content"] or ""})
    groups = group_parts(docs)
    n = 0
    for g in groups:
        for pid in g["part_ids"]:
            conn.execute("UPDATE documents SET part_of=? WHERE id=?",
                         (g["head_id"], pid))
            n += 1
        # الرأس يرث السنة والهوية من أجزائه إن كان بلا (بلا اختراع: سنة
        # واحدة معلومة في العنقود، ومفتاح هوية واحد)
        if g["year"]:
            conn.execute(
                "UPDATE documents SET year=COALESCE(year,?) WHERE id=?",
                (g["year"], g["head_id"]))
        if g["identity_key"]:
            conn.execute(
                """UPDATE documents SET identity_key=?,
                   identity_confidence='inherited_from_part'
                   WHERE id=? AND identity_key IS NULL""",
                (g["identity_key"], g["head_id"]))
    conn.commit()
    return {"groups": len(groups), "parts_linked": n,
            "detail": [(g["head_id"], g["number"], g["year"], g["part_ids"],
                        g["contained"]) for g in groups]}


def explain_parts(conn) -> list[str]:
    """تشخيص قابل للإرفاق: كل رقم تشترك فيه ≥2 وثيقة، بنطاق مواد كل واحدة
    وسبب عدم التجميع إن وُجد (قِيس 2026-09-19: `parts --link` أعاد 0 على قاعدة
    المالك رغم 4 نسخ للمرسوم 30 — لا يُصلَح ما لا يُرى)."""
    rows = conn.execute(
        """SELECT id, title, number, year, identity_key, clean_content
           FROM documents WHERE status='active'
           AND COALESCE(nature,'instrument')='instrument' AND number IS NOT NULL
           ORDER BY number, id""").fetchall()
    by_num: dict[int, list] = {}
    for r in rows:
        by_num.setdefault(int(r["number"]), []).append(r)
    out = []
    for num, rs in by_num.items():
        if len(rs) < 2:
            continue
        years = {r["year"] for r in rs if r["year"]}
        types = {(r["identity_key"] or "").split(":")[0] for r in rs if r["identity_key"]}
        out.append(f"رقم {num}: {len(rs)} وثيقة | سنوات={sorted(years) or '؟'} "
                   f"| أنواع={sorted(types) or '؟'}")
        for r in rs:
            rng = article_range(r["clean_content"] or "")
            n_art = len(list(ARTICLE_RE.finditer(r["clean_content"] or "")))
            out.append(f"   #{r['id']} نطاق={rng} مواد={n_art} سنة={r['year']} "
                       f"| {(r['title'] or '')[:50]}")
        docs = [{"id": r["id"], "title": r["title"] or "",
                 "doc_type": (r["identity_key"] or "").split(":")[0] or None,
                 "number": r["number"], "year": r["year"],
                 "identity_key": r["identity_key"],
                 "text": r["clean_content"] or ""} for r in rs]
        gs = group_parts(docs)
        if not gs:
            out.append("   ⇒ لا مجموعة: سنوات مختلفة بلا كلمة جوهرية مشتركة، "
                       "أو عناوين مختلفة بلا سنة، أو أنواع غير متوافقة")
        for g in gs:
            out.append(f"   ⇒ مجموعة: رأس #{g['head_id']} سنة={g['year'] or '؟'} "
                       f"أجزاء={g['part_ids']} محتواة={g['contained']}")
    return out or ["لا رقم مشترك بين وثيقتين"]
