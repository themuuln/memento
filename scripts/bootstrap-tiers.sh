#!/bin/bash
# Bootstrap tiering: classify existing entries into hot/warm/cold.
# Handles both bullet-point (- text) AND date-time (- [date] text) formats.
set -euo pipefail

ROOT="${AGENT_MEMORY_DIR:-$HOME/.agent-memory}"
GLOBAL="$ROOT/global/memories.md"
RULES="$ROOT/global/rules.md"
PREFS="$ROOT/global/preferences.md"
HOT_DIR="$ROOT/archive/entries/hot"
WARM_DIR="$ROOT/archive/entries/warm"
COLD_DIR="$ROOT/archive/entries/cold"

mkdir -p "$HOT_DIR" "$WARM_DIR" "$COLD_DIR"

echo "🧠 Bootstrapping memory tiers..."

hot=0; warm=0; cold=0
section=""; entry_id=0

# ── Rules + Prefs → HOT (always injected) ──────
for src in "$RULES" "$PREFS"; do
  if [ -f "$src" ]; then
    cp "$src" "$HOT_DIR/000_$(basename "$src")"
    echo "   🔥 $(basename "$src") -> hot/"
    hot=$((hot+1))
  fi
done

# ── Parse entries from global/memories.md ──────
[ ! -f "$GLOBAL" ] && echo "No global/memories.md" && exit 0

while IFS= read -r line; do
  # Section header
  if [[ "$line" =~ ^##[[:space:]]+(.*) ]]; then
    section="${BASH_REMATCH[1]}"
    continue
  fi
  # Skip blank lines, separators, comments
  [[ -z "$line" ]] && continue
  [[ "$line" == "---" ]] && continue
  [[ "$line" == "<!--"* ]] && continue

  # Bullet entry: "- text..."
  if [[ "$line" =~ ^-[[:space:]]+(.*) ]]; then
    text="${BASH_REMATCH[1]}"
    lower_text=$(echo "$text" | tr '[:upper:]' '[:lower:]')
    tier="cold"

    # Section-based defaults
    if echo "$section" | grep -qiE 'hard rules|preference|model configuration'; then
      tier="hot"
    elif echo "$section" | grep -qiE 'project convention|tool quirk|validated approach'; then
      tier="warm"
    fi

    # Entry-level keyword overrides
    if echo "$lower_text" | grep -qE '\b(always|never|must|required|mandatory)\b'; then
      tier="hot"
    fi
    if echo "$lower_text" | grep -qE '\b(gotcha|crash|breaks|bug|pitfall)\b'; then
      tier="warm"
    fi

    # Per-project convention subsections -> warm
    if echo "$section" | grep -qiE 'project convention'; then
      tier="warm"
    fi

    target_dir="$COLD_DIR"
    emoji="cold"
    case "$tier" in
      hot) target_dir="$HOT_DIR"; emoji="hot"; hot=$((hot+1)) ;;
      warm) target_dir="$WARM_DIR"; emoji="warm"; warm=$((warm+1)) ;;
      cold) cold=$((cold+1)) ;;
    esac

    entry_id=$((entry_id+1))
    printf "## %s\n%s\n\nsection: %s\ntier: %s\n" "$section" "$text" "$section" "$tier" > "$target_dir/$(printf '%04d' $entry_id)_entry.md"

    [ $entry_id -le 10 ] && echo "   $emoji [$section] $text"
  fi
done < "$GLOBAL"

echo ""
echo "   Done: $hot hot, $warm warm, $cold cold entries"
echo ""
echo "   Hot entries are injected into every Pi session."
echo "   Warm entries are searchable via memory_search tool."
echo "   Cold entries are archived."
