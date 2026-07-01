# Phase 0 Complete: Memory System Audit & Cleanup
> Date: 2026-07-01

## Manifest of All Memory Mechanisms

### ACTIVE — Working, wired, fresh data

| # | System | Type | Last Update | Size | Location |
|---|--------|------|-------------|------|----------|
| 1 | **Flat file memories** | Source of truth | Jun 30 | 5.5KB | `~/.agent-memory/global/memories.md` |
| 2 | **MCP knowledge graph** | Entity-relation | Jun 30 | 9KB | `~/.agent-memory/graph/memory-graph.jsonl` |
| 3 | **Archive tiers** | hot/warm/cold | Jun 30 | 276KB | `~/.agent-memory/archive/entries/` |
| 4 | **memory-capture.py** | UserPromptSubmit hook | Active | 18KB | `~/.factory/hooks/memory-capture.py` |
| 5 | **consolidate-session.sh** | SessionEnd hook | Active | 9.4KB | `~/.agent-memory/scripts/consolidate-session.sh` |
| 6 | **load-context.sh** | SessionStart hook | Active | 6.1KB | `~/.factory/hooks/load-context.sh` |
| 7 | **mcp_bridge.py** | MCP stdio bridge | Active | 10.7KB | `~/.factory/hooks/mcp_bridge.py` |
| 8 | **consolidate.py** | On-demand CLI | Active | 34KB | `~/.factory/hooks/consolidate.py` |
| 9 | **consolidate-memory.py** | On-demand CLI | Active | 12.7KB | `~/.factory/hooks/consolidate-memory.py` |
| 10 | **memory-dedup.py** | On-demand CLI | Active | 11KB | `~/.factory/hooks/memory-dedup.py` |
| 11 | **forget.py** | On-demand CLI | Active | 17KB | `~/.factory/hooks/forget.py` |
| 12 | **save-precompact-checkpoint.sh** | PreCompact hook | Active | 7KB | `~/.factory/hooks/save-precompact-checkpoint.sh` |
| 13 | **session-end-memory.sh** | SessionEnd hook | Active | 747B | `~/.factory/hooks/session-end-memory.sh` |
| 14 | **ai-memory-consolidate.sh** | PreCompact hook | Active | 655B | `~/.factory/hooks/ai-memory-consolidate.sh` |
| 15 | **consolidation log** | Observability | Jul 1 | 344B | `~/.agent-memory/logs/consolidation.log` |

### STALE — Needs review

| # | System | Stale Since | Size | Note |
|---|--------|-------------|------|------|
| 1 | **pi-hermes-memory runtime** | Jun 6 | 4.3MB | `/private/tmp/pi-runtime/pi-hermes-memory/sessions.db` — 98 sessions, 504 memories. Data may be worth extracting. |
| 2 | **pi.bak/memory/memory.db** | Jun 9 (last content) | 84KB | FTS5 database with 17 facts, 6 lessons, 24 events. WAL still being written — something touches it. |
| 3 | **pi.bak (full backup)** | Jun 30 | 5.3GB | Git repo of pi-config. Not harmful but large. |

### DEAD — Quarantined or Fixed

| # | System | Size | Action Taken |
|---|--------|------|-------------|
| 1 | `~/.config.9217f467/` | 2.4MB | → `~/.agent-memory/archive/quarantine/` |
| 2 | `~/.config.5230d841/` | 2.4MB | → `~/.agent-memory/archive/quarantine/` |
| 3 | `agent-memory-disabled` extension | — | Removed dead reference from settings.json |
| 4 | `setup-command` extension | — | Removed dead reference from settings.json |
| 5 | `session-end-memory-capture.sh` hook ref | — | Fixed name → `session-end-memory.sh` in hooks.json |
| 6 | `agent-done.sh` hook ref (Stop/SubagentStop) | — | Removed dead hook references from hooks.json |
| 7 | `~/.factory/AGENTS.md` | — | Removed broken symlink to empty file |
| 8 | `~/agent-workflow/wiki/` | — | Directory doesn't exist, no action needed |

## Issues Found

### Critical
- **Hard-coded API key** in `consolidate-session.sh` (line with `API_KEY="sk-..."`)
- **All consolidations returning EMPTY/NOTHING** — capture hooks may not be firing in Pi sessions
- **No compaction ingest** — messages lost when Pi compacts context
- **Search is grep-only** — no vector/semantic search

### Moderate
- **Hot tier oversubscribed**: config says max 20, actual 26 files
- **Graph has 1 malformed line**: two JSON objects concatenated without newline
- **All 5 project dirs empty**: no `memories.md` files populated
- **3 consolidation scripts overlap** (consolidate.py, consolidate-memory.py, consolidate-session.sh)
- **Dual memory paths** persist: `~/.agent-memory/` (primary) and legacy `~/.factory/memories.md`

### Minor
- Archive entries average ~120B — very concise, may lack context
- Some graph entities duplicate flat-file entries
- consolidation.log records skip/no-ops — normal when no decisions made in short sessions

## Next Phase Ready

Phase 0 complete. Ready for Phase 1 (Stabilize):
1. Move API key to env variable
2. Add file locks for concurrent writes
3. Add atomic writes for markdown + JSONL
4. Add minimal trace logging
5. Add fixture tests
