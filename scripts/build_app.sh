#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python scripts/create_icon.py
.venv/bin/python -m PyInstaller \
  --noconfirm --clean --windowed --name PaperEdit2 --icon artifacts/PaperEdit.icns \
  --osx-bundle-identifier local.paperedit.editor.v2 \
  --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets \
  --collect-data pymupdf \
  --add-data 'artifacts/编辑示例.pdf:examples' \
  launch.py
