#!/usr/bin/env python3
"""Extract memories from pi-hermes-memory SQLite DB into agent-memory.

Uses the FlatFileAdapter directly to append entries to the correct sections,
then rebuilds the FTS5 index once. Much faster than per-entry CLI calls.

Run: python3 extract-hermes.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time

# ── Paths ─────────────────────────────────────────────────────────
HERMES_DB = "/private/tmp/pi-runtime/pi-hermes-memory/sessions.db"
AGENT_MEMORY_DIR = os.environ.get(
    "AGENT_MEMORY_DIR",
    os.path.expanduser("~/.agent-memory"),
)

# Map pi-hermes (target, category) → section key for _category_to_section
CATEGORY_MAP = {
    ("memory", None): "learning",
    ("memory", "preference"): "preference",
    ("memory", "failure"): "gotcha",
    ("memory", "tool-quirk"): "gotcha",
    ("user", None): "preference",
    ("user", "preference"): "preference",
    ("failure", None): "gotcha",
    ("failure", "failure"): "gotcha",
    ("failure", "tool-quirk"): "gotcha",
    ("failure", "insight"): "learning",
    ("failure", "correction"): "learning",
    ("failure", "convention"): "convention",
}


def map_category(target: str, category: str | None) -> str:
    return CATEGORY_MAP.get((target, category), "learning")


def main() -> int:
    t0 = time.time()

    if not os.path.exists(HERMES_DB):
        print(f"❌ pi-hermes database not found: {HERMES_DB}", flush=True)
        return 1

    # Import agent-memory modules
    sys.path.insert(0, AGENT_MEMORY_DIR)
    from memory_cli.core.config import load_config
    from memory_cli.core.search_index import SearchIndex
    from memory_cli.core.parser import parse_memory_file
    from memory_cli.constants import GLOBAL_MEM_PATH
    from memory_cli.adapters.file import FlatFileAdapter
    from memory_cli.adapters.graph import GraphAdapter
    
    # Reuse the canonical section name mapping from ingest
    def _cat_to_section(cat: str) -> str:
        mapping = {
            "decision": "Validated Approaches",
            "preference": "User Preferences",
            "learning": "Key Learnings",
            "gotcha": "Gotchas & Traps",
            "rule": "Hard Rules",
            "convention": "Conventions",
            "architecture": "Architecture Decisions",
            "workflow": "Workflows",
            "project-fact": "Project Conventions",
        }
        return mapping.get(cat, "Key Learnings")

    # ── Read from SQLite ──────────────────────────────────────────
    conn = sqlite3.connect(HERMES_DB)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    rows = conn.execute(
        "SELECT id, project, target, category, content, created "
        "FROM memories ORDER BY created ASC"
    ).fetchall()
    conn.close()

    print(f"📦 Read {total} memories from pi-hermes database\n", flush=True)

    # ── Initialize adapters ───────────────────────────────────────
    config_path = os.path.join(AGENT_MEMORY_DIR, "config.json")
    config = load_config(config_path)
    file_adapter = FlatFileAdapter()
    file_adapter.initialize(config)
    graph_adapter = GraphAdapter()
    graph_adapter.initialize(config)

    stats = {"written": 0, "skipped": 0, "by_target": {}}

    for row in rows:
        content = row["content"].strip()
        if not content:
            stats["skipped"] += 1
            continue
        if len(content) > 10000:
            print(f"  ⚠️  Skipping memory #{row['id']}: {len(content)}c too long", flush=True)
            stats["skipped"] += 1
            continue

        target = row["target"]
        category = row["category"]
        section_key = map_category(target, category)

        key = f"{target}/{category or 'none'}"
        stats["by_target"][key] = stats["by_target"].get(key, 0) + 1

        date = row["created"] or "2026-06-05"
        stats["written"] += 1

        # Write via FlatFileAdapter — handles section routing + formatting
        section_name = _cat_to_section(section_key)
        file_adapter.write({
            "content": content,
            "category": section_key,
            "target_section": section_name,
            "timestamp": date,
            "source": "pi-hermes-extract",
        })

        # Also write to graph adapter
        graph_adapter.write({
            "content": content,
            "category": section_key,
            "target_section": section_name,
            "timestamp": date,
            "source": "pi-hermes-extract",
        })

        if stats["written"] % 100 == 0:
            pct = int(stats["written"] / total * 100) if total else 0
            print(f"  ... {stats['written']}/{total} ({pct}%)", flush=True)

    # ── Rebuild FTS5 search index (single pass) ───────────────────
    print(f"\n🔨 Rebuilding FTS5 search index...", flush=True)
    idx = SearchIndex()
    idx.open()
    parsed = parse_memory_file(GLOBAL_MEM_PATH)
    entries_for_index = [
        {
            "id": e.id, "content": e.content,
            "search_text": e.search_text,
            "section_path": e.section_path,
            "kind": e.kind, "timestamp": e.timestamp,
            "source_path": e.source_path,
            "line_start": e.line_start,
            "content_hash": e.content_hash,
        }
        for e in parsed
    ]
    idx.rebuild(entries_for_index)
    idx.close()

    entry_count = len(parsed)
    elapsed = time.time() - t0

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n✅ Done! ({elapsed:.1f}s)", flush=True)
    print(f"   Written:       {stats['written']}", flush=True)
    print(f"   Skipped:       {stats['skipped']}", flush=True)
    print(f"   Total entries: {entry_count}", flush=True)
    print(f"\n   By source type:", flush=True)
    for k, v in sorted(stats["by_target"].items()):
        print(f"     {k}: {v}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
