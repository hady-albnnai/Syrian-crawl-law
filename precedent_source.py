"""precedent_source.py — محرك جمع الاجتهادات (ف٣ / أ-2) — mohamah.net أولاً.

المسار: خريطة الموقع ⇒ ترشيح صفحات الاجتهاد السوري ⇒ جلب مؤدَّب (fetcher.fetch:
robots + تأخير) ⇒ نص المقال ⇒ `precedent_parser.parse_text` ⇒ كتابة في
decisions/principles/citations/principle_articles بحالة `pending` (المراجعة
البشرية إلزامية — الميثاق §4 ف٣؛ لا اعتماد آلي مهما كانت الثقة).

قرارات التصميم (docs/PRECEDENTS-RESEARCH-2026-09-21.md §9):
- هوية القرار = `identity_key` من المحلل؛ ظهور ثانٍ لنفس القرار = استشهاد جديد فقط.
- المبدأ يُكرَّر بالبصمة (`text_sha256`): نفس النص من مصدرين = سجل مبدأ واحد + استشهادان.
- ما لا هوية له (بلا رقم قرار، أو بلا أساس وتاريخ معاً) لا يدخل `decisions` أصلاً؛
  يُعدّ «منقولاً بلا إسناد» ويُحصى في التقرير فقط.
- الجلب الشبكي معزول في `http_get` (حقن) حتى تُختبر الوحدة بلا شبكة.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from logging_setup import get_log
from precedent_parser import (Citation, parse_text, extract_article_refs,
                              extract_overrulings, authority_rank, _principle_ok)

log = get_log(__name__)

MOHAMAH_SITEMAP_INDEX = "https://www.mohamah.net/law/sitemap_index.xml"
SOURCE_SITE = "mohamah.net"
# الترشيح من الرابط (المفكوك): سوري + مفردة اجتهاد — قِيس 2026-09-21: 202/41,114
_URL_SY = re.compile(r"سور")
_URL_IJ = re.compile(r"اجتهاد|نقض|مبادئ|مبدأ|هيئة-العامة|إدارية-العليا|الادارية-العليا|مخاصمة")
# استبعاد صريح: مواد تشريعية/قوالب (لا اجتهاد فيها) — الرابط فقط
_URL_EXCLUDE = re.compile(r"نصوص-و-مواد|نموذج|صيغة|صيغ-")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def _quote_url(u: str) -> str:
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc, quote(unquote(p.path)), p.query, ""))


# صفحات بلا كلمة «سورية» في الرابط لكنها سورية بالعنوان («اجتهادات-الهيئة-العامة-لمحكمة-النقض-ا-2»)
_URL_SY_IMPLICIT = re.compile(r"الهيئة-العامة-لمحكمة-النقض|المحكمة-الإدارية-العليا|المحكمة-الادارية-العليا")


# الوضع الواسع (--broad): كل صفحة اجتهادية العنوان غير أجنبية — المحلل يحسم (≥3 بهوية)
_URL_BROAD = re.compile(r"اجتهاد|نقض|هيئة-العامة|مبادئ|أحكام|احكام|قرارات")
_URL_FOREIGN = re.compile(r"مصر|لبنان|أردن|الاردن|مغرب|كويت|إمارات|امارات|عمان|فلسطين|عراق|جزائر|تونس|سعود|بحرين|قطر|ليبي|يمن|سودان|فرنس")


def is_broad_candidate_url(url: str) -> bool:
    u = unquote(url)
    if _URL_EXCLUDE.search(u) or _URL_FOREIGN.search(u):
        return False
    return bool(_URL_BROAD.search(u))


def is_precedent_url(url: str) -> bool:
    u = unquote(url)
    if _URL_EXCLUDE.search(u):
        return False
    return bool((_URL_SY.search(u) and _URL_IJ.search(u)) or (_URL_SY_IMPLICIT.search(u) and "مصر" not in u))


def sitemap_precedent_urls(index_xml: str, http_get, broad: bool = False) -> list[str]:
    """يقرأ فهرس الخرائط ثم كل خريطة مقالات ويعيد روابط الاجتهاد السوري (بلا تكرار)."""
    pred = is_broad_candidate_url if broad else is_precedent_url
    out, seen = [], set()
    for sm in _LOC_RE.findall(index_xml or ""):
        if "post-sitemap" not in sm:
            continue
        xml = http_get(sm)
        if not xml:
            continue
        for loc in _LOC_RE.findall(xml):
            if pred(loc):
                q = _quote_url(loc)
                if q not in seen:
                    seen.add(q)
                    out.append(q)
    return out


# ------------------------------------------------------------- نص المقال
_BODY_RES = [
    re.compile(r'<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>(.*?)(?:<footer|<div[^>]+class="[^"]*(?:post-tags|entry-footer|sharedaddy)|</article>)', re.S),
    re.compile(r"<article[^>]*>(.*?)</article>", re.S),
]


def article_text(page_html: str) -> str:
    """HTML ⇒ نص بأسطر تحفظ حدود الفقرات (المحلل يعتمد على الأسطر)."""
    body = None
    for rx in _BODY_RES:
        m = rx.search(page_html or "")
        if m:
            body = m.group(1)
            break
    if body is None:
        body = page_html or ""
    body = re.sub(r"<(script|style|noscript)\b.*?</\1>", "", body, flags=re.S | re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|blockquote)>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", "", body)
    body = _html.unescape(body)
    body = body.replace("\r", "")
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    # ذيل الصفحة القياسي في mohamah («شارك المقالة» / «إقرأ أيضا») — يُقصّ
    for marker in ("شارك المقالة", "إقرأ أيضا", "اقرأ أيضا"):
        i = body.find(marker)
        if i > 200:
            body = body[:i]
    return body.strip()


def title_of(page_html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html or "", re.S)
    t = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------- الكتابة في القاعدة
def _sha(s: str) -> str:
    return hashlib.sha256((s or "").strip().encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_citation(conn, c: Citation, source_url: str, snapshot_ts: str | None = None,
                    source_site: str = SOURCE_SITE) -> dict:
    """يكتب استشهاداً واحداً. يعيد {decision_id, principle_id, new_decision, new_principle}
    أو {'skipped': 'no_identity'} إن نقصت الهوية."""
    key = c.identity_key()
    if not key:
        return {"skipped": "no_identity"}
    now = _now()
    row = conn.execute("SELECT id FROM decisions WHERE identity_key=?", (key,)).fetchone()
    new_dec = row is None
    if new_dec:
        cur = conn.execute(
            "INSERT INTO decisions(court,division,chamber_raw,case_kind,decision_number,decision_year,"
            "basis_number,basis_year,appeal_number,decision_date,identity_key,authority_rank,"
            "review_status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)",
            (c.court, c.division, c.chamber_raw, c.case_kind, c.decision_number, c.decision_year,
             c.basis_number, c.basis_year, c.appeal_number, c.decision_date, key,
             authority_rank(c), now))
        dec_id = cur.lastrowid
    else:
        dec_id = row[0]
        # إكمال حقول فارغة فقط (لا كتابة فوق ما وُجد)
        for col, val in (("division", c.division), ("chamber_raw", c.chamber_raw),
                         ("case_kind", c.case_kind), ("basis_year", c.basis_year),
                         ("decision_date", c.decision_date)):
            if val:
                conn.execute(f"UPDATE decisions SET {col}=? WHERE id=? AND ({col} IS NULL OR {col}='')",
                             (val, dec_id))

    prin_id, new_prin = None, False
    if _principle_ok(c):
        h = _sha(c.principle_text)
        r = conn.execute("SELECT id FROM principles WHERE text_sha256=?", (h,)).fetchone()
        if r:
            prin_id = r[0]
        else:
            cur = conn.execute(
                "INSERT INTO principles(decision_id,title_keywords,text,text_sha256,review_status,created_at)"
                " VALUES (?,?,?,?,'pending',?)",
                (dec_id, c.title_keywords, c.principle_text.strip(), h, now))
            prin_id, new_prin = cur.lastrowid, True
            for ref in extract_article_refs(c.principle_text):
                conn.execute(
                    "INSERT OR IGNORE INTO principle_articles(principle_id,law_alias,article_number,"
                    "article_numbering_scheme,match_method,confidence) VALUES (?,?,?,'as_cited','regex',?)",
                    (prin_id, ref["law_alias"], ref["article_number"], ref["confidence"]))

    conn.execute(
        "INSERT OR IGNORE INTO citations(decision_id,principle_id,source_site,source_url,snapshot_ts,"
        "publication,pub_year,pub_issue,pub_page,rule_number,citation_raw,parse_confidence,scraped_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (dec_id, prin_id, source_site, source_url, snapshot_ts, c.publication, c.pub_year,
         c.pub_issue, c.pub_page, c.rule_number, c.citation_raw, c.confidence, now))
    return {"decision_id": dec_id, "principle_id": prin_id,
            "new_decision": new_dec, "new_principle": new_prin}


def ingest_page(conn, url: str, page_html: str, source_site: str = SOURCE_SITE,
                snapshot_ts: str | None = None, text_fn=None) -> dict:
    """`text_fn(html) -> str` يُحقن لمصادر أخرى (المنتديات)؛ الافتراضي مقالة mohamah."""
    text = (text_fn or article_text)(page_html)
    cs = parse_text(text)
    st = {"url": url, "citations": len(cs), "new_decisions": 0, "new_principles": 0,
          "unsourced": 0, "written": 0}
    for c in cs:
        r = upsert_citation(conn, c, url, snapshot_ts, source_site)
        if r.get("skipped"):
            st["unsourced"] += 1
            continue
        st["written"] += 1
        st["new_decisions"] += int(r["new_decision"])
        st["new_principles"] += int(r["new_principle"])
    st["relations"] = write_overrulings(conn, text, cs)
    conn.commit()
    return st


def _find_decision_id(conn, target: Citation) -> int | None:
    """يطابق هدف العدول بقرار موجود: بالهوية الكاملة، أو رقم القرار + الأساس، أو التاريخ + الرقم."""
    key = target.identity_key()
    if key:
        r = conn.execute("SELECT id FROM decisions WHERE identity_key=?", (key,)).fetchone()
        if r:
            return r[0]
    if target.decision_number and target.basis_number:
        r = conn.execute("SELECT id FROM decisions WHERE court='نقض' AND decision_number=? AND basis_number=?"
                         + (" AND decision_date=?" if target.decision_date else ""),
                         (target.decision_number, target.basis_number)
                         + ((target.decision_date,) if target.decision_date else ())).fetchone()
        if r:
            return r[0]
    if target.decision_date:
        q = "SELECT id FROM decisions WHERE decision_date=?"
        args: tuple = (target.decision_date,)
        if target.decision_number:
            q += " AND decision_number=?"
            args += (target.decision_number,)
        rows = conn.execute(q, args).fetchall()
        if len(rows) == 1:
            return rows[0][0]
    return None


def _ensure_stub_decision(conn, target: Citation) -> int | None:
    """قرار مُعدول عنه غير موجود بعد: يُنشأ صفاً هيكلياً (pending) إن حمل هوية كافية
    (رقم قرار + أساس، أو تاريخ + رقم) كي تُحفظ العلاقة ويُستكمل لاحقاً من مصدر آخر."""
    if not ((target.decision_number and target.basis_number)
            or (target.decision_date and target.decision_number)):
        return None
    key = target.identity_key() or f"نقض|{target.decision_number}|{(target.decision_date or '')[:4] or '?'}|{target.basis_number or ''}"
    r = conn.execute("SELECT id FROM decisions WHERE identity_key=?", (key,)).fetchone()
    if r:
        return r[0]
    cur = conn.execute(
        "INSERT INTO decisions(court,division,case_kind,decision_number,decision_year,basis_number,"
        "decision_date,identity_key,authority_rank,review_status,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'pending',?)",
        ("نقض", target.division, target.case_kind, target.decision_number,
         int((target.decision_date or "0000")[:4]) or None, target.basis_number,
         target.decision_date, key, authority_rank(target), _now()))
    return cur.lastrowid


def write_overrulings(conn, text: str, cs: list[Citation]) -> int:
    """يكتب علاقات «عدول» من نص هيئة عامة إلى `decision_relations`.

    المصدر (from) = قرار الهيئة العامة الوحيد في الصفحة (وإلا لا تُكتب علاقة —
    لا تخمين)؛ الهدف (to) = القرار المعدول عنه، يُطابَق أو يُنشأ هيكلياً."""
    targets = extract_overrulings(text)
    if not targets:
        return 0
    srcs = [c for c in cs if c.court in ("هيئة_عامة_نقض", "توحيد_مبادئ") and c.identity_key()]
    if len(srcs) != 1:
        return 0
    from_id = conn.execute("SELECT id FROM decisions WHERE identity_key=?", (srcs[0].identity_key(),)).fetchone()
    if not from_id:
        return 0
    n = 0
    for tg in targets:
        to_id = _find_decision_id(conn, tg) or _ensure_stub_decision(conn, tg)
        if not to_id or to_id == from_id[0]:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO decision_relations(from_decision_id,to_decision_id,relation,evidence_text,created_at)"
            " VALUES (?,?,'عدول',?,?)", (from_id[0], to_id, tg.citation_raw[:300], _now()))
        n += cur.rowcount
    return n


def already_ingested(conn, url: str) -> bool:
    return conn.execute("SELECT 1 FROM citations WHERE source_url=? LIMIT 1", (url,)).fetchone() is not None


def harvest_mohamah(conn, http_get, limit: int | None = None, dry_run: bool = False,
                    skip_done: bool = True, broad: bool = False, min_hits: int = 3) -> dict:
    """الدورة الكاملة. `http_get(url) -> str|None` يُحقن (fetcher.fetch في الإنتاج).
    broad=True: مرشّح روابط واسع (~2,200 صفحة) والمحلل يحسم — صفحة بلا ≥min_hits
    استشهاداً بهوية تُهمل ولا تُكتب."""
    idx = http_get(MOHAMAH_SITEMAP_INDEX)
    urls = sitemap_precedent_urls(idx or "", http_get, broad=broad)
    report = {"candidate_urls": len(urls), "fetched": 0, "skipped_done": 0, "failed": 0,
              "citations": 0, "new_decisions": 0, "new_principles": 0, "unsourced": 0,
              "pages": []}
    done = 0
    for u in urls:
        if limit is not None and done >= limit:
            break
        if skip_done and not dry_run and already_ingested(conn, u):
            report["skipped_done"] += 1
            continue
        page = http_get(u)
        done += 1
        if not page:
            report["failed"] += 1
            continue
        report["fetched"] += 1
        if dry_run:
            cs = parse_text(article_text(page))
            st = {"url": u, "citations": len(cs),
                  "exportable": sum(c.is_exportable() for c in cs),
                  "unsourced": sum(1 for c in cs if not c.identity_key())}
            report["citations"] += st["citations"]
            report["unsourced"] += st["unsourced"]
        else:
            if broad:
                probe = [c for c in parse_text(article_text(page)) if c.is_exportable()]
                if len(probe) < min_hits:
                    report["rejected_broad"] = report.get("rejected_broad", 0) + 1
                    continue
            st = ingest_page(conn, u, page)
            for k in ("citations", "new_decisions", "new_principles", "unsourced"):
                report[k] += st[k]
        report["pages"].append(st)
    return report


def stats(conn) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "decisions": q("SELECT COUNT(*) FROM decisions"),
        "principles": q("SELECT COUNT(*) FROM principles"),
        "citations": q("SELECT COUNT(*) FROM citations"),
        "pending": q("SELECT COUNT(*) FROM decisions WHERE review_status='pending'"),
        "approved": q("SELECT COUNT(*) FROM decisions WHERE review_status='approved'"),
        "multi_source": q("SELECT COUNT(*) FROM (SELECT decision_id FROM citations GROUP BY decision_id HAVING COUNT(DISTINCT source_url)>1)"),
        "by_court": dict(conn.execute("SELECT court, COUNT(*) FROM decisions GROUP BY court").fetchall()),
        "article_links": q("SELECT COUNT(*) FROM principle_articles"),
        "relations": q("SELECT COUNT(*) FROM decision_relations"),
    }
