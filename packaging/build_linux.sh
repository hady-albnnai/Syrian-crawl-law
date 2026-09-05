#!/usr/bin/env bash
# build_linux.sh — يبني حزمة Linux ويدخّنها (smoke مجمد offscreen).
# الاستخدام من جذر المستودع: bash packaging/build_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Qt يحتاج رموز النظام (libxkbcommon…) منذ الاستيراد — قبل PyInstaller نفسه
export QT_QPA_PLATFORM=offscreen
if [ -d "$HOME/qtlibs" ]; then export LD_LIBRARY_PATH="$HOME/qtlibs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"; fi

python3 -m pip install --quiet pyinstaller
python3 -m PyInstaller packaging/mizan-harvester.spec --noconfirm

BIN=dist/mizan-harvester/mizan-harvester
chmod +x "$BIN"
"$BIN" --smoke
echo "✔ build_linux: الحزمة في dist/mizan-harvester/ — دخّنت بنجاح"
