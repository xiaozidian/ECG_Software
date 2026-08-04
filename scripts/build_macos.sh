#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h}"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "macOS 应用必须在 macOS 上构建。"
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  "$SCRIPT_DIR/setup_macos.sh"
fi

"$VENV_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements-dev.txt"
cd "$PROJECT_ROOT"
"$VENV_PYTHON" -m PyInstaller --noconfirm --clean CardioInsightHolter.spec

APP_PATH="$PROJECT_ROOT/dist/CardioInsightHolter.app"
if [[ ! -d "$APP_PATH" ]]; then
  print -u2 "构建失败：未生成 $APP_PATH"
  exit 1
fi

xattr -cr "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
print "已生成并进行临时签名：$APP_PATH"
print "对外分发前请使用 Apple Developer ID 签名并完成 notarization。"
