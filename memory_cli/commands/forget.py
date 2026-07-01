from __future__ import annotations
"""memory forget — delete entries from all adapters."""

from typing import Any

from memory_cli.adapters import resolve_adapters


def run(
    config: dict,
    adapters: list[str],
    query: str,
    apply: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Delete memory entries matching query.
    
    By default runs in dry-run mode (preview only).
    Use --apply to actually delete.
    """
    result: dict[str, Any] = {
        "command": "forget",
        "status": "dry_run",
        "query": query,
        "preview": [],
        "deleted": 0,
    }
    
    # Preview: search first
    for a in resolve_adapters(adapters, config, capability="write"):
        matches = a.read(query, limit=50)
        for m in matches:
            result["preview"].append(m)
    
    if not result["preview"]:
        result["status"] = "no_match"
        return result
    
    if not apply:
        # Dry-run: just return preview
        return result
    
    # Actually delete
    total = 0
    for a in resolve_adapters(adapters, config, capability="write"):
        count = a.delete([query])
        total += count
    
    # Auto-rebuild FTS5 search index after delete
    if total > 0:
        try:
            from memory_cli.core.search_index import SearchIndex
            from memory_cli.core.parser import parse_memory_file
            from memory_cli.constants import GLOBAL_MEM_PATH
            
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
        except Exception:
            pass
    
    result["status"] = "ok"
    result["deleted"] = total
    
    return result
