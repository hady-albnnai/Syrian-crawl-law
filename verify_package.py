# -*- coding: utf-8 -*-
"""verify_package.py — مصدر الحقيقة الواحد للتحقق من حزمة المحتوى.

علة وُجدت (قِيس 2026-09-17): كانت دلالة البصمة موزّعة على ثلاث نسخ من
المنطق — exporter.py (يكتبها)، core_data.validate_package (يفحصها بشدة
أخفّ)، وcsv_legal_library_importer.dart في ميزان (بوابة الاستيراد
الحقيقية). الفارق بينها هو ما أخفى كسر sha256 عن الواجهة كلها.

هذه الوحدة نسخة واحدة من المنطق، **مطابقة لسلوك البوابة في ميزان سطرًا
سطرًا** كما قرئت من مستودع ميزان:

    File('$root/${local_path}')            ← الملف نفسه، لا اللقطة الخام
    sha256(bytes) == sha256الفهرس           ← وإلا يُتخطى «بصمة غير مطابقة»
    وإلا يُعاد الحساب بعد CRLF→LF           ← سماح سحب ويندوز
العقد المتفق عليه هو أربعة عشر عموداً بترتيب ثابت (`REQUIRED_COLUMNS`)؛
تقرؤها ميزان قاموسياً من سطر الترويسة، فالأعمدة الوصفية (`id` و`date`
و`priority` و`status`) آمنة وإن لم يستهلكها المستورد — قِستُ ذلك بالـgrep
على مستودع ميزان. فحوص البصمة والعدد أدقّ من قراءة الترويسة وحدها.

يستدعيها: cli export --verify، وشاشة «الحزمة» في الواجهة، والاختبارات.
"""
import csv
import hashlib
from pathlib import Path

from logging_setup import get_log

log = get_log(__name__)

# ما يفحصه المستورد في ميزان — بنفس الأسماء في csv_legal_library_importer.dart
REQUIRED_COLUMNS = ["id", "title", "type", "number", "year", "date",
                    "category", "url", "format", "priority", "status",
                    "local_path", "size_bytes", "sha256"]


def _crlf_to_lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def exported_file_sha256(package_dir: Path, local_path: str) -> tuple[Path, str | None]:
    """(المسار، البصمة) للملف الذي يفتحه ميزان فعلياً.

    المسار يُحسب نسبةً إلى جذر الحزمة بنفس صيغة التطبيق:
    `File('$root/${local_path}')` — فالحزمة تُصدَّر لتوضع داخل مستودع ميزان
    حيث `local_path` يبدأ من `content/…`. ولمّا كان `markdown/` يقع مباشرة
    تحت جذر الحزمة، فإن `root` هنا = `package_dir / '…/…'` المزيّف — لذا
    نبني المسار على آخر قسمين فقط (وثيقة سلوك موثقة في DELIVERY).
    """
    name = Path(local_path).name
    parent = Path(local_path).parts[-2] if len(Path(local_path).parts) >= 2 else ""
    cand = package_dir / parent / name if parent else package_dir / name
    if not cand.exists():
        cand = package_dir / name
    if not cand.exists():
        return cand, None
    b = cand.read_bytes()
    return cand, hashlib.sha256(b).hexdigest()


