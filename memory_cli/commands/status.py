from __future__ import annotations
"""memory status — observability and health check."""

import os
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.constants import (
    GLOBAL_MEM_PATH,
    GRAPH_FILE,
    GLOBAL_RULES_PATH,
    GLOBAL_PREFERENCES_PATH,
    ARCHIVE_DIR,
    HOT_DIR,
    WARM_DIR,
    COLD_DIR,
    TIER_DEFAULTS,
    CONSOLIDATION_LOG,
    CLI_LOG,
    COMPACTION_INBOX_DIR,
    COMPACTION_PROCESSED_DIR,
)


def run(
    config: dict,
    adapters: list[str],
    health: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Report memory system status.
    
    Args:
        health: if True, return exit code 1 if any issues found.
    """
    result: dict[str, Any] = {
        "command": "status",
        "status": "ok",
    }
    
    file_adapter = graph_adapter = None
    for a in resolve_adapters(adapters, config, capability="read"):
        if a.name == "file":
            file_adapter = a
        elif a.name == "graph":
            graph_adapter = a
    
    # File stats
    if file_adapter:
        result["files"] = file_adapter.count()
        result["files"]["memories.md"] = _file_info(GLOBAL_MEM_PATH)
        result["files"]["rules.md"] = _file_info(GLOBAL_RULES_PATH)
        result["files"]["preferences.md"] = _file_info(GLOBAL_PREFERENCES_PATH)
    
    # Graph stats
    if graph_adapter:
        result["graph"] = graph_adapter.count()
    
    # Archive tiers
    result["tiers"] = {
        "hot": _tier_info(HOT_DIR, TIER_DEFAULTS["hot"]["max_entries"]),
        "warm": _tier_info(WARM_DIR, TIER_DEFAULTS["warm"]["max_entries"]),
        "cold": _tier_info(COLD_DIR, TIER_DEFAULTS["cold"]["max_entries"]),
    }
    
    # Log info
    result["logs"] = {
        "consolidation.log": _file_info(CONSOLIDATION_LOG),
        "memory-cli.log": _file_info(CLI_LOG),
    }
    
    # Compaction inbox
    result["inbox"] = _inbox_info()
    
    # Health checks
    issues: list[dict] = []
    
    # Hot tier oversubscribed?
    hot = result["tiers"]["hot"]
    if hot.get("over"):
        issues.append({
            "severity": "warning",
            "message": f"Hot tier oversubscribed: {hot['count']}/{hot['max']} entries",
        })
    
    # Check adapters
    for a in resolve_adapters(adapters, config, capability="read"):
        h = a.health()
        for iss in h.get("issues", []):
            issues.append({"severity": "warning", "message": f"[{a.name}] {iss}"})
    
    result["issues"] = issues
    result["health"] = "ok" if not issues else "warnings"
    
    if health and issues:
        result["status"] = "issues_found"
    
    return result


def _inbox_info() -> dict:
    """Report on compaction inbox state."""
    pending = 0
    processed = 0
    
    for d, name in [(COMPACTION_INBOX_DIR, "pending"), (COMPACTION_PROCESSED_DIR, "processed")]:
        try:
            files = [f for f in os.listdir(d) if f.endswith(".jsonl") and os.path.isfile(os.path.join(d, f))]
            if name == "pending":
                pending = len(files)
            else:
                processed = len(files)
        except OSError:
            pass
    
    return {
        "pending_count": pending,
        "processed_count": processed,
        "pending_dir": COMPACTION_INBOX_DIR,
        "processed_dir": COMPACTION_PROCESSED_DIR,
    }


def _file_info(path: str) -> dict:
    try:
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(
            os.path.getmtime(path), timezone.utc
        ).isoformat()
        return {"size_bytes": size, "last_modified": mtime, "exists": True}
    except OSError:
        return {"size_bytes": 0, "last_modified": None, "exists": False}


def _tier_info(tier_dir: str, max_entries: int) -> dict:
    try:
        files = [
            f for f in os.listdir(tier_dir)
            if os.path.isfile(os.path.join(tier_dir, f))
        ]
        count = len(files)
        return {
            "count": count,
            "max": max_entries,
            "over": count > max_entries,
            "files": sorted(files)[:10],  # first 10
        }
    except OSError:
        return {"count": 0, "max": max_entries, "over": False, "files": []}
