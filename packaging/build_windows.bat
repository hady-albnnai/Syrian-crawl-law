@echo off
REM build_windows.bat — يبني exe ثم مثبّت Inno على آلة Windows.
REM يُشغَّل من جذر المستودع بعد استنساخه.
setlocal
cd /d "%~dp0.."

python -m pip install --quiet pyinstaller || exit /b 1
python -m PyInstaller packaging\mizan-harvester.spec --noconfirm || exit /b 1

REM دخان المجمد قبل التغليف
dist\mizan-harvester\mizan-harvester.exe --smoke || exit /b 1

where iscc >nul 2>&1
if %errorlevel%==0 (
    iscc packaging\mizan-harvester.iss || exit /b 1
) else (
    echo [تنبيه] ISCC غير موجود على PATH — جرب:
    echo "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\mizan-harvester.iss
)
echo ✔ اكتمل البناء: dist\mizan-harvester\ + Output\mizan-harvester-setup-0.2.0.exe
endlocal
