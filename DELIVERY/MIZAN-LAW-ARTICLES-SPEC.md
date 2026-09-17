# مواصفة ميزان: جدول `law_articles` + FTS5 للمواد العربية

**هذه مواصفة، لا كود.** جهة الحاصدة (mizan-harvester) انتهت من دفعتها؛ لا أعدّل
`lawyer-office2` ولا بوابته الحمراء بقرار نطاق من المالك. الوثيقة مكتوبة ليأخذها
منفّذ ميزان كما هي. كل ما نُسِب إلى ميزان هنا **مقروء من نسخة محلية من المستودع**
(`csv_legal_library_importer.dart` و`lib/data/database/schema.dart`)،
ولم أُشغّل Dart في هذه البيئة (لا Flutter مثبَّت): الفصول الموسومة «غير متحقق»
تُتحقق عند التنفيذ.

## 1. الفجوة بالأرقام

| القياس | القيمة | مصدر |
|---|---|---|
| وثائق في حزمة مطبَّعة | 513 | قياس قاعدة المالك 2026-09-17 |
| مواد محصودة | 16,930 | قياس قاعدة المالك |
| صَفْر مواد تصل إلى ميزان اليوم | **0** | قراءة: لا جدول مواد في `schema.dart` |
| صفوف الفهرس في حزمة ميزان المطبَّعة | 29 (17 md + 12 pdf) | قياس محلي على `content/legal_library/laws_decrees/` |
| بصمات مطابقة لسلوك `planCsvImport` | 29/29 | قياس محلي |

النتيجة: المحامي يقرأ «الملف الكامل» من `LegalLibraryItems.extractedText`، أما
**المرجع بالمادة** («المادة ٢٤ من القانون ١٤ لعام ٢٠٢») فغير ممكن لا تخزيناً ولا
بحثاً. هذا هو السبب الوحيد الذي لا تُستهلَك معه الحزمة كاملة.

## 2. DDL مقترح (يُضاف إلى `schema.dart` بجانب `LegalLibraryItems`)

```sql
CREATE TABLE legal_library_articles (
  id                TEXT PRIMARY KEY,          -- '<doc_key>:<n>' ثابت قابل للتكرار
  item_id           TEXT NOT NULL,             -- FK إلى LegalLibraryItems.id
  doc_key           TEXT NOT NULL,             -- identity_key من الحزمة (law:14:2021)
  article_no        INTEGER,                   -- رقم صحيح إن وُجد
  article_label     TEXT,                      -- «المادة ٢٤» أو «مادة ٢٤ مكرراً»
  hierarchy_path    TEXT,                      -- «الباب ٣ › الفصل ١»
  body              TEXT NOT NULL,             -- نص المادة ( paragraphs مُدمَجة بـ\n\n )
  body_sha256       TEXT NOT NULL,             -- = text_sha256 من JSON الجانبية
  legal_status      TEXT,                      -- sari / mulgha / muaddal …
  law_kind          TEXT,                      -- نوع الصك (قانون/مرسوم تشريعي/قرار)
  amends_json       TEXT,                      -- JSON: [{action,target_identity,…}]
  amended_by_json   TEXT,                      -- JSON: المعكوس
  domain_tier       INTEGER,                   -- 1..4 طبقة الرسمية
  source_url        TEXT,
  imported_at       INTEGER NOT NULL
);
CREATE INDEX idx_lla_item ON legal_library_articles(item_id);
CREATE INDEX idx_lla_doc  ON legal_library_articles(doc_key, article_no);
```

**قيد متعمَّد:** لا يُكتَب في عمود `body` أكثر من `is_complete_text=true` للوثيقة؛
وإلا يُملأ `body` مع `body_truncated=1` (يُضاف العمود) بدل أن تُقرأ مادة مبتورة
على أنها كاملة — الحاصدة تعرف `is_complete_text` والميزان يصدّقها.

## 3. FTS5 للمواد العربية — النمط الهجين

`extractor_v4.py:219` يوثّق فشلاً مقاساً: **FTS5 مع `unicode61` لا يسترجع العربية
بشكل مُرضٍ** (التقطيع اللفظي بلا تطبيع عربي). لا تُكرَّر نفس المغامرة في Dart.
النمط الموصّى به:

```sql
CREATE VIRTUAL TABLE legal_library_articles_fts USING fts5(
  body, article_label, hierarchy_path,
  content=legal_library_articles, content_rowid=rowid,
  tokenize = "unicode61 remove_diacritics 2"
);
-- محفزات الحفظ/الحذف قياسية على FTS5 external content.
```

وقاعدة الرجوع (هي المهمّة، لا الجدول وحده):