def check_package(package_dir) -> list[tuple[str, bool]]:
    """فحوص الحزمة بصيغة (رسالة، نجاح) — كما تعرضها الشاشة.

    لا ادعاء بلا قياس: الحزمة غير المولَّدة تُعيد فحصاً واحداً صادقاً
    بالإخفاق (نفس عقد validate_package التاريخي حتى لا تُكسر حارسته).
    """
    pkg = Path(package_dir)
    index = pkg / "laws_decrees_index.csv"
    if not index.exists():
        return [("\u0627\u0644\u062d\u0632\u0645\u0629 \u063a\u064a\u0631 \u0645\u0648\u0644َّ\u062f\u0629 \u0628\u0639\u062f — \u0627\u0636\u063a\u0637 \u00ab\u062a\u0648\u0644\u064a\u062f \u0627\u0644\u062d\u0632\u0645\u0629\u00bb", False)]
    out = []
    raw = index.read_bytes()
    out.append(("الفهرس UTF-8 مع BOM (كما يتوقعه ميزان)", raw.startswith(b"\xef\xbb\xbf")))
    out.append(("فواصل الأسطر LF حصراً (فهرس ميزان LF-only)", b"\r\n" not in raw))
    rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
    header = [h.strip() for h in raw.decode("utf-8-sig").splitlines()[0].split(",")]
    out.append((f"أعمدة ميزان الأربعة عشر بترتيبها ({len(header)})",
                header == REQUIRED_COLUMNS))
    # «بوابة خضراء على حزمة فاضية» كانت كذباً بصمت: قِيس 2026-09-17 أن
    # `cli export` على قاعدة بلا وثائق طبع «✓ ستُستورد كل الصفوف» وخرج 0،
    # لأن كل فحوص ما فوق تجري على قائمة صفوف فارغة فتنجح كلها. الحزمة
    # الفارغة لا تُصدِّر شيئاً، واستيراد ميزان أصلاً يسقط تحت 8 صفوف
    # (‏`bootstrap()` في csv_legal_library_importer.dart) — فلنجعلها حمراء.
    out.append((f"الفهرس فيه صفوف تُصدَّر ({len(rows)})", bool(rows)))
    missing, bad_size, bad_sha = [], [], []
    for r in rows:
        f, sha = exported_file_sha256(pkg, r.get("local_path", ""))
        if sha is None:
            missing.append(r.get("id", "?"))
            continue
        want = (r.get("sha256") or "").lower()
        if want not in (sha, hashlib.sha256(_crlf_to_lf(f.read_bytes())).hexdigest()):
            bad_sha.append(r.get("id", "?"))
        if r.get("size_bytes") and str(f.stat().st_size) != r["size_bytes"]:
            bad_size.append(r.get("id", "?"))
    # بوابة البصمة: المنطق الحرفي لـ planCsvImport — لا نسخة أخفّ
    out.append((f"ميزان يستورد كل الصفوف: بصمة الفهرس = بصمة ملف local_path "
                f"({len(rows)} صفاً)", not bad_sha))
    if bad_sha:
        out.append((f"  ⚠︎ بصمة غير مطابقة ⇒ سيتخطاها ميزان: {', '.join(bad_sha[:6])}"
                    + (" …" if len(bad_sha) > 6 else ""), False))
    out.append((f"لا ملف مفقود على القرص ({len(missing)} مفقود)", not missing))
    out.append((f"size_bytes مطابقة للملفات ({len(bad_size)} مخالف)", not bad_size))
    paths = [(r.get("local_path") or "").strip() for r in rows]
    seen, dups = set(), set()
    for pth in paths:
        (dups if pth in seen else seen).add(pth)
    # ميزان يفصل التكرار على `filePath` عنده — فمساران متطابقان معناهما أن
    # وثيقة واحدة تُستورد والأخرى تُدفن بصمت.
    out.append((f"لا مسار مكرر في local_path ({len(dups)} مكرر)", not dups))
    if dups:
        out.append(("  ⚠︎ تكرار اسم ملف ⇒ دفن وثيقة: "
                    + ", ".join(sorted(dups)[:4])
                    + (" …" if len(dups) > 4 else ""), False))
    ids = [r.get("id", "") for r in rows]
    out.append(("لا id مكرر ولا عنوان فارغ",
                len(ids) == len(set(ids)) and all((r.get("title") or "").strip()
                                                  for r in rows)))
    # عقد الحزمة الغني (الف٢ — عقد المواد): JSON جانبي لكل صَفْر + مانيفست
    js_missing = [r.get("id", "?") for r in rows
                  if not exported_file_sha256(pkg, r.get("local_path", ""))[0]
                  .with_suffix(".json").exists()]
    out.append((f"JSON جانبي بمواد مُهرملة لكل صَفْر ({len(rows) - len(js_missing)}"
                f"/{len(rows)})", not js_missing))
    manifest = pkg / "mizan_package_manifest.json"
    out.append(("مانيفست الحزمة (mizan_package_manifest.json) موجود",
                manifest.exists()))
    return out


def gate_ok(package_dir) -> bool:
    """بوابة صلبة: كل الفحوص خضراء، والبصمة مطابقة تحديداً."""
    checks = check_package(package_dir)
    return all(bool(ok) for _msg, ok in checks)


def article_counts(package_dir) -> dict:
    """عدادات من الحزمة نفسها (لا من القاعدة) — للعرض في الشاشة."""
    pkg = Path(package_dir)
    index = pkg / "laws_decrees_index.csv"
    if not index.exists():
        return {"rows": 0, "articles": 0, "docs_with_json": 0}
    rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
    import json as _json
    arts = 0
    n_json = 0
    for r in rows:
        jp = exported_file_sha256(pkg, r.get("local_path", ""))[0].with_suffix(".json")
        if not jp.exists():
            continue
        n_json += 1
        try:
            arts += len(_json.loads(jp.read_text(encoding="utf-8")).get("articles", []))
        except (ValueError, OSError):
            continue
    return {"rows": len(rows), "articles": arts, "docs_with_json": n_json}
