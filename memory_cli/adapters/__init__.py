from __future__ import annotations
"""Adapter registry — import adapters to trigger registration."""

# Import adapters to trigger register_adapter() calls
from memory_cli.adapters import base, file as _file, graph as _graph, search as _search

# Re-export
from memory_cli.adapters.base import AbstractMemoryAdapter, resolve_adapters, register_adapter

__all__ = [
    "AbstractMemoryAdapter",
    "resolve_adapters",
    "register_adapter",
]
