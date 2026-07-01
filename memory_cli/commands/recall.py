"""memory recall — search memory entries across adapters."""
from __future__ import annotations

from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.core.hybrid import HybridRetriever


def run(
    config: dict,
    adapters: list[str],
    query: str | None = None,
    limit: int = 20,
    context: int = 0,
    section: str | None = None,
    hybrid: bool = True,
    verbose: bool = False,
) -> dict[str, Any]:
    """Search memory entries.
    
    Default mode: hybrid (FTS5 + grep via RRF).
    --no-hybrid: grep-only via file adapter.
    """
    result: dict[str, Any] = {
        "command": "recall",
        "query": query or "",
        "status": "ok",
        "matches": 0,
        "results": [],
    }
    
    if not query:
        result["status"] = "no_query"
        return result
    
    if not hybrid:
        # Grep-only mode (file adapter)
        seen = set()
        filters = {"limit": limit, "context_lines": context}
        if section:
            filters["section"] = section
        
        for a in resolve_adapters(adapters or ["file"], config, capability="read"):
            if a.name == "search" and not adapters:
                continue
            matches = a.read(query, **filters)
            for m in matches:
                dedup_key = str(m.get("content", m.get("entity_name", "")))[:100]
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    result["results"].append(m)
        
        result["matches"] = len(result["results"])
        if limit and len(result["results"]) > limit:
            result["results"] = result["results"][:limit]
            result["matches"] = len(result["results"])
    else:
        # Hybrid search: grep + FTS5 merged via RRF (default)
        retriever = HybridRetriever(config)
        hybrid_result = retriever.search(
            query=query,
            limit=limit,
            adapters=adapters or ["file", "search"],
        )
        result["results"] = hybrid_result.get("results", [])
        result["matches"] = len(result["results"])
        result["hybrid"] = hybrid_result.get("hybrid", {})
    
    return result
