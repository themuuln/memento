from __future__ import annotations
"""SearchAdapter — vector/semantic search via SQLite FTS5.

write() and delete() are intentionally no-ops — this is an index/retrieval
adapter, not storage. The search index is rebuilt from canonical memory
sources via `memory index --search --rebuild`.
"""

import os
from typing import Any

from memory_cli.adapters.base import AbstractMemoryAdapter, register_adapter
from memory_cli.core.search_index import SearchIndex, SEARCH_DB_DIR


class SearchAdapter(AbstractMemoryAdapter):
    """SQLite FTS5 search index adapter.
    
    Read-only retrieval adapter. Index is rebuilt from canonical markdown
    sources via `memory index --search --rebuild`.
    """
    
    name = "search"
    capabilities = {"read"}  # NOT write — search is a read-only index
    
    def __init__(self):
        self._index: SearchIndex | None = None
    
    def initialize(self, config: dict) -> None:
        try:
            self._index = SearchIndex()
            self._index.open()
        except Exception:
            self._index = None
    
    def shutdown(self) -> None:
        if self._index:
            self._index.close()
    
    def write(self, entry: dict) -> bool:
        """No-op — search is a read-only retrieval/index adapter.
        
        The search index is rebuilt from canonical memory sources via
        `memory index --search --rebuild`. It is NOT a write target.
        """
        return False
    
    def delete(self, entry_ids: list[str]) -> int:
        """No-op — deletion happens at the source (memories.md)."""
        return 0
    
    def read(self, query: str, **filters) -> list[dict]:
        """Search the FTS5 index.
        
        Only returns results if query is non-empty (FTS5 requires a query).
        With empty query, returns empty list (use file adapter for listing).
        """
        if not self._index or not query or not query.strip():
            return []
        
        limit = filters.get("limit", 20)
        
        try:
            return self._index.search(query, limit=limit)
        except Exception:
            return []
    
    def count(self) -> dict:
        """Return index stats."""
        if self._index:
            return self._index.count()
        return {"total": 0, "note": "search index not open"}
    
    def health(self) -> dict:
        """Return health check info."""
        if not self._index:
            return {"ok": False, "issues": ["Search index not initialized"]}
        
        info = self._index.health()
        issues = info.get("issues", [])
        
        # Check if search DB exists
        if not os.path.isdir(SEARCH_DB_DIR):
            issues.append("Search DB directory missing — run `memory index --search --rebuild`")
        
        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "total": info.get("total", 0),
        }


register_adapter("search", SearchAdapter)
