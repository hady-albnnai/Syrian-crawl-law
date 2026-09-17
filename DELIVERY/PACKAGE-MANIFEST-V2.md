# عقد حزمة ميزان v2 — المانيفست والجانبية الموسَّعة

دفعة 2 («عقد التصدير»). كل رقم هنا **مقاس في هذه الشجرة** أو موسوم صراحةً.
الحالة: منفَّذ ومختبَر محلياً (311 اختباراً، منه 19 على هذا العقد)؛ **غير مُطبَّق
في ميزان بعد** — هذا العقد يوضَّح لما يقرؤه ميزان، وهو لا يغيّر شيئاً في Dart.

لماذا وُجد هذا العقد؟ الحزمة القديمة كانت فهرساً فقط: ترى ميزان «مؤشراً على ملف»
لا متنـاً — 16,930 مادة محصودة كان لا يصِل منها صَفْر مواد إلى تطبيق المحامي
(قياس قاعدة المالك، 2026-09-17).

---

## 1. البنية على القرص

```
<prefix>laws_decrees_index.csv          ← 14 عموداً، ترتيب ثابت، UTF-8 BOM، LF
<prefix>markdown/<stem>.md              ← المتن الذي يفتحه ميزان (نفس الملف الذي تُبصَم عليه)
<prefix>markdown/<stem>.json            ← الجانبية: عقد الوثيقة + موادها (موسَّع في v2)
mizan_package_manifest.json              ← عقد الحزمة الآلي (جديد v2)
```

`<stem>` = `year_title_id` (مثال مقاس: `2024_قانون_مثال_1`). الفهرس **يبقى
14 عموداً كما هو**؛ لم يُزَد ولا يُنقَص عمود، لأن `parseCsvIndex` في ميزان يبني
قاموساً من سطر الترويسة ⇒ الأعمدة الزائدة آمنة نظرياً، لكن لم نُغَيِّر شيئاً
تحت هذا الضغط: الغنى كلّه يُحمَل في الطبقتين الأخريين.

### أعمدة الفهرس (بترتيبها، كما في `REQUIRED_COLUMNS`)

```
id, title, type, number, year, date, category, url, format,
priority, status, local_path, size_bytes, sha256
```

`sha256` هنا هي بصمة **ملف الـmarkdown نفسه** (دفعة 1: `hashlib.sha256(md_bytes)`)،
وليست بصمة اللقطة الخام؛ اللقطة بقيت في `snapshot_sha256` داخل JSON. هذا هو
الإصلاح الذي جعل البوابة الحمراء لميزان قابلة للاجتياز أصلاً.

---

## 2. `mizan_package_manifest.json` (الحقول المقاسة من ملف مولَّد)

```json
{
  "schema_version": "2",
  "generated_at": "2026-09-17T12:10:50",
  "producer": "mizan-harvester",
  "index": {
    "file": "laws_decrees_index.csv",
    "columns": ["id", "title", "type", "…", "sha256"],
    "sha256": "1f5d2b1d…",
    "rows": 1
  },
  "corpus": {"documents": 1, "articles": 1},
  "index_bom": true,
  "index_line_endings": "lf",
  "files": [
    {
      "id": "law_2024_1",
      "title": "قانون مثال",
      "markdown": "markdown/2024_قانون_مثال_1.md",
      "markdown_sha256": "19d0db3e…",
      "size_bytes": 204,
      "json": "markdown/2024_قانون_مثال_1.json",
      "json_sha256": "5fa68a8f…",
      "category": "civil", "type": "قانون", "number": "1", "year": "2024",
      "url": "https://example.org/a", "format": "html",
      "priority": "2", "status": "crawled"
    }
  ]
}
```

قاعدة صلبة مُطبَّقة في `package_manifest.build_manifest`: **كل رقم وكل بصمة
تُقرأ من الحزمة بعد كتابتها على القرص، لا من القاعدة** — «لا ادعاء بلا قياس»؛
لو انحدّرت كتابة الحزمة، يكذب المانيفست فوراً ويُكتشف، بدلاً من أن يشهد لنفسه.

---

## 3. JSON الجانبية: المفاتيح التي زادت في v2

من ملف مولَّد فعلاً (نفس تجربة §2):

```
TOP:      doc_id, title, number, year, branch, source_url, content_sha256,
          snapshot_sha256, legal_status, review_status, source_domain_tier,
          quality_score, identity_key, articles,
          [v2] schema_version, identity_confidence, document_status,
               domain_tier, is_complete_text, branch_key, document_type,
               amends, amended_by_docs
ARTICLE:  number, label, text, hierarchy_path, paragraphs, amended_by,
          [v2] text_sha256
```

