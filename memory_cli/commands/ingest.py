from __future__ import annotations
"""memory ingest — capture memory from user input.

Merges patterns from memory-capture.py:
  - Explicit triggers: "remember this:", "note:", "decision:", etc.
  - Prefix routing: "# text" → project, "## text" → global
  - Natural language patterns: "we decided X", "i learned Y"
  - Classification + dedup before write
"""

import re
import sys
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.core.dedup import is_duplicate
from memory_cli.core.config import load_config
from memory_cli.constants import CAPTURE_TRIGGERS, NATURAL_LANGUAGE_PATTERNS


def run(
    config: dict,
    adapters: list[str],
    text: list[str] | None = None,
    stdin: bool = False,
    file: str | None = None,
    target: str | None = None,
    dry_run: bool = False,
    no_dedup: bool = False,
    direct: bool = False,
    no_index: bool = False,
    section: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Capture memory entries from input."""
    result: dict[str, Any] = {
        "command": "ingest",
        "status": "ok",
        "captured": [],
        "skipped": {"duplicates": 0, "nothing": 0},
    }
    
    # Read input
    raw_messages = _read_input(text, stdin, file)
    if not raw_messages:
        result["status"] = "no_input"
        return result
    
    # Extract entries from messages
    entries = _extract_entries(raw_messages, target, config, direct=direct, section=section)
    
    if not entries:
        result["status"] = "no_match"
        return result
    
    # Dedup
    adapter_instances = resolve_adapters(adapters, config, capability="write")
    file_adapter = next((a for a in adapter_instances if a.name == "file"), None)
    
    if not no_dedup and file_adapter:
        existing = [
            e["content"] for e in
            (file_adapter.read("", limit=5000) if hasattr(file_adapter, "read") else [])
        ]
        deduped = []
        for entry in entries:
            if is_duplicate(entry["content"], existing, threshold=0.55):
                result["skipped"]["duplicates"] += 1
            else:
                deduped.append(entry)
        entries = deduped
    
    # Write
    if not dry_run:
        for entry in entries:
            for a in adapter_instances:
                a.write(entry)
        
        # Auto-rebuild FTS5 search index after write (unless --no-index)
        if not no_index:
            try:
                from memory_cli.core.search_index import SearchIndex
                from memory_cli.core.parser import parse_memory_file
                from memory_cli.constants import GLOBAL_MEM_PATH
                
                idx = SearchIndex()
                idx.open()
                parsed = parse_memory_file(GLOBAL_MEM_PATH)
                entries_for_index = [
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
                    for e in parsed
                ]
                idx.rebuild(entries_for_index)
                idx.close()
            except Exception:
                pass  # Best-effort
    
    result["captured"] = entries
    
    if not result["captured"] and not result["skipped"]["duplicates"]:
        result["status"] = "no_match"
    
    return result


def _read_input(
    text: list[str] | None,
    stdin: bool,
    file: str | None,
) -> list[str]:
    """Read input from args, stdin, or file. Returns list of message strings."""
    messages: list[str] = []
    
    if text:
        messages.extend(text)
    
    if stdin:
        data = sys.stdin.read().strip()
        if data:
            # Try parsing as JSON (Pi session format)
            import json
            try:
                parsed = json.loads(data)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            msg = item.get("content", "") or item.get("message", "")
                            if msg:
                                messages.append(str(msg))
                elif isinstance(parsed, dict):
                    for role in ("user", "assistant", "system"):
                        if parsed.get(role):
                            messages.append(str(parsed[role]))
            except (json.JSONDecodeError, ValueError):
                messages.append(data)
    
    if file:
        try:
            with open(file) as f:
                messages.append(f.read())
        except OSError as e:
            pass  # will be caught by caller
    
    return messages


def _extract_entries(
    messages: list[str],
    target: str | None,
    config: dict,
    direct: bool = False,
    section: str | None = None,
) -> list[dict]:
    """Parse messages into structured memory entries.
    
    When direct=True, every message is treated as a direct learning entry
    without any trigger/pattern matching.
    """
    entries: list[dict] = []
    seen = set()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    triggers = config.get("capture", {}).get("triggers", CAPTURE_TRIGGERS)
    nl_patterns = config.get("capture", {}).get("natural_language", NATURAL_LANGUAGE_PATTERNS)

    def _normalize_key(content: str) -> str:
        """Normalize content for cross-path dedup: strip trigger prefixes."""
        c = content.strip().lower()
        for t in triggers:
            tl = t.lower()
            if c.startswith(tl):
                c = c[len(tl):].strip()
                break
        return c[:100]
    
    for msg in messages:
        if not msg or not isinstance(msg, str):
            continue
        msg = msg.strip()
        if not msg:
            continue
        
        # Skip very long messages (garbage) — generous for direct mode
        max_len = 5000 if direct else 2000
        if len(msg) > max_len:
            continue

        # Direct mode: write content as-is without pattern matching
        if direct:
            if msg not in seen:
                seen.add(msg[:100])
                # Use explicit --section if provided, else derive from --target
                section_name = (
                    _category_to_section(section)
                    if section
                    else _category_to_section(target or "learning")
                )
                entries.append({
                    "content": msg,
                    "category": section or "learning",
                    "target_section": section_name,
                    "timestamp": now,
                    "source": "ingest",
                })
            continue
        
        # Check triggers
        for trigger in triggers:
            if trigger.lower() in msg.lower():
                idx = msg.lower().index(trigger.lower())
                content = msg[idx + len(trigger):].strip()
                # Limit to first line only (avoid multi-line captures)
                newline_pos = content.find("\n")
                if newline_pos > 0:
                    content = content[:newline_pos].strip()
                if content:
                    entry = _classify(content, nl_patterns, target)
                    entry["timestamp"] = now
                    entry["source"] = "ingest"
                    dedup_key = _normalize_key(content)
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        entries.append(entry)
        
        # Check natural language patterns
        for category, patterns in nl_patterns.items():
            for pattern in patterns:
                if pattern.lower() in msg.lower():
                    idx = msg.lower().index(pattern.lower())
                    content = msg[idx:].strip()
                    # Take up to 200 chars, stop at newline
                    newline_pos = content.find("\n")
                    if newline_pos > 0:
                        content = content[:newline_pos].strip()
                    if len(content) > 200:
                        content = content[:200] + "..."
                    if content:
                        entry = {
                            "content": content,
                            "category": category,
                            "target_section": _category_to_section(category),
                            "timestamp": now,
                            "source": "ingest",
                        }
                        dedup_key = _normalize_key(content)
                        if dedup_key not in seen:
                            seen.add(dedup_key)
                            entries.append(entry)
        
        # Check #/## prefixes
        lines = msg.split("\n")
        for line in lines:
            stripped = line.strip()
            
            # ## text → global/personal memory
            if stripped.startswith("## ") and len(stripped) > 4:
                raw_content = stripped[3:].strip()
                if raw_content and raw_content.startswith("#"):
                    continue  # Skip sub-headings
                dedup_key = _normalize_key(raw_content)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    entry = {
                        "content": raw_content,
                        "category": "learning",
                        "target_section": "Key Learnings",
                        "timestamp": now,
                        "source": "ingest",
                    }
                    entries.append(entry)
            
            # # text → project memory
            elif stripped.startswith("# ") and len(stripped) > 2:
                raw_content = stripped[2:].strip()
                if raw_content:
                    dedup_key = _normalize_key(raw_content)
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        entry = {
                            "content": raw_content,
                            "category": "project-fact",
                            "target_section": "Project Conventions",
                            "timestamp": now,
                            "source": "ingest",
                        }
                        entries.append(entry)
    
    return entries


def _classify(content: str, nl_patterns: dict, target: str | None) -> dict:
    """Classify content into a category and determine target section."""
    content_lower = content.lower()
    
    for category, patterns in nl_patterns.items():
        for pattern in patterns:
            if pattern.lower() in content_lower:
                return {
                    "content": content,
                    "category": category,
                    "target_section": _category_to_section(category),
                }
    
    return {
        "content": content,
        "category": "learning",
        "target_section": _category_to_section("learning"),
    }


def _category_to_section(category: str) -> str:
    mapping = {
        "decision": "Validated Approaches",
        "preference": "User Preferences",
        "learning": "Key Learnings",
        "gotcha": "Gotchas & Traps",
        "rule": "Hard Rules",
        "convention": "Conventions",
        "architecture": "Architecture Decisions",
        "workflow": "Workflows",
        "project-fact": "Project Conventions",
    }
    return mapping.get(category, "Key Learnings")
