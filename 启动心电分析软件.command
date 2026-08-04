#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="${0:A:h}"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  "$PROJECT_ROOT/scripts/setup_macos.sh"
fi

cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" app.py "$@"
