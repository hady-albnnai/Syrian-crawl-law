# التوزيع — حاصدة ميزان (قرار المالك: توزيع أوسع لمحامين آخرين)

## ما يُبنى

| المنصة | الأداة | الناتج | حالة التحقق |
|---|---|---|---|
| Linux | `build_linux.sh` (PyInstaller onedir) | `dist/mizan-harvester/` | ✅ **مُدخَّن في بيئة التطوير** (smoke مجمد offscreen) وفي CI |
| Windows | `build_windows.bat` (PyInstaller + Inno Setup 6) | `Output\mizan-harvester-setup-0.2.0.exe` | ⚠️ غير مُتحقق هنا — PyInstaller لا يبني exe لويندوز من لينكس؛ يُبنى على آلة Windows |

## لماذا onedir لا onefile
إقلاع أسرع، بلا مستخرج مؤقت يثير إنذارات مكافحة الفيروسات، والمجلد
قابل للنسخ والتدقيق ملفاً ملفاً — وهو ما يناسب جمهور المحامين.

## أين تعيش البيانات؟
عند الإقلاع المجمد ينتقل مسار العمل إلى مجلد الثنائي (`entry_gui.py`)،
فتُخلق `data/` (القاعدة + snapshots خارج Git) و`export/` (الحزم) بجانبه —
حزمة محمولة قابلة للنسخ على USB دون تثبيت.

## متطلبات وقت التشغيل (Linux)
الثنائي المجمد يضم مكتبات Qt من عجلة PySide6؛ إن نقصت رموز نظام
(مثل `libxkbcommon.so.0` في حاويات مجردة) تُمرر عبر `LD_LIBRARY_PATH`
كما يفعل `build_linux.sh` وCI. أجهزة المستخدمين العادية تملكها.

## خطوات Windows (تفصيلاً)
1. `python -m pip install -e ".[ui]"` ثم `pip install pyinstaller`
2. `python -m PyInstaller packaging\mizan-harvester.spec --noconfirm`
3. `dist\mizan-harvester\mizan-harvester.exe --smoke` (دخان)
4. ثبّت Inno Setup 6 ثم `ISCC.exe packaging\mizan-harvester.iss`
5. وزّع `Output\mizan-harvester-setup-0.2.0.exe`

## ما لا يُدَّعى
لم يُشغَّل المثبّت Windows في بيئة تطويرنا (Linux) — لا يُقال «جُرّب على
ويندوز» قبل أن يجري المالك أو CI-Windows ذلك. ملفا `.iss` و`.bat`
مكتوبان وفق توثيق PyInstaller/Inno 6 وبانتظار أول بناء ويندوزي فعلي.
