# Memento

> Local-first persistent memory system for AI coding agents.

Memento gives **Pi** (and other coding agents) durable memory that survives session restarts. It captures, stores, and retrieves knowledge using a hybrid FTS5+grep search — no cloud, no dependencies, just local files.

## Quick Start

```bash
git clone git@github.com:themuuln/memento.git ~/.agent-memory
pip3 install -e ~/.agent-memory
bash ~/.agent-memory/setup.sh
```

Restart Pi — you'll see memory recalled automatically when you ask questions.

## Features

### For Day-to-Day Use

| What | How |
|---|---|
| **Auto-recall** | When you ask a question, relevant memories are injected as context — no manual search needed |
| **Store memories** | `memory_remember` LLM tool or `remember this: ...` in chat |
| **Search** | `memory_recall <query>` tool or `/memory-recall <query>` slash command |
| **Status** | `memory_status` tool or `/memory-status` slash command |
| **Session cleanup** | Compaction messages captured automatically; learnings consolidated on quit |

### For Power Users — CLI

```
memory status          # Health check + entry count
memory recall <query>  # Hybrid search (FTS5+grep via RRF)
memory ingest <text>   # Capture with pattern detection
memory doctor          # Diagnostics + --repair
memory inbox           # Pending compaction items
memory consolidate     # LLM-powered session analysis
memory forget <query>  # Remove entries
memory index --rebuild # Rebuild FTS5 index
```

## Under the Hood

```
~/.agent-memory/
├── memory                   # CLI entry point
├── memory_cli/              # Python package (26 files, 7 commands)
│   ├── cli.py               # Argparse CLI
│   ├── adapters/             # Flat file, graph, search backends
│   ├── commands/             # ingest, recall, consolidate, forget, etc.
│   └── core/                 # parser, dedup, hybrid search, FTS5 index
├── extensions/               # Pi TypeScript extensions
│   ├── memory-tools.ts              # 3 LLM tools, 4 slash commands, auto-recall, shutdown hook
│   └── memory-compaction-capture.ts  # Captures messages before compaction
├── global/memories.md        # Source of truth (durable markdown)
├── graph/memory-graph.jsonl  # Knowledge graph (MCP compatible)
├── config.json               # Triggers, patterns, LLM settings
├── tests/                    # 105 pytest tests
├── setup.sh                  # One-command installer
└── INSTALL.md                # Full installation guide
```

### Search Architecture

Hybrid retriever combining:
- **FTS5** — SQLite full-text search with Porter stemming
- **Grep** — Line-by-line regex fallback
- **RRF ranking** — Reciprocal Rank Fusion merges both results
- **OR fallback** — If AND query returns 0 results, auto-retry with OR
- **Alias expansion** — `nextjs`→`next.js`, `tailwind`→`tailwindcss`, etc.

### Storage

Dual-write to flat markdown + MCP knowledge graph JSONL. FTS5 index is auto-rebuilt after every write.

## CLI Commands

| Command | Description |
|---|---|
| `status` | Health check, entry count, section breakdown |
| `ingest` | Capture memory from stdin/file with trigger detection |
| `recall` | Search memories (hybrid by default, `--no-hybrid` for grep-only) |
| `forget` | Remove entries (`--apply` to confirm) |
| `index` | Rebuild FTS5 search index |
| `inbox` | Show/process pending compaction items |
| `consolidate` | LLM-powered session transcript analysis |
| `parse` | Parse and validate memories.md |
| `doctor` | Deep diagnostics with `--repair` |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_MEMORY_DIR` | `~/.agent-memory` | Root directory |
| `MEMORY_CLI` | `memory` | CLI binary override |
| `OPENCODE_GO_API_KEY` | *(required)* | For LLM consolidation via pi --print |

## License

MIT
