# -*- coding: utf-8 -*-
"""
precedent_export.py — ف٣ (أ-2): من جداول الاجتهاد في الزاحف إلى حزمة ميزان.

شرط التصدير (docs/PRECEDENTS-RESEARCH-2026-09-21.md §9): `review_status = approved`
و(رقم قرار و(أساس أو تاريخ)) ومبدأ ≥ الحد الأدنى واستشهاد واحد على الأقل.
`--include-pending` يضيف غير المراجَع بوسمه الصريح (لشاشة المراجعة في ميزان، المرحلة ب).

المخرجات في `export/precedents/`:
  precedents.json  — قائمة مبادئ، كل مبدأ مع قراره واستشهاداته وعلاقات العدول ومواده.
  precedents.csv   — نفس الصفوف مسطّحة (لعمود «الاجتهاد» في مكتبة ميزان: `Precedents`
                     court/decisionNumber/baseNumber/decidedAt/principle/body/topic/source).
  manifest.json    — الأعداد + sha256 للملفين.

الاعتماد الجماعي (`approve_bulk`) قرار بشري صريح من المالك عبر الأمر — لا يحدث تلقائياً.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from precedent_parser import MIN_PRINCIPLE, MIN_PRINCIPLE_TITLED

COURT_LABEL = {
    "نقض": "محكمة النقض", "هيئة_عامة_نقض": "الهيئة العامة لمحكمة النقض",
    "توحيد_مبادئ": "دائرة توحيد المبادئ في مجلس الدولة", "ادارية_عليا": "المحكمة الإدارية العليا",
    "دستورية": "المحكمة الدستورية العليا", "استئناف": "محكمة الاستئناف",
}
RELATION_LABEL = {"عدول": "عُدل عنه بـ", "تأكيد": "أُكِّد بـ", "إحالة": "أُحيل إليه في", "تعارض": "يتعارض مع"}


def court_display(court: str, chamber_raw: str | None) -> str:
    base = COURT_LABEL.get(court or "", court or "")
    if chamber_raw and court == "نقض":
        return f"{base} — الغرفة {chamber_raw}"
    return base


def _ref(d: dict) -> str:
    parts = []
    if d.get("decision_number"):
        parts.append(f"قرار {d['decision_number']}")
    if d.get("basis_number"):
        parts.append(f"أساس {d['basis_number']}")
    if d.get("decision_date"):
        y, m, dd = d["decision_date"].split("-")
        parts.append(f"تاريخ {int(dd)}/{int(m)}/{y}")
    elif d.get("decision_year"):
        parts.append(f"لعام {d['decision_year']}")
    return " ".join(parts)


def _source_line(cits: list[dict]) -> str:
    """«مجلة المحامون 2010 العدد 1-2 القاعدة 52» أو اسم الموقع."""
    for c in cits:
        if c.get("publication"):
            s = f"مجلة {c['publication']}"
            if c.get("pub_year"):
                s += f" {c['pub_year']}"
            if c.get("pub_issue"):
                s += f" العدد {c['pub_issue']}"
            if c.get("rule_number"):
                s += f" القاعدة {c['rule_number']}"
            return s
    sites = sorted({c["source_site"] for c in cits if c.get("source_site")})
    return "، ".join(sites)


def exportable_rows(conn, include_pending: bool = False) -> list[dict]:
    status = "('approved','pending')" if include_pending else "('approved')"
    q = f"""
    SELECT p.id AS principle_id, p.title_keywords, p.text, p.review_status AS p_status,
           d.id AS decision_id, d.court, d.division, d.chamber_raw, d.case_kind, d.decision_number,
           d.decision_year, d.basis_number, d.basis_year, d.decision_date, d.identity_key,
           d.authority_rank, d.review_status AS d_status
    FROM principles p JOIN decisions d ON d.id = p.decision_id
    WHERE d.review_status IN {status}
      AND d.decision_number IS NOT NULL AND d.decision_number <> ''
      AND ((d.basis_number IS NOT NULL AND d.basis_number <> '') OR d.decision_date IS NOT NULL)
      AND EXISTS (SELECT 1 FROM citations c WHERE c.decision_id = d.id)
    ORDER BY d.authority_rank, d.decision_year DESC, d.id, p.id"""
    conn.row_factory = None
    cols = None
    out = []
    cur = conn.execute(q)
    cols = [c[0] for c in cur.description]
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        limit = MIN_PRINCIPLE_TITLED if d["title_keywords"] else MIN_PRINCIPLE
        if len((d["text"] or "").strip()) < limit:
            continue
        cits = [dict(zip(("source_site", "source_url", "snapshot_ts", "publication", "pub_year",
                          "pub_issue", "pub_page", "rule_number", "parse_confidence"), x))
                for x in conn.execute(
                    "SELECT source_site,source_url,snapshot_ts,publication,pub_year,pub_issue,pub_page,"
                    "rule_number,parse_confidence FROM citations WHERE decision_id=? ORDER BY id",
                    (d["decision_id"],)).fetchall()]
        arts = [dict(zip(("law_alias", "article_number", "confidence"), x)) for x in conn.execute(
            "SELECT law_alias,article_number,confidence FROM principle_articles WHERE principle_id=?",
            (d["principle_id"],)).fetchall()]
        rels = []
        for rel, other_key, other_no, other_basis, other_date, direction in conn.execute(
                "SELECT r.relation, o.identity_key, o.decision_number, o.basis_number, o.decision_date, 'out'"
                " FROM decision_relations r JOIN decisions o ON o.id=r.to_decision_id WHERE r.from_decision_id=?"
                " UNION ALL "
                "SELECT r.relation, o.identity_key, o.decision_number, o.basis_number, o.decision_date, 'in'"
                " FROM decision_relations r JOIN decisions o ON o.id=r.from_decision_id WHERE r.to_decision_id=?",
                (d["decision_id"], d["decision_id"])).fetchall():
            rels.append({"relation": rel, "direction": direction, "identity_key": other_key,
                         "decision_number": other_no, "basis_number": other_basis, "decision_date": other_date})
        overruled = any(r["relation"] == "عدول" and r["direction"] == "in" for r in rels)
        d.update({"citations": cits, "articles": arts, "relations": rels, "overruled": overruled,
                  "court_display": court_display(d["court"], d["chamber_raw"]),
                  "reference": _ref(d), "source_line": _source_line(cits),
                  "review_status": "approved" if d["d_status"] == "approved" and d["p_status"] == "approved" else "pending"})
        out.append(d)
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


CSV_COLUMNS = ["principle_id", "identity_key", "court", "court_display", "chamber_raw", "division", "case_kind",
               "decision_number", "decision_year", "basis_number", "decision_date", "authority_rank",
               "title_keywords", "principle", "reference", "source_line", "source_urls", "articles",
               "overruled", "review_status"]


def build_package(conn, out_dir="export/precedents", include_pending: bool = False) -> dict:
    rows = exportable_rows(conn, include_pending=include_pending)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js = out / "precedents.json"
    js.write_text(json.dumps({"schema_version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"),
                              "include_pending": include_pending, "count": len(rows), "items": rows},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    cs = out / "precedents.csv"
    with open(cs, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        for d in rows:
            w.writerow({
                "principle_id": d["principle_id"], "identity_key": d["identity_key"], "court": d["court"],
                "court_display": d["court_display"], "chamber_raw": d["chamber_raw"] or "",
                "division": d["division"] or "", "case_kind": d["case_kind"] or "",
                "decision_number": d["decision_number"], "decision_year": d["decision_year"] or "",
                "basis_number": d["basis_number"] or "", "decision_date": d["decision_date"] or "",
                "authority_rank": d["authority_rank"], "title_keywords": d["title_keywords"] or "",
                "principle": d["text"].strip(), "reference": d["reference"], "source_line": d["source_line"],
                "source_urls": " | ".join(sorted({c["source_url"] for c in d["citations"] if c["source_url"]})),
                "articles": " | ".join(f"م{a['article_number']} {a['law_alias'] or ''}".strip() for a in d["articles"]),
                "overruled": int(d["overruled"]), "review_status": d["review_status"]})
    by_court: dict[str, int] = {}
    for d in rows:
        by_court[d["court"]] = by_court.get(d["court"], 0) + 1
    manifest = {"schema_version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"),
                "count": len(rows), "approved": sum(d["review_status"] == "approved" for d in rows),
                "pending": sum(d["review_status"] == "pending" for d in rows),
                "overruled": sum(d["overruled"] for d in rows), "by_court": by_court,
                "files": {"precedents.json": _sha(js), "precedents.csv": _sha(cs)}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest["out_dir"] = str(out)
    return manifest


def approve_bulk(conn, min_confidence: float = 0.85, multi_source_only: bool = False,
                 courts: tuple[str, ...] | None = None, dry_run: bool = False) -> dict:
    """اعتماد جماعي بقرار المالك: قرارات pending تحقق العتبة (أعلى ثقة تحليل بين استشهاداتها ≥ الحد،
    واختيارياً مصدران مستقلان على الأقل / جهات محددة). يعتمد القرار ومبادئه معاً."""
    q = """SELECT d.id FROM decisions d WHERE d.review_status='pending'
           AND d.decision_number IS NOT NULL AND d.decision_number <> ''
           AND ((d.basis_number IS NOT NULL AND d.basis_number <> '') OR d.decision_date IS NOT NULL)
           AND (SELECT MAX(parse_confidence) FROM citations c WHERE c.decision_id=d.id) >= ?
           AND EXISTS (SELECT 1 FROM principles p WHERE p.decision_id=d.id)"""
    args: list = [min_confidence]
    if multi_source_only:
        q += " AND (SELECT COUNT(DISTINCT source_url) FROM citations c WHERE c.decision_id=d.id) >= 2"
    if courts:
        q += f" AND d.court IN ({','.join('?' * len(courts))})"
        args += list(courts)
    ids = [r[0] for r in conn.execute(q, args).fetchall()]
    if not dry_run and ids:
        now = datetime.now().isoformat(timespec="seconds")
        for i in ids:
            conn.execute("UPDATE decisions SET review_status='approved', reviewed_by='bulk', reviewed_at=? WHERE id=?", (now, i))
            conn.execute("UPDATE principles SET review_status='approved' WHERE decision_id=? AND review_status='pending'", (i,))
        conn.commit()
    return {"matched": len(ids), "approved": 0 if dry_run else len(ids), "dry_run": dry_run}
