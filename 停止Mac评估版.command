#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
exec "$SCRIPT_DIR/scripts/mac_release_command.sh" stop --interactive "$@"
