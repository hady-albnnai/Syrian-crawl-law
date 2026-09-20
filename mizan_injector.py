# -*- coding: utf-8 -*-
"""mizan_injector.py — حقن الحزمة في جذر ميزان: دمج لا تغطية، وإيصالية.

علة وُجدت (مقيسة، لا مستنتَجة): كان «نسخ الحزمة إلى مجلد ميزان» في شاشة
الحزمة يكتب فهرسنا فوق فهرسهم. فهرسهم فيه 29 صفاً، منها 12 صفاً `pdf/…` لا
يولّدها الزاحف؛ ومستورد ميزان يستهلك **الفهرس** وحده
(`legal_library_repository.dart:72`) ⇒ النسخ الأعمى كان يُيتّم تلك الـ12
(ملفاتها تبقى على القرص بلا صفّ يستوردها). لذا الحقن هنا **دمج**: صفوفنا
تُضاف/تُحدَّث، وما لا يعنينا من فهرسهم يبقى كما هو.

ثلاث حقائق من كود ميزان فُرضت على التصميم:

1. `importLegalFilesFromContent({String root = '.'})` — الجذر هو مجلد تشغيل
   البرنامج (لا `StorageLocationService.activeRoot`)، و`local_path` في الفهرس
   كامل من الجذر (`content/legal_library/laws_decrees/…`). لذلك يطلب هذا
   المسار **جذر المستودع**، لا مجلد المحتوى.
2. `bootstrap()` يستورد فقط إذا كان عدد المكتبة `< 8`
   (`legal_library_models.dart:375`)، ولا زرّ يدوي يستدعي
   `loadRealLegalFiles()` ⇒ الملفات وحدها لا تكفي؛ الإيصالية تُخبر المستخدم
   بما على ميزان أن يفعله.
3. تكرار الاستيراد محكوم بمطابقة `filePath`
   (`csv_legal_library_importer.dart:114`) ⇒ ملف **تغيّر بنفس المسار**
   يتخطّاه ميزان بصمت. يكشف الحقن تلك الصفوف ويكتب `mizan_update_plan.json`
   بدل أن يدّعي أنها حُقنت.

ولا يلمس هذا الملف قاعدة بيانات ميزان إطلاقاً (WAL + `PRAGMA foreign_keys=ON`
+ 62 جدولاً — الكتابة الخارجية مخاطرة قفل/فساد، وبوابتهم الحمراء مقصودة).
الحقن ملفاتٌ وفهرسٌ فقط، ثم يقول بصدق ماذا سيحدث عند الاستيراد.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from logging_setup import get_log

log = get_log(__name__)

LIB_SUBPATH = ("content", "legal_library", "laws_decrees")
INDEX_NAME = "laws_decrees_index.csv"
MANIFEST_NAME = "mizan_package_manifest.json"
RECEIPT_NAME = "mizan_injection_receipt.json"
UPDATE_PLAN_NAME = "mizan_update_plan.json"
BACKUP_DIRNAME = ".mizan_injection_backup"


class GateError(RuntimeError):
    """الحقن مرفوض لأن بوابة الحزمة حمراء — يُصرَّح صراحةً بـallow_red_gate."""

    def __init__(self, p: dict):
        self.plan = p
        super().__init__(
            "البوابة حمراء في الحزمة — الحقن يعني أن ميزان سيتخطى صفوفًا. "
            "فحوص راسبة: " + "؛ ".join(p["gate_failed"]) +
            " — للتجاوز الصريح استخدم --force")


# ─────────────────────────────────────────────── أدوات المسارات
def default_mizan_root() -> str:
    """المرحلة C: جذر التخزين الفعّال لميزان على هذا الجهاز —
    `Documents/LawOffice` (StorageLocationService.defaultRoot). ميزان صار
    يقرأ `content/` من هناك أولاً، فالحقن إليه لا يحتاج مستودع المصدر.
    يُعاد فارغاً إن لم يوجد المجلد (لا نخترع جذراً)."""
    import os
    home = Path(os.path.expanduser("~"))
    for docs in (home / "Documents", home / "OneDrive" / "Documents", home / "المستندات"):
        cand = docs / "LawOffice"
        if cand.is_dir():
            return str(cand)
    return ""


def library_dir(mizan_root) -> Path:
    """مجلد المحتوى في ميزان (حيث الفهرس ومجلد markdown)."""
    return Path(mizan_root).joinpath(*LIB_SUBPATH)


def _dest_path(mizan_root: Path, local_path: str) -> Path:
    """الوجهة الفعلية لملف: `File('$root/$local_path')` كما في ميزان."""
    return mizan_root / (local_path or "")


def _pkg_sibling(pkg: Path, local_path: str, suffix: str) -> Path | None:
    """نظير الملف داخل الحزمة (`.md`/`.json` جنباً إلى جنب في `markdown/`)."""
    name = Path(local_path).name
    for cand in (pkg / "markdown" / Path(name).with_suffix(suffix),
                 pkg / Path(name).with_suffix(suffix)):
        if cand.exists():
            return cand
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_rows(index_path: Path) -> list[dict]:
    if not index_path.exists():
        return []
    with open(index_path, encoding="utf-8-sig", newline="") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()}
                for r in csv.DictReader(f)]


def _write_rows(index_path: Path, rows: list[dict]) -> None:
    """فهرس 14 عموداً، UTF-8+BOM، LF — نفس عقد الحزمة حرفياً."""
    from exporter import COLUMNS
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


# ─────────────────────────────────────────────── الخطة (لا كتابة)
def plan(package_dir, mizan_root, *, replace_index: bool = False) -> dict:
    """يحسب كل ما سيحدث — بلا كتابة بايت واحد. صالح للمعاينة وللتأكيد."""
    import verify_package

    src = Path(package_dir)
    # قيس على ميدان ويندوز: خطأ طباعة بمسار الحزمة كان يردّ «ولِّد الحزمة أولاً»
    # وهو محقّق منها — فتضيع الدقيقة التالية على تشخيص غلط. المجلد المفقود
    # والمجلد الفاضي حالتان مختلفتان، وكل وحدة إلها سبب مختلف.
    if not src.exists():
        raise FileNotFoundError(
            f"مسار الحزمة غير موجود: {src} — راجع حروف المسار، أو ولِّد الحزمة "
            f"أولاً (زر «توليد الحزمة» / python -m cli export)")
    if not (src / INDEX_NAME).exists():
        raise FileNotFoundError(
            f"لا فهرس في {src} — المجلد موجود لكنه بلا {INDEX_NAME}؛ ولِّد "
            f"الحزمة أولاً (زر «توليد الحزمة»)")
    root = Path(mizan_root)
    if not root.exists():
        raise FileNotFoundError(
            f"جذر ميزان غير موجود: {root} — يجب أن يكون مجلد المستودع الذي "
            f"يحتوي content/legal_library/")
    dest = library_dir(root)

    checks = verify_package.check_package(src)
    gate_failed = [m for m, ok in checks if not ok]

    ours = _read_rows(src / INDEX_NAME)
    theirs = _read_rows(dest / INDEX_NAME)
    by_id = {r.get("id"): r for r in theirs}
    by_path = {(r.get("local_path") or ""): r for r in theirs}

    added, identical, updated = [], [], []
    foreign_rows, missing_theirs = [], []
    ours_paths = {r.get("local_path") for r in ours}
    for r in ours:
        old = by_id.get(r.get("id")) or by_path.get(r.get("local_path") or "")
        if old is None:
            added.append(r)
        elif (old.get("sha256") or "").lower() == (r.get("sha256") or "").lower():
            identical.append(r)
        else:
            updated.append(r)
    for r in theirs:
        if (r.get("local_path") or "") in ours_paths or r.get("id") in {
                x.get("id") for x in ours}:
            continue
        (foreign_rows if _dest_path(root, r.get("local_path") or "").exists()
         else missing_theirs).append(r)

    files = 0
    for r in ours:
        for suf in (".md", ".json"):
            if _pkg_sibling(src, r.get("local_path") or "", suf):
                files += 1

    warnings = []
    if not ours:
        warnings.append(
            "الحزمة بلا صفوف — لا شيء يُحقن: فهرس الحزمة فارغ، وأي كتابة هنا "
            "ستكون إعادة كتابة لفهرس ميزان بلا مقابل")
    if updated:
        warnings.append(
            f"{len(updated)} وثيقة تغيّر نصّها ومسارها مسجّل عند ميزان: الملفات "
            "ستُحدَّث على القرص، لكن المستورد **سيتخطاها** (مطابقة filePath) — "
            f"لا بدّ من «استبدال» عنده؛ القائمة في {UPDATE_PLAN_NAME}")
    if gate_failed:
        warnings.append(
            f"بوابة الحزمة حمراء ({len(gate_failed)} فحص) — هذه الحزمة ستُتخطى "
            "صفوفها في ميزان")
    if missing_theirs:
        warnings.append(
            f"{len(missing_theirs)} صفاً في فهرسهم ملفه مفقود أصلاً — بقي كما "
            "هو، لا نصلحه من هنا")
    if replace_index and foreign_rows:
        warnings.append(
            f"استبدال الفهرس تخلّى عن {len(foreign_rows)} صفاً من فهرسهم "
            "(ملفاتهم تبقى يتيمة)")

    return {
        "package_dir": str(src), "mizan_root": str(root), "dest": str(dest),
        "replace_index": bool(replace_index),
        "gate_green": not gate_failed, "gate_failed": gate_failed,
        "rows_ours": len(ours), "rows_theirs": len(theirs),
        "added": [r.get("id") for r in added],
        "identical": [r.get("id") for r in identical],
        "updated_same_path": [r.get("id") for r in updated],
        "kept_foreign": [r.get("id") for r in foreign_rows],
        "missing_theirs": [r.get("id") for r in missing_theirs],
        "index_rows_after": (len(ours) if replace_index
                             else len(ours) + len(foreign_rows)),
        "files_to_write": files, "warnings": warnings,
        "_updated_rows": updated,
    }


# ─────────────────────────────────────────────── التنفيذ
def apply(package_dir, mizan_root, *, replace_index: bool = False,
          allow_red_gate: bool = False, prefetch: dict | None = None) -> dict:
    """يكتب الملفات + الفهرس المدموج + الإيصالية. لا يلمس قاعدة بياناتهم."""
    p = prefetch or plan(package_dir, mizan_root, replace_index=replace_index)
    if not p["gate_green"] and not allow_red_gate:
        raise GateError(p)

    src = Path(p["package_dir"])
    root = Path(p["mizan_root"])
    dest = Path(p["dest"])
    dest.mkdir(parents=True, exist_ok=True)

    # ١) أمان: نسخة مما سنبدّله (فهرسهم + ملفات موجودة ستُستبدل)
    backup = root / BACKUP_DIRNAME / datetime.now().strftime("%Y%m%dT%H%M%S")
    backed_up: list[str] = []
    if (dest / INDEX_NAME).exists():
        (backup / "content" / "legal_library" / "laws_decrees").mkdir(
            parents=True, exist_ok=True)
        shutil.copy2(dest / INDEX_NAME, backup / INDEX_NAME)
        backed_up.append(INDEX_NAME)

    ours = _read_rows(src / INDEX_NAME)
    updated_ids = {r.get("id") for r in p["_updated_rows"]}
    written = 0
    for r in ours:
        lp = r.get("local_path") or ""
        for suf in (".md", ".json"):
            s = _pkg_sibling(src, lp, suf)
            if s is None:
                continue
            d = _dest_path(root, str(Path(lp).with_suffix(suf)))
            if d.exists() and (r.get("id") in updated_ids or suf == ".md"):
                rel = d.relative_to(root)
                (backup / rel.parent).mkdir(parents=True, exist_ok=True)
                if not (backup / rel).exists():
                    shutil.copy2(d, backup / rel)
                    if suf == ".md":
                        backed_up.append(str(rel))
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            written += 1

    # ٢) الفهرس: دمج (افتراضي) أو استبدال صريح
    final_rows = ours if replace_index else _merge(_read_rows(dest / INDEX_NAME),
                                                   ours)
    _write_rows(dest / INDEX_NAME, final_rows)
    if (src / MANIFEST_NAME).exists():
        shutil.copy2(src / MANIFEST_NAME, dest / MANIFEST_NAME)

    # ٣) خطة «استبدال» لما تغيّر بنفس المسار — لا ندّعي ما لا يحدث
    if updated_ids:
        (dest / UPDATE_PLAN_NAME).write_text(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reason": "filePath مسجّل مسبقاً عند ميزان ⇒ المستورد يتخطاه "
                      "(csv_legal_library_importer.dart:114). لتحديث التطبيق "
                      "احذف السطر القديم أو نفّذ استبدالاً بـ filePath.",
            "rows": [{"action": "replace", "id": r.get("id"),
                      "title": r.get("title"),
                      "filePath": r.get("local_path"),
                      "sha256_new": r.get("sha256")} for r in ours
                     if r.get("id") in updated_ids]},
            ensure_ascii=False, indent=2), encoding="utf-8")

    # ٤) قياس الوجهة: هل وصلت بايتاتنا كما خرجت من الحزمة؟
    verify = verify_destination(root, dest, [r.get("id") for r in ours])

    receipt = {
        "injected_at": datetime.now().isoformat(timespec="seconds"),
        "producer": "mizan-harvester/injector",
        "mode": "replace-index" if replace_index else "merge",
        "package_dir": p["package_dir"], "mizan_root": p["mizan_root"],
        "dest": p["dest"],
        "gate_before": {"green": p["gate_green"], "failed": p["gate_failed"],
                        "forced": bool(not p["gate_green"] and allow_red_gate)},
        "rows": {"ours": p["rows_ours"], "theirs_before": p["rows_theirs"],
                 "added": len(p["added"]), "identical": len(p["identical"]),
                 "updated_same_path": len(p["updated_same_path"]),
                 "kept_foreign": len(p["kept_foreign"]),
                 "index_rows_after": len(final_rows)},
        "files_written": written, "backed_up": backed_up[:6],
        "backup_dir": str(backup) if backed_up else None,
        "verify_our_rows": verify, "warnings": p["warnings"],
        "index_sha256": _sha256_file(dest / INDEX_NAME),
        "next_step_in_mizan": "المكتبة تُستورد آلياً فقط إن كانت أقل من 8 "
                              "عناصر (legal_library_models.dart:375) — لذا "
                              "شغّل الاستيراد من ميزان أو اطلب زرّ «استيراد من "
                              "الحزمة» (مواصفة MIZAN-INJECTION-HOOKS.md)",
    }
    text = json.dumps(receipt, ensure_ascii=False, indent=2)
    (dest / RECEIPT_NAME).write_text(text, encoding="utf-8")
    try:  # نسخة عند الحزمة — للتدقيق حتى لو حُذفت الوجهة
        (src / RECEIPT_NAME).write_text(text, encoding="utf-8")
    except OSError:
        pass
    log.info(f"حقن في ميزان: {len(p['added'])} صفاً جديداً +{written} ملف "
             f"→ {dest}")
    return receipt


def _merge(theirs: list[dict], ours: list[dict]) -> list[dict]:
    """صفوفهم التي لا تعنينا + صفوفنا (صفوفنا تفوز على صفّهم بنفس المسار/الـid)."""
    ours_keys = {(r.get("local_path") or "", r.get("id") or "") for r in ours}
    kept = [r for r in theirs
            if (r.get("local_path") or "", r.get("id") or "") not in ours_keys]
    return kept + ours


def verify_destination(mizan_root: Path, dest: Path, ids: list[str]) -> dict:
    """لكل صَفّنا في الوجهة: الملف موجود؟ وبصمته مطابقة للفهرس المدموج؟"""
    rows = {r.get("id"): r for r in _read_rows(dest / INDEX_NAME)}
    missing, mismatch = [], []
    for i in ids:
        r = rows.get(i)
        if r is None:
            missing.append(i)
            continue
        f = _dest_path(Path(mizan_root), r.get("local_path") or "")
        if not f.exists():
            missing.append(i)
        elif (r.get("sha256") or "").lower() != _sha256_file(f):
            mismatch.append(i)
    return {"checked": len(ids), "missing": missing, "sha_mismatch": mismatch,
            "ok": not missing and not mismatch}


def read_receipt(mizan_root) -> dict | None:
    """إيصالية آخر حقن من الوجهة — None إن لم يسبق حقن."""
    f = library_dir(mizan_root) / RECEIPT_NAME
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def summarize(plan_or_receipt: dict, *, for_write: bool = True) -> str:
    """نصّ عربي قصير للعرض (حوار التأكيد في الشاشة أو مخرج الـCLI)."""
    r = plan_or_receipt
    rows = r.get("rows", r)
    added = len(r.get("added", [])) if "added" in r else rows.get("added", 0)
    upd = (len(r.get("updated_same_path", [])) if "updated_same_path" in r
           else rows.get("updated_same_path", 0))
    kept = (len(r.get("kept_foreign", [])) if "kept_foreign" in r
            else rows.get("kept_foreign", 0))
    lines = [
        f"الوجهة: {r.get('dest', '')}",
        f"طريقة الفهرس: {'استبدال كامل' if r.get('replace_index') else 'دمج (صفوفهم تبقى)'}",
        f"بوابة الحزمة: {'✓ خضراء' if r.get('gate_green', True) else '✗ حمراء — ' + '؛ '.join(r.get('gate_failed', []))}",
        (f"سيُضاف: {added} صفاً | بلا تغيير: {len(r.get('identical', [])) if 'identical' in r else rows.get('identical', 0)}"
         f" | معدَّل بنفس المسار: {upd} | محفوظ من فهرسهم: {kept}"),
        f"عدد الفهارس بعد الحقن: {r.get('index_rows_after', rows.get('index_rows_after', ''))}",
    ]
    for w in r.get("warnings", []):
        lines.append("⚠︎ " + w)
    if not for_write:
        lines.append("(معاينة — لم تُكتب أي بايتات)")
    return "\n".join(x for x in lines if x)
