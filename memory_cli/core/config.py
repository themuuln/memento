from __future__ import annotations
"""Configuration loading and environment variable overlays."""

import json
import os
from typing import Any

from memory_cli.constants import (
    AGENT_MEMORY_DIR,
    CONFIG_PATH,
    TIER_DEFAULTS,
    DEFAULT_MODEL,
    DEFAULT_API_URL,
)


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load config.json, apply env var overlays, fill defaults.
    
    Priority (highest wins):
      1. Env vars (AGENT_MEMORY_DIR, OPENCODE_GO_API_KEY)
      2. config.json on disk
      3. Built-in defaults (constants.py)
    """
    config: dict[str, Any] = {
        "version": 1,
        "storage": {
            "root": AGENT_MEMORY_DIR,
            "global_memory": _resolve("global/memories.md"),
            "graph_file": _resolve("graph/memory-graph.jsonl"),
            "archive_dir": _resolve("archive/entries"),
        },
        "tiers": TIER_DEFAULTS,
        "capture": {
            "triggers": [
                "remember this:", "note:", "we decided:",
                "important:", "key insight:", "lesson learned:",
                "decision:", "learning:", "preference:",
            ],
            "patterns": {"personal": "## ", "project": "# "},
            "natural_language": {
                "decision": ["we decided", "we chose", "we switched to", "we migrated", "we adopted"],
                "learning": ["i learned", "i discovered", "i realized", "key takeaway"],
            },
        },
        "dedup": {"method": "jaccard", "threshold": 0.55},
        "mcp": {
            "server": "@modelcontextprotocol/server-memory",
            "graph_file": _resolve("graph/memory-graph.jsonl"),
        },
        "llm": {
            "model": DEFAULT_MODEL,
            "api_url": DEFAULT_API_URL,
            "api_key_env": "OPENCODE_GO_API_KEY",
        },
    }

    # Overlay from disk
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            disk_config = json.load(f)
        _deep_merge(config, disk_config)

    # Env var overlays
    if os.environ.get("AGENT_MEMORY_DIR"):
        config["storage"]["root"] = os.environ["AGENT_MEMORY_DIR"]
    if os.environ.get("OPENCODE_GO_API_KEY"):
        config["llm"]["api_key"] = os.environ["OPENCODE_GO_API_KEY"]

    return config


def get_api_key(config: dict) -> str:
    """Resolve the LLM API key from config, env, or secrets file."""
    # 1. Config overrides
    key = config.get("llm", {}).get("api_key")
    if key:
        return key

    # 2. Environment variable
    env_var = config.get("llm", {}).get("api_key_env", "OPENCODE_GO_API_KEY")
    env_key = os.environ.get(env_var)
    if env_key:
        return env_key

    # 3. Fallback: chezmoi-managed secrets file
    secrets_path = os.path.expanduser("~/.config/secrets/env.sh")
    if os.path.isfile(secrets_path):
        try:
            with open(secrets_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("export OPENCODE_GO_API_KEY="):
                        # Extract the value between quotes
                        val = line.split("=", 1)[1].strip().strip("'\"")
                        if val:
                            return val
        except OSError:
            pass

    return ""


def _resolve(rel_path: str) -> str:
    return os.path.join(AGENT_MEMORY_DIR, rel_path)


def _deep_merge(base: dict, overlay: dict) -> None:
    """Recursively merge overlay into base (mutates base)."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
