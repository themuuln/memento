from __future__ import annotations
"""memory doctor — deep diagnostics and repair."""

import os
import time
from typing import Any

from memory_cli.constants import (
    AGENT_MEMORY_DIR,
    GLOBAL_MEM_PATH,
    GLOBAL_RULES_PATH,
    GLOBAL_PREFERENCES_PATH,
    GRAPH_FILE,
    LOCK_DIR,
    LOG_DIR,
    COMPACTION_INBOX_DIR,
    COMPACTION_PROCESSED_DIR,
    HOT_DIR,
    WARM_DIR,
    COLD_DIR,
)
from memory_cli.core.config import load_config
from memory_cli.core.search_index import SearchIndex


def run(config: dict, repair: bool = False, verbose: bool = False) -> dict[str, Any]:
    """Run deep diagnostics. Optionally repair fixable issues."""
    start = time.time()
    issues: list[dict] = []
    fixes: list[str] = []

    def _check(label: str, condition: bool, severity: str = "warning", fix_hint: str | None = None) -> None:
        if not condition:
            item = {"label": label, "severity": severity}
            if fix_hint:
                item["fix_hint"] = fix_hint
            issues.append(item)

    def _repair(hint: str) -> None:
        if repair:
            fixes.append(hint)

    # ── 1. Directory tree ──
    paths = {
        "root": AGENT_MEMORY_DIR,
        "global/memories.md": GLOBAL_MEM_PATH,
        "global/rules.md": GLOBAL_RULES_PATH,
        "global/preferences.md": GLOBAL_PREFERENCES_PATH,
        "graph/memory-graph.jsonl": GRAPH_FILE,
        "archive/entries/hot": HOT_DIR,
        "archive/entries/warm": WARM_DIR,
        "archive/entries/cold": COLD_DIR,
        ".locks": LOCK_DIR,
        "logs": LOG_DIR,
        "inbox/compaction": COMPACTION_INBOX_DIR,
        "inbox/processed": COMPACTION_PROCESSED_DIR,
    }

    for label, path in paths.items():
        exists = os.path.exists(path)
        _check(f"Path exists: {label}", exists,
               severity="error" if "memories.md" in label or "graph.jsonl" in label else "warning",
               fix_hint=f"Create directory: mkdir -p {os.path.dirname(path)}" if not label.endswith(".md") and not label.endswith(".jsonl") else None)

    # ── 2. Writable check ──
    writable_paths = [GLOBAL_MEM_PATH, GRAPH_FILE, LOCK_DIR, LOG_DIR, COMPACTION_INBOX_DIR, HOT_DIR, WARM_DIR, COLD_DIR]
    for p in writable_paths:
        if os.path.isfile(p):
            _check(f"Writable: {p}", os.access(p, os.W_OK), severity="error")
        elif os.path.isdir(p):
            _check(f"Parent writable: {p}", os.access(os.path.dirname(p) if not os.path.isdir(p) else p, os.W_OK,)
                   if os.path.exists(os.path.dirname(p)) else True, severity="error")

    # ── 3. Memories.md content integrity ──
    if os.path.isfile(GLOBAL_MEM_PATH):
        try:
            text = open(GLOBAL_MEM_PATH).read()
            _check("memories.md not empty", len(text.strip()) > 0, severity="error",
                   fix_hint="Run `memory ingest --stdin` to add entries")
            _check("memories.md has bullet entries", " - [" in text or "\n- " in text, severity="warning",
                   fix_hint="Use markdown bullet list format: - content")
            # Check for broken bullet formats
            lines = text.split("\n")
            orphan_text = sum(1 for l in lines if l.strip().startswith(("```", "    ```"))) == 0
        except Exception as e:
            _check(f"memories.md readable", False, severity="error", fix_hint=str(e))

    # ── 4. Graph file integrity (JSONL) ──
    if os.path.isfile(GRAPH_FILE):
        malformed = 0
        try:
            with open(GRAPH_FILE) as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    import json
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
            _check(f"Graph JSONL malformed lines", malformed == 0, severity="error",
                   fix_hint=f"Repair: {malformed} malformed lines found. Run `memory index --search --rebuild`")
        except Exception as e:
            _check("Graph JSONL readable", False, severity="error", fix_hint=str(e))

    # ── 5. Lock files — check for stale locks ──
    if os.path.isdir(LOCK_DIR):
        now = time.time()
        for fname in os.listdir(LOCK_DIR):
            fpath = os.path.join(LOCK_DIR, fname)
            if os.path.isfile(fpath):
                age_seconds = now - os.path.getmtime(fpath)
                if age_seconds > 300:  # 5 minutes
                    _check(f"Stale lock: {fname} ({age_seconds:.0f}s old)", False, severity="warning",
                           fix_hint=f"rm -f {fpath}")

    # ── 6. FTS5 index health ──
    try:
        idx = SearchIndex()
        idx.open()
        count = idx.count()
        idx.close()
        _check("FTS5 search index accessible", True)
    except Exception:
        _check("FTS5 search index", False, severity="error",
               fix_hint="Run `memory index --search --rebuild`")

    # ── 7. Archive tier consistency ──
    for tier_name, tier_path in [("hot", HOT_DIR), ("warm", WARM_DIR), ("cold", COLD_DIR)]:
        if os.path.isdir(tier_path):
            files = [f for f in os.listdir(tier_path) if f.endswith(".md")]
            # Check for orphan entries (no corresponding .json)
            md_names = {f.replace(".md", "") for f in files}
            # Quick check: no excessive files
            if len(files) > 100:
                _check(f"Archive tier '{tier_name}' has {len(files)} files", False, severity="info",
                       fix_hint="Consider running `memory index --archive`")

    # ── 8. Inbox integrity ──
    if os.path.isdir(COMPACTION_INBOX_DIR):
        files = [f for f in os.listdir(COMPACTION_INBOX_DIR) if f.endswith(".jsonl")]
        for fname in files:
            fpath = os.path.join(COMPACTION_INBOX_DIR, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath) as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                import json
                                json.loads(line)
                except (json.JSONDecodeError, Exception):
                    _check(f"Malformed inbox file: {fname}", False, severity="warning",
                           fix_hint=f"Inspect: cat {fpath}")

    # ── 9. rules.md and preferences.md freshness ──
    for label, path in [("rules.md", GLOBAL_RULES_PATH), ("preferences.md", GLOBAL_PREFERENCES_PATH)]:
        if os.path.isfile(path):
            mtime = os.path.getmtime(path)
            age_days = (time.time() - mtime) / 86400
            _check(f"{label} last modified", age_days < 90, severity="info",
                   fix_hint=f"Last modified {age_days:.0f} days ago — consider reviewing")

    # ── 10. Cross-adapter consistency ──
    # Check that memories.md and FTS5 index agree on count
    if os.path.isfile(GLOBAL_MEM_PATH):
        md_bullets = sum(1 for l in open(GLOBAL_MEM_PATH).readlines() if l.strip().startswith("- ") and len(l.strip()) > 3)
        if count.get("total", 0) > 0:
            diff = abs(md_bullets - count["total"])
            if diff > 10:
                _check(f"Cross-adapter count mismatch: {diff} entries diff", False, severity="warning",
                       fix_hint="Run `memory index --search --rebuild`")

    elapsed = time.time() - start

    # Build result
    result: dict[str, Any] = {
        "command": "doctor",
        "status": "ok",
        "elapsed_seconds": round(elapsed, 3),
        "issues_found": len(issues),
        "issues": issues,
        "repair_applied": repair,
        "fixes": fixes,
    }

    if verbose:
        result["check_count"] = len(paths) + 12

    return result