```
OR  BETWEEN legal_library_articles
WHERE (legal_library_articles_fts MATCH ?)
   OR (legal_library_articles.body LIKE ? ESCAPE '\')      -- مسار العربية المضمون
ORDER BY rank IS NULL, rank, domain_tier DESC, legal_status = 'sari' DESC
```

أي: **FTS5 للمرشّحات + LIKE كضمانة للعربية**، لا أيّهما وحده؛ ويُجرَّب
`remove_diacritics 2` قبل أي محوّل تطبيع يدوي. هذا نمط مطبَّق ومقيس في الحاصدة
(Ansible/F1 heron) — نقله أرخص من إعادة اكتشاف عطلته.

## 4. تغذية الجدول من الحزمة (توسيع `csv_legal_library_importer.dart`)

1. بعد نجاح الاستيراد لكل صَفْر (`sha256` الملف ✓)، اقرأ `markdown/<stem>.json`
   المقابل — المسار مُشتَق من `local_path` باستبدال اللاحقة `.md → .json`.
2. لكل عنصر في `articles[]`: املأ `legal_library_articles` من
   `number/label/text|paragraphs/hierarchy_path/text_sha256`، ومن رؤوس الوثيقة:
   `identity_key → doc_key`، `legal_status`، `document_type → law_kind`،
   `domain_tier`، `source_url`، `amends`/`amended_by_docs` (JSON كما هي).
3. `id` = `doc_key + ':' + (article_no ?? label)` ⇒ **استيراد الحزمة مرتين لا
   يُنشئ تكراراً** (`INSERT OR REPLACE`).
4. `extractedText` في `LegalLibraryItems` **لا يُهمَل بعد الآن**: يملؤه
   `body` المضموم لكل مواد الوثيقة (هو الحقل الموجود والجاهز أصلاً، لا تحتاج
   هجرة إضافية لعرض الملف).
5. `lawKind` و`lastAmendment` حقول جاهزة لا تُمْلأ اليوم في `LegalLibraryItems`:
   تُمْلأ من `document_type` و`amended_by_docs[0].amender (+ year)`.
6. **فشل JSON لا يجب أن يُسقط استيراد المتن**: المادة طبقة إضافية؛ عند غياب
   JSON تُستورد الوثيقة بلا مواد ويُعلَن ذلك في تقرير الاستيراد (نفس سياسة
   الحاصدة: «لا استثناء غير معالج في مسار حرج»، ودرس `SystemExit` في
   `pdf_to_text`).

## 5. البوابة قبل البناء

قبل تنفيذ أي استيراد، شغّل `python -m cli verify <package_dir>` في الحاصدة:
بوابة واحدة تثبت أن كل صف سيُطّلع عليه وأن لكل صَفْر JSON بمواد مُهرملة.
**إن خضّرت البوابة في الحاصدة فذلك شرط قبول الاستيراد في ميزان** — لا
«استيراد ثم اكتشاف». البوابة الحمراء لـ`planCsvImport` تبقى كما هي: لا تُرخَّص.

## 6. قبول التنفيذ (اختبارات يجب أن تُكتب في ميزان)

| الاختبار | ينجح إذا |
|---|---|
| استيراد حزمة اختبارية بـN مواد | عدد صفوف `legal_library_articles` = N، و`body_sha256` = `text_sha256` لكل مادة |
| استيراد مرتين | لا تكرار (count ثابت) — الـPK قابل للتكرار |
| تعديل Markdown مع بقاء الفهرس قديماً | الاستيراد **يرفض/يتخطى** ذلك الصَفْر ولا يبني مواد على ملف لا تطابق بصمته |
| بحث «عقوبات» بالعربية | نتيجة عبر المسار الهجين (LIKE يضمنها) |
| وثيقة `is_complete_text=false` | موادها موسومة مبتورة، ولا تظهر في الاستشهاد ككاملة |
| حذف `legal_library_items` أم | تتلاشى مواده (FK cascade أو حذف صريح مغطّى باختبار) |

## 7. غير متحقق / خارج هذه المواصفة

- لا أُشغّل Dart هنا: السلوك الفعلي لـ`planCsvImport` من **قراءة الكود** لا من
  تنفيذ؛ أي تعارض بين §4 وما ينفّذه المستورد فعلاً يُحسم عند التنفيذ.
- لا أعرض رقمنة هجرة قديمة: `legal_library_articles` جدول جديد بلا حالة سابقة؛
  29 صَفْر حالية تُعاد تغذيتها باستيراد الحزمة من جديد.
- `html/*.json` اليُتماء في `content/legal_library/` **لا يقرؤها سطر Dart**
  (قياس grep) — تبقى يتيمة، والمرجع الصحيح هو `markdown/*.json` الذي تصدّره
  الحاصدة.
