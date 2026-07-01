from __future__ import annotations
"""memory index — rebuild archive tiers from memories.md."""

import os
import shutil
import re
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.constants import (
    GLOBAL_MEM_PATH,
    HOT_DIR,
    WARM_DIR,
    COLD_DIR,
    TIER_DEFAULTS,
)
from memory_cli.core.atomic import read_file_safe


def run(
    config: dict,
    adapters: list[str],
    dry_run: bool = False,
    search_rebuild: bool = False,
    archive: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Rebuild archive tiers and/or search index from memories.md."""
    result: dict[str, Any] = {
        "command": "index",
        "status": "ok",
        "archive": None,
        "search": None,
    }
    
    # ── Search index rebuild ──────────────────────────────────
    if search_rebuild:
        result["search"] = _rebuild_search_index(config, verbose)
    
    # ── Archive tier rebuild ──────────────────────────────────
    if archive or not search_rebuild:
        # Default mode if no flags: rebuild archive tiers
        result["archive"] = _rebuild_archive_tiers(dry_run, verbose)
    
    return result


def _rebuild_search_index(config: dict, verbose: bool) -> dict[str, Any]:
    """Rebuild the FTS5 search index from canonical parser output."""
    from memory_cli.core.parser import parse_memory_file
    from memory_cli.core.search_index import SearchIndex
    
    result: dict[str, Any] = {"status": "ok"}
    
    # Parse canonical entries
    from memory_cli.constants import GLOBAL_MEM_PATH
    entries = parse_memory_file(GLOBAL_MEM_PATH)
    result["entries_parsed"] = len(entries)
    
    entry_dicts = [
        {
            "id": e.id,
            "content": e.content,
            "search_text": e.search_text,
            "section_path": e.section_path,
            "kind": e.kind,
            "timestamp": e.timestamp,
            "source_path": e.source_path,
            "line_start": e.line_start,
            "content_hash": e.content_hash,
        }
        for e in entries
    ]
    
    # Rebuild search index
    idx = SearchIndex()
    try:
        idx.open()
        stats = idx.rebuild(entry_dicts)
        result.update(stats)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        idx.close()
    
    return result


def _rebuild_archive_tiers(dry_run: bool, verbose: bool) -> dict[str, Any]:
    """Rebuild hot/warm/cold archive tiers from memories.md."""
    result: dict[str, Any] = {"movements": [], "tiers": {}}
    
    # Read all entries from memories.md
    entries = _parse_entries(read_file_safe(GLOBAL_MEM_PATH))
    
    # Classify into tiers
    tier_map: dict[str, list[dict]] = {"hot": [], "warm": [], "cold": []}
    now = datetime.now(timezone.utc)
    
    for entry in entries:
        section = entry.get("section", "")
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d")
            days_old = (now - ts).days
        except (ValueError, TypeError):
            days_old = 0
        
        tier = _classify_tier(section, days_old)
        tier_map[tier].append(entry)
    
    # Apply max_entries caps
    for tier_name, tier_cfg in TIER_DEFAULTS.items():
        max_e = tier_cfg["max_entries"]
        tier_list = tier_map[tier_name]
        tier_list.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        
        if len(tier_list) > max_e:
            # Overflow goes to next colder tier
            overflow = tier_list[max_e:]
            tier_list = tier_list[:max_e]
            
            target = "warm" if tier_name == "hot" else "cold"
            tier_map[target].extend(overflow)
            
            for o in overflow:
                result["movements"].append({
                    "entry": o.get("content", "")[:50],
                    "from": tier_name,
                    "to": target,
                    "reason": f"oversubscribed (max {max_e})",
                })
        
        tier_map[tier_name] = tier_list
    
    # Report
    before = _tier_counts()
    after = {t: len(e) for t, e in tier_map.items()}
    result["tiers"] = {
        "before": before,
        "after": after,
        "files": {t: [e.get("content", "")[:40] for e in entries] for t, entries in tier_map.items()},
    }
    
    # Write archive entries
    if not dry_run:
        for tier_name, entries in tier_map.items():
            tier_dir = _tier_dir(tier_name)
            os.makedirs(tier_dir, exist_ok=True)
            
            # Clear existing
            for f in os.listdir(tier_dir):
                fpath = os.path.join(tier_dir, f)
                if os.path.isfile(fpath):
                    os.unlink(fpath)
            
            # Write new
            for i, entry in enumerate(entries):
                entry_path = os.path.join(tier_dir, f"{i+1:04d}_entry.md")
                with open(entry_path, "w") as f:
                    f.write(f"## {entry.get('section', 'Uncategorized')}\n\n")
                    f.write(f"- [{entry.get('timestamp', '')}] {entry.get('content', '')}\n")
    
    return result


def _parse_entries(content: str) -> list[dict]:
    """Parse memories.md into list of {section, content, timestamp}."""
    entries: list[dict] = []
    current_section = ""
    
    pattern = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] (.+)$", re.MULTILINE)
    
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            current_section = stripped[3:]
        m = pattern.match(stripped)
        if m:
            entries.append({
                "section": current_section,
                "timestamp": m.group(1),
                "content": m.group(2).strip(),
            })
    
    return entries


def _classify_tier(section: str, days_old: int) -> str:
    if section in ("Hard Rules", "User Preferences"):
        return "hot"
    if days_old > 90:
        return "cold"
    if section in ("Workflows",):
        return "cold"
    return "warm"


def _tier_counts() -> dict:
    counts = {}
    for name, path in [("hot", HOT_DIR), ("warm", WARM_DIR), ("cold", COLD_DIR)]:
        try:
            counts[name] = len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
        except OSError:
            counts[name] = 0
    return counts


def _tier_dir(name: str) -> str:
    mapping = {"hot": HOT_DIR, "warm": WARM_DIR, "cold": COLD_DIR}
    return mapping[name]
