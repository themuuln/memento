#!/bin/bash
# Memento — one-command setup script
# Run: bash ~/.agent-memory/setup.sh
set -euo pipefail

MEMENTO_DIR="${MEMENTO_DIR:-$HOME/.agent-memory}"
PI_EXT_DIR="$HOME/.pi/agent/extensions"
CLI_TARGET="$HOME/.local/bin/memory"

echo "🔧 Installing memento..."

# 1. Install Python package
echo "   📦 Installing Python package..."
pip3 install -e "$MEMENTO_DIR" -q

# 2. Symlink CLI
if [ ! -L "$CLI_TARGET" ] || [ "$(readlink "$CLI_TARGET")" != "$MEMENTO_DIR/memory" ]; then
    echo "   🔗 Symlinking CLI..."
    mkdir -p "$(dirname "$CLI_TARGET")"
    ln -sf "$MEMENTO_DIR/memory" "$CLI_TARGET"
fi

# 3. Install Pi extensions
echo "   📋 Installing Pi extensions..."
mkdir -p "$PI_EXT_DIR"
cp "$MEMENTO_DIR/extensions/memory-tools.ts" "$PI_EXT_DIR/"
cp "$MEMENTO_DIR/extensions/memory-compaction-capture.ts" "$PI_EXT_DIR/"

# 4. Verify
echo ""
echo "━━━ Verification ━━━"
if command -v memory &>/dev/null; then
    memory --json status 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'  Health:  {d[\"health\"]}')
print(f'  Entries: {d[\"files\"][\"total\"]}')
print(f'  Issues:  {len(d[\"issues\"])}')
"
    echo "  ✅ memory CLI working"
else
    echo "  ⚠️  'memory' not found on PATH — add ~/.local/bin to PATH"
fi

if [ -f "$PI_EXT_DIR/memory-tools.ts" ]; then
    echo "  ✅ Pi extension installed"
else
    echo "  ⚠️  Extension not copied — check $PI_EXT_DIR"
fi

echo ""
echo "✅ Setup complete. Restart Pi to load extensions."