- `amends[]`: `{action, target_identity, amender, amender_number, amender_year,
  context≤240}` — إحالات هذه الوثيقة على غيرها (من `law_amendments`، ف١).
- `amended_by_docs[]`: المعكوس، محسوباً بمطابقة `identity_key` للوثيقة.
- `text_sha256` لكل مادة: يستطيع ميزان أن يطمئن على نص المادة عند البناء،
  لا على الملف كله فقط.
- الجدول `law_amendments` مفقود؟ الخرائط تُعيد `{}` بصمت (`_amendment_maps`
  يتحقق من `sqlite_master`) — لا انهيار على مخطط قديم. كذلك `_get()` في
  `exporter.py` يلغي `IndexError` على مخططات ما قبل ف١.

---

## 4. البوابة: فحص واحد، لا نسختان

`verify_package.check_package(package_dir)` يُعيد `[(رسالة، نجاح)]` وهي **نفس
منطق بوابة ميزان حرفياً**، لا نسخة أخفّ (هذه كانت فجوة حقيقية: نسخة أخفّ كانت
تجعل كسر البصمة يمرّ على الواجهة بصمت):

| الفحص | ما يثبت |
|---|---|
| UTF-8 مع BOM | كما يقرأه ميزان |
| LF حصراً | لا CRLF في الفهرس |
| 14 عموداً بترتيبها | الترويسة |
| بصمة الفهرس = بصمة `local_path` (لكل صف) | **ميزان سيطّلع على كل الصفوف** — مع سماح إعادة الحساب بعد CRLF→LF |
| لا ملف مفقود | `File('$root/$local_path')` موجود |
| `size_bytes` مطابقة | لا ملف مبتور |
| لا `id` مكرر ولا عنوان فارغ | الفهرس صالح للبناء عليه |
| JSON جانبي بمواد مُهرملة لكل صَفْر | عقد المواد موجود فعلاً |
| المانيفست موجود | لا حزمة بلا عقد |

`gate_ok()` ⇒ منع؛ `article_counts()` ⇒ عدادات من القرص.
`app/core_data.validate_package()` **تندب هذه الوحدة** (سماها تسمية خفيفة)،
واختبار `test_core_data_delegates_to_verify_package` يفرض تطابق المفاتيح — فلا
تُبنى بوابة أخفّ ثانية على الواجهة.

---

## 5. المستهلكات (CLI) — مخرجات مقاسة

```
python -m cli export --out <dir> [--prefix …] [--min-articles N] [--db …] [--no-manifest]
python -m cli verify <package_dir>          ← يفحص حزمة جاهزة بلا إعادة توليد
```

`cli export` يطبع «المانيفست: schema v… | بوابة ميزان: ✓ ستُستورد كل الصفوف» و
«مواد داخل الحزمة (معدودة من القرص)»، و**خروجه 1 إذا أخفقت البوابة** (يبني ميزان
على مقياس صحيحي). `--db` أُضيف لأن `cmd_export` كان يلتقط `DB_PATH` كقيمة افتراضية
وقت الاستيراد — فجوة إنتاجية كشفها اختبار ترتيب الحزمة الكاملة، لا اختبار منفرد.

## 6. الحراسة ضد الانحدار (اختبارات)

`tests/test_package_contract_v2.py` — 19 اختباراً، منها:
`test_detects_legacy_snapshot_hash` (بصمة لقطة وهمية ⇒ سقوط البوابة)،
`test_detects_tampered_markdown`، `test_detects_crlf_index`،
`test_detects_missing_manifest`، `test_every_article_has_text_fingerprint`.

## 7. ما لم أتحقق منه

- سلوك `planCsvImport` مقروء من مستودع ميزان (منسخة محلية)؛ **لم أُشغّل Dart
  هنا** (لا Flutter في الصندوق)، فاجتياز ميزان الفعلي للحزمة v2: غير متحقق.
- لم تُختبَر الحزمة التاريخية في ميزان (29/29 بصمة سليمة) إلا قراءةً — لذا
  لم يكشفها أحد يدوياً من قبل.
- أرقام قاعدة المالك (513 وثيقة / 16,930 مادة / 291 بلا هوية) قياس قاعدة المالك
  بتاريخ 2026-09-17، لا قياس هذه الشجرة.
