# Memento — Installation Guide

## Prerequisites

- **Python 3.9+** on `PATH`
- **Pi Coding Agent** (`pi`) installed
- **Git** for cloning

## Quick Install

```bash
# 1. Clone
git clone git@github.com:themuuln/memento.git ~/.agent-memory

# 2. Install Python package
pip3 install -e ~/.agent-memory

# 3. Symlink CLI (if not already on PATH)
ln -sf ~/.agent-memory/memory ~/.local/bin/memory

# 4. Install Pi extensions
mkdir -p ~/.pi/agent/extensions
cp ~/.agent-memory/extensions/memory-tools.ts ~/.pi/agent/extensions/
cp ~/.agent-memory/extensions/memory-compaction-capture.ts ~/.pi/agent/extensions/

# 5. Verify
memory status
```

Or run the setup script:

```bash
bash ~/.agent-memory/setup.sh
```

## What Gets Installed

```
~/.agent-memory/          # Repo root
├── memory                # CLI entry point script
├── memory_cli/           # Python package (7 commands)
├── extensions/
│   ├── memory-tools.ts           # Pi extension: tools + commands + auto-recall
│   └── memory-compaction-capture.ts  # Pi extension: compaction capture
├── scripts/
│   └── consolidate-session.sh    # Shell helper for session consolidation
├── tests/                # 105 pytest tests
├── config.json           # Default configuration
└── setup.sh              # One-command installer
```

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_MEMORY_DIR` | `~/.agent-memory` | Root directory |
| `MEMORY_CLI` | `memory` | CLI binary path |
| `OPENCODE_GO_API_KEY` | *(required)* | API key for LLM consolidation |

### Config File (`config.json`)

Key settings:
- `capture.triggers` — keyword phrases that trigger memory capture
- `capture.natural_language` — NLP patterns for auto-categorization
- `llm.model` — model for session consolidation (default: `deepseek-v4-flash`)
- `dedup.threshold` — Jaccard similarity threshold (0.0–1.0)

## Updating

```bash
cd ~/.agent-memory && git pull
cp extensions/memory-tools.ts ~/.pi/agent/extensions/
cp extensions/memory-compaction-capture.ts ~/.pi/agent/extensions/
```
