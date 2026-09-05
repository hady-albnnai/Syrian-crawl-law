; mizan-harvester.iss — مثبّت Windows لحاصدة ميزان (Inno Setup 6)
;
; ⚠️ غير مُتحقق منه في بيئة التطوير (Linux): PyInstaller لا يبنّي exe
; لويندوز من لينكس. يُبنى على آلة Windows ثم يُغلَّف هنا.
;
; على Windows:
;   1) python -m pip install pyinstaller
;   2) python -m PyInstaller packaging\mizan-harvester.spec --noconfirm
;   3) "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\mizan-harvester.iss
;
; الناتج: Output\mizan-harvester-setup-0.2.0.exe

#define MyAppName "حاصدة ميزان"
#define MyAppNameLatin "Mizan Harvester"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Syrian Qanun Archive"
#define MyAppExeName "mizan-harvester.exe"

[Setup]
AppId={{B7E2A1D4-2026-4F05-9C31-MIZANHARVEST01}
AppName={#MyAppName} ({#MyAppNameLatin})
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MizanHarvester
DefaultGroupName={#MyAppNameLatin}
OutputBaseFilename=mizan-harvester-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; بيانات المحامي (القاعدة/اللقطات/الحزم) في مجلد التطبيق لا AppData —
; قرار «حزمة قابلة للنسخ والتدقيق» في DESIGN-TOOL-APP.md
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
; مجلد onedir كاملاً كما ينتجه PyInstaller
Source: "..\dist\mizan-harvester\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppNameLatin}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppNameLatin}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل حاصدة ميزان الآن"; Flags: nowait postinstall skipifsilent
