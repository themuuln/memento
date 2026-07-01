from __future__ import annotations
"""AbstractMemoryAdapter — pluggable backend interface."""

from abc import ABC, abstractmethod
from typing import Any


class AbstractMemoryAdapter(ABC):
    """Pluggable backend adapter for the memory CLI.
    
    Each adapter wraps one storage backend (flat file, MCP graph, etc.)
    and implements read/write/delete/count operations.
    
    Adapter errors are NEVER fatal to a command. The pattern is:
    file is source of truth; graph is best-effort enhancement.
    
    Capabilities control how the adapter participates in commands:
      - "read": eligible for recall/search/logging
      - "write": eligible for ingest/consolidate/index/store
      - "index": eligible for search index rebuild
    """
    
    name: str = "base"
    capabilities: set[str] = {"read", "write"}

    def initialize(self, config: dict) -> None:
        """Called once before any operations. Config is the full config dict."""

    def shutdown(self) -> None:
        """Called once on process exit. Close connections, flush buffers."""

    @abstractmethod
    def write(self, entry: dict) -> bool:
        """Write a single memory entry.
        
        Args:
            entry: {content, category, timestamp, target_section, source, ...}
        Returns:
            True on success.
        """

    @abstractmethod
    def read(self, query: str, **filters) -> list[dict]:
        """Search/read entries matching query.
        
        Args:
            query: Search string
            **filters: source, category, section, limit, context_lines, ...
        Returns:
            List of entry dicts.
        """

    @abstractmethod
    def delete(self, entry_ids: list[str]) -> int:
        """Delete entries by identifier.
        
        Returns:
            Count of entries deleted.
        """

    @abstractmethod
    def count(self) -> dict:
        """Return stats: total, by_category, by_section, file_sizes, ..."""

    def health(self) -> dict:
        """Return {ok: bool, issues: [...]}. Default: always ok."""
        return {"ok": True, "issues": []}

    def write_batch(self, entries: list[dict]) -> int:
        """Write multiple entries. Default: loop write()."""
        return sum(1 for e in entries if self.write(e))


def register_adapter(name: str, cls: type[AbstractMemoryAdapter]) -> None:
    """Register an adapter class for CLI --adapter resolution."""
    _REGISTRY[name] = cls


def resolve_adapters(
    requested: list[str], config: dict,
    capability: str | None = None,
) -> list[AbstractMemoryAdapter]:
    """Resolve adapter names to instances, optionally filtering by capability.
    
    If requested is empty or contains "all", return all registered adapters
    that match the requested capability (or all, if no capability specified).
    """
    if not requested or "all" in requested:
        names = list(_REGISTRY.keys())
    else:
        names = requested
    
    instances: list[AbstractMemoryAdapter] = []
    for name in names:
        cls = _REGISTRY.get(name)
        if cls is None:
            continue
        adapter = cls()
        # Check capability match
        if capability and capability not in adapter.capabilities:
            continue
        adapter.initialize(config)
        instances.append(adapter)
    return instances


_REGISTRY: dict[str, type[AbstractMemoryAdapter]] = {}
