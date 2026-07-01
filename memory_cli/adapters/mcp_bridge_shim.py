from __future__ import annotations
"""Thin wrapper around the existing ~/.factory/hooks/mcp_bridge.py.
    
Maintains backward compatibility — any external code calling
mcp_bridge.py directly still works unchanged.
"""

import sys
import os

# Add ~/.factory/hooks to sys.path so we can import mcp_bridge
_FACTORY_HOOKS = os.path.expanduser("~/.factory/hooks")
if _FACTORY_HOOKS not in sys.path:
    sys.path.insert(0, _FACTORY_HOOKS)

# Re-export all public symbols
# Import inside function to avoid import-order issues
_bridge = None

def _get_bridge():
    global _bridge
    if _bridge is None:
        import importlib
        _bridge = importlib.import_module("mcp_bridge")
    return _bridge

def create_entity(entity: dict) -> bool:
    """Create a single entity."""
    return _get_bridge().create_memory_entities([entity])

def create_entities(entities: list[dict]) -> bool:
    return _get_bridge().create_memory_entities(entities)

def create_relations(relations: list[dict]) -> bool:
    return _get_bridge().create_memory_relations(relations)

def delete_entities(entity_names: list[str]) -> bool:
    return _get_bridge().delete_memory_entities(entity_names)

def search_nodes(query: str) -> list[dict] | None:
    return _get_bridge().search_memory_nodes(query)

def create_entities_and_relations(entities: list[dict], relations: list[dict]) -> bool:
    return _get_bridge().create_memory_entities_and_relations(entities, relations)
