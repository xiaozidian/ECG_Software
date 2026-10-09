#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
PACKAGE_DIR="${SCRIPT_DIR:h}"
EXECUTABLE="$PACKAGE_DIR/CardioInsightMacCandidate.app/Contents/MacOS/CardioInsightMacCandidate"
if [[ ! -x "$EXECUTABLE" ]]; then
  print -u2 "未找到同目录的 CardioInsightMacCandidate.app。请保留整个评估包，并先完成构建。无需安装系统 Python。"
  exit 2
fi
exec "$EXECUTABLE" "$@"
