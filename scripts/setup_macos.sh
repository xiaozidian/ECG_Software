#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h}"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "此脚本仅用于 macOS。"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  print -u2 "未找到 Python 3。请先安装 Python 3.11 或更高版本。"
  exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  print -u2 "当前 Python 为 $PYTHON_VERSION；请安装 Python 3.11 或更高版本。"
  exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  print "正在创建本地 Python 环境…"
  python3 -m venv "$PROJECT_ROOT/.venv"
fi

print "正在安装运行依赖…"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"

CONFIG_PATH="$PROJECT_ROOT/config.json"
if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$PROJECT_ROOT/config.example.json" "$CONFIG_PATH"
  print "已创建本机配置：$CONFIG_PATH"
fi

print "macOS 运行环境已就绪。"
print "请确认项目根目录 config.json 中的 data_root 指向本机病例目录。"
