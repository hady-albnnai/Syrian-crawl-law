"""المرحلة B-1: قائمة الفجوات المرتّبة — ما يعرف الزاحف أنه ينقصه.

الأولوية بالأدلة: صك يُستهدف بتعديل/إلغاء (law_amendments)، أو مادة منه
تُعدَّل (article_amendments)، أو هو الأم للائحة محصودة (parent_identity)،
أو يُذكر نصياً كثيراً. الوزن: إلغاء 5، تعديل مادة 4، تعديل 3، أم 3،
ذكر 1 لكل مرة. الناتج يغذّي استعلامات البحث بالترتيب.
"""
from collections import defaultdict

import law_identity

WEIGHTS = {"repeal": 5, "article": 4, "amend": 3, "parent": 3, "mention": 1}


def _known(conn) -> set:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT identity_key FROM documents WHERE identity_key IS NOT NULL")}


def missing_targets(conn, limit: int = 100) -> list:
    """[{identity_key, score, why}] مرتبة تنازلياً — صكوك غير موجودة بالقاعدة."""
    known = _known(conn)
    score, why = defaultdict(int), defaultdict(list)

    def hit(key, kind, note):
        if not key or key in known:
            return
        score[key] += WEIGHTS[kind]
        if note not in why[key]:
            why[key].append(note)

    for r in conn.execute("""SELECT a.target_identity, a.action, d.identity_key AS by_key
                             FROM law_amendments a JOIN documents d ON d.id=a.amending_doc_id
                             WHERE d.status='active'"""):
        hit(r[0], r[1], f"{'يُلغيه' if r[1]=='repeal' else 'يعدّله'} {r[2]}")
    tables = {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "article_amendments" in tables:
        for r in conn.execute("""SELECT aa.target_identity, aa.article_number, d.identity_key
                                 FROM article_amendments aa JOIN documents d ON d.id=aa.amending_doc_id"""):
            hit(r[0], "article", f"م{r[1]} تُعدَّل بـ {r[2]}")
    cols = {c[1] for c in conn.execute("PRAGMA table_info(documents)")}
    if "parent_identity" in cols:
        for r in conn.execute("""SELECT parent_identity, title FROM documents
                                 WHERE parent_identity IS NOT NULL AND status='active'"""):
            hit(r[0], "parent", f"أم لـ «{(r[1] or '')[:40]}»")
    for r in conn.execute("SELECT clean_content FROM documents WHERE status='active' AND clean_content IS NOT NULL"):
        for ref in law_identity.extract_law_references(r[0]):
            hit(ref["identity_key"], "mention", "مذكور نصياً")
    # صك موجود بنفس الرقم/السنة لكن بنوع آخر (بنود تسمّي م.ت 115/1953 «قانون»؛
    # قِيس missing2): يُذكر كتلميح ولا يُحذف — الرقم/السنة قد يتكرر بين نوعين.
    by_ny = {}
    for k in known:
        parts = k.split(":")
        if len(parts) == 3:
            by_ny.setdefault((parts[1], parts[2]), []).append(k)
    for k in list(score):
        parts = k.split(":")
        alt = [a for a in by_ny.get((parts[1], parts[2]), []) if a != k]
        if alt:
            why[k].insert(0, f"⚠ موجود بنوع آخر: {alt[0]}")
    out = [{"identity_key": k, "score": s, "why": why[k][:3]} for k, s in score.items()]
    out.sort(key=lambda x: (-x["score"], x["identity_key"]))
    return out[:limit]


def missing_target_queries(conn, limit: int = 40) -> list:
    """استعلامات بحث للفجوات بالترتيب — تُقدَّم على الاستعلامات العامة."""
    qs = []
    for t in missing_targets(conn, limit):
        typ, num, year = t["identity_key"].split(":")
        qs.append(f"{typ} رقم {num} لعام {year} سوريا نص كامل")
    return qs


def format_report(targets: list) -> str:
    lines = [f"# فجوات معلومة: {len(targets)} صكاً غير محصود، مرتبة بالأهمية"]
    for t in targets:
        lines.append(f"{t['score']:>3} | {t['identity_key']} | {'؛ '.join(t['why'])}")
    return "\n".join(lines)
