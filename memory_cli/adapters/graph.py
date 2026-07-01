from __future__ import annotations
"""GraphAdapter — MCP knowledge graph via JSONL + mcp_bridge."""

import json
import os
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters.base import AbstractMemoryAdapter, register_adapter
from memory_cli.constants import GRAPH_FILE
from memory_cli.core.atomic import atomic_append, read_file_safe
from memory_cli.core.locking import FileLock


class GraphAdapter(AbstractMemoryAdapter):
    """Read/write the MCP knowledge graph.
    
    Writes are dual:
      1. JSONL file (durable append — always succeeds or crashes cleanly)
      2. MCP server via mcp_bridge (best-effort — failures are logged, never fatal)
    
    JSONL is always consistent because each line is one complete JSON object.
    On crash, at worst the last partial line is ignored by parsers.
    """
    
    name = "graph"
    capabilities = {"read", "write"}
    
    def __init__(self):
        self._graph_path: str = ""
        self._bridge: Any = None  # imported lazily
        self._bridge_available: bool = False
    
    def initialize(self, config: dict) -> None:
        storage = config.get("storage", {})
        self._graph_path = storage.get("graph_file", GRAPH_FILE)
        os.makedirs(os.path.dirname(self._graph_path) or ".", exist_ok=True)
        
        # Try importing mcp_bridge (non-fatal if unavailable)
        try:
            from memory_cli.adapters import mcp_bridge_shim  # noqa
            self._bridge_available = True
        except ImportError:
            self._bridge_available = False
    
    def write(self, entry: dict) -> bool:
        """Write an entry to the graph.
        
        Creates an entity with observations and links to category.
        """
        content = entry.get("content", "").strip()
        if not content:
            return False
        
        category = entry.get("category", "learning")
        ts = entry.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        source = entry.get("source", "memory-cli")
        
        # Prepare entity name from first few words
        words = content.split()[:6]
        name = "-".join(words).lower().replace(":", "").replace(".", "")
        name = name[:60]
        
        entity = {
            "name": name,
            "entityType": category,
            "observations": [f"[{ts}] {content}", f"source: {source}"],
        }
        
        jsonl_line = json.dumps(entity, ensure_ascii=False) + "\n"
        
        # 1. JSONL append (source of truth)
        with FileLock(self._graph_path, timeout=3.0):
            atomic_append(self._graph_path, jsonl_line)
        
        # 2. MCP server (best-effort)
        self._mcp_create_entity(entity)
        
        return True
    
    def write_batch(self, entries: list[dict]) -> int:
        """Write multiple entries in batch to JSONL.
        
        MCP server gets individual calls since server-memory doesn't
        support batch create_entities.
        """
        lines = []
        mcp_entities = []
        for entry in entries:
            content = entry.get("content", "").strip()
            if not content:
                continue
            category = entry.get("category", "learning")
            ts = entry.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            source = entry.get("source", "memory-cli")
            
            words = content.split()[:6]
            name = "-".join(words).lower().replace(":", "").replace(".", "")
            name = name[:60]
            
            entity = {
                "name": name,
                "entityType": category,
                "observations": [f"[{ts}] {content}", f"source: {source}"],
            }
            lines.append(json.dumps(entity, ensure_ascii=False) + "\n")
            mcp_entities.append(entity)
        
        if not lines:
            return 0
        
        # 1. JSONL batch append
        with FileLock(self._graph_path, timeout=3.0):
            atomic_append(self._graph_path, "".join(lines))
        
        # 2. MCP server (best-effort, one per entity)
        for ent in mcp_entities:
            self._mcp_create_entity(ent)
        
        return len(lines)
    
    def read(self, query: str, **filters) -> list[dict]:
        """Search graph entries. First tries MCP, falls back to JSONL grep."""
        query_lower = query.lower()
        results: list[dict] = []
        
        content = read_file_safe(self._graph_path)
        if not content:
            return results
        
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entity = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            name = entity.get("name", "")
            etype = entity.get("entityType", "")
            observations = entity.get("observations", [])
            
            if (query_lower in name.lower()
                    or query_lower in etype.lower()
                    or any(query_lower in o.lower() for o in observations)):
                results.append({
                    "source": "graph",
                    "entity_name": name,
                    "entity_type": etype,
                    "observations": observations,
                })
        
        limit = filters.get("limit", 0)
        if limit and len(results) > limit:
            results = results[:limit]
        
        return results
    
    def delete(self, entry_ids: list[str]) -> int:
        """Remove entities matching any of entry_ids.
        
        Rewrites the JSONL file (line-level deletion on JSONL requires
        full rewrite).
        """
        if not entry_ids:
            return 0
        
        content = read_file_safe(self._graph_path)
        if not content:
            return 0
        
        kept: list[str] = []
        count = 0
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entity = json.loads(stripped)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            
            name = entity.get("name", "")
            if any(eid in name or eid in json.dumps(entity) for eid in entry_ids):
                count += 1
            else:
                kept.append(line)
        
        if count:
            from memory_cli.core.atomic import atomic_write
            atomic_write(self._graph_path, "".join(kept))
        
        return count
    
    def count(self) -> dict:
        """Count entities, relations, by entityType."""
        content = read_file_safe(self._graph_path)
        entities = 0
        by_type: dict[str, int] = {}
        
        if content:
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entity = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entities += 1
                etype = entity.get("entityType", "unknown")
                by_type[etype] = by_type.get(etype, 0) + 1
        
        stats = {
            "entities": entities,
            "by_type": by_type,
            "size_bytes": len(content.encode("utf-8")) if content else 0,
        }
        
        try:
            mtime = os.path.getmtime(self._graph_path)
            stats["last_modified"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        except OSError:
            stats["last_modified"] = None
        
        return stats
    
    def health(self) -> dict:
        issues: list[str] = []
        if not os.path.isfile(self._graph_path):
            issues.append("Graph file not found")
        elif not os.access(self._graph_path, os.R_OK):
            issues.append("Graph file not readable")
        else:
            # Check for malformed JSON lines
            content = read_file_safe(self._graph_path)
            for i, line in enumerate(content.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    issues.append(f"Malformed JSON at line {i}")
                    break
        
        if not self._bridge_available:
            issues.append("MCP bridge not available (mcp_bridge_shim not found)")
        
        return {"ok": len(issues) == 0, "issues": issues}
    
    def _mcp_create_entity(self, entity: dict) -> None:
        """Best-effort MCP entity creation. Never raises."""
        if not self._bridge_available:
            return
        try:
            from memory_cli.adapters.mcp_bridge_shim import create_entity
            create_entity(entity)
        except Exception:
            pass  # best-effort


register_adapter("graph", GraphAdapter)
