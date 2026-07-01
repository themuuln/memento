#!/bin/bash
# Session-end memory consolidation — shared between Pi and Factory.
# Shim: delegates to `memory consolidate` CLI.
#
# Usage (Pi):
#   echo '...json...' | consolidate-session.sh --source pi --session SID
#
# Usage (Factory):
#   consolidate-session.sh --source factory --session SID --transcript /path/to/log

set -euo pipefail

MEMORY_ROOT="${AGENT_MEMORY_DIR:-$HOME/.agent-memory}"
MEMORY_BIN="$(dirname "$0")/../memory"

# Forward all args to `memory consolidate`
if [[ "$*" == *"--source"* ]]; then
  exec "$MEMORY_BIN" consolidate "$@"
else
  # Default: read from stdin (Pi mode)
  exec "$MEMORY_BIN" consolidate --source pi "$@"
fi
