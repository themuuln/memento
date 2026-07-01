"""
from __future__ import annotationsmemory parse — validate and inspect canonical memory entries."""

from typing import Any

from memory_cli.core.parser import parse_memory_file, validate_entries, count_by_kind
from memory_cli.constants import GLOBAL_MEM_PATH


def run(
    config: dict,
    adapters: list[str],
    validate: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """
from __future__ import annotationsParse memories.md and report entry breakdown."""
    result: dict[str, Any] = {
        "command": "parse",
        "status": "ok",
        "source": GLOBAL_MEM_PATH,
    }
    
    entries = parse_memory_file(GLOBAL_MEM_PATH)
    result["total_entries"] = len(entries)
    result["by_kind"] = count_by_kind(entries)
    
    if validate:
        warnings = validate_entries(entries)
        result["warnings"] = warnings
        result["valid"] = len(warnings) == 0
    
    if verbose:
        result["entries"] = [
            {
                "id": e.id,
                "kind": e.kind,
                "section": " > ".join(e.section_path),
                "timestamp": e.timestamp,
                "content": e.content[:80],
                "lines": f"{e.line_start}-{e.line_end}",
            }
            for e in entries
        ]
    
    return result
