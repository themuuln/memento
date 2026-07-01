from __future__ import annotations
"""FlatFileAdapter — reads/writes memories.md as source of truth."""

import os
import re
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters.base import AbstractMemoryAdapter, register_adapter
from memory_cli.constants import (
    GLOBAL_MEM_PATH,
    GLOBAL_RULES_PATH,
    GLOBAL_PREFERENCES_PATH,
    HOT_DIR,
    WARM_DIR,
    COLD_DIR,
    PROTECTED_SECTIONS,
    PREFIX_MAP,
)
from memory_cli.core.atomic import atomic_write, atomic_append, read_file_safe
from memory_cli.core.locking import FileLock
from memory_cli.core.dedup import is_duplicate


class FlatFileAdapter(AbstractMemoryAdapter):
    """Read/write memories.md — the durable source of truth.
    
    Format:
      ## Section Name
      - [2026-06-30] Content here
      - [2026-06-29] More content
    
    Protected sections (e.g. "Hard Rules") are never auto-edited.
    """
    
    name = "file"
    capabilities = {"read", "write"}
    
    def __init__(self):
        self._root: str = ""
        self._mem_path: str = ""
        self._rules_path: str = ""
        self._prefs_path: str = ""
    
    def initialize(self, config: dict) -> None:
        storage = config.get("storage", {})
        self._root = storage.get("root", os.path.expanduser("~/.agent-memory"))
        self._mem_path = storage.get("global_memory", GLOBAL_MEM_PATH)
        self._rules_path = os.path.join(self._root, "global", "rules.md")
        self._prefs_path = os.path.join(self._root, "global", "preferences.md")
    
    def write(self, entry: dict) -> bool:
        """Append a single entry to memories.md.
        
        If the entry has a target_section, ensures the section header
        exists before appending. Protected sections are skipped.
        """
        section = entry.get("target_section", "")
        content = entry.get("content", "").strip()
        if not content:
            return False
        if section in PROTECTED_SECTIONS:
            return False
        
        ts = entry.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        # Handle multi-line content: first line has the bullet, continuation lines get 2-space indent
        content_lines = content.split("\n")
        bullet = f"- [{ts}] {content_lines[0]}\n"
        continuation = "\n".join(f"  {l}" for l in content_lines[1:] if l.strip())
        line = bullet + (continuation + "\n" if continuation else "")
        
        with FileLock(self._mem_path):
            current = read_file_safe(self._mem_path)
            
            if section:
                section_header = f"## {section}"
                if section_header not in current:
                    # Append section + entry at end
                    text = f"\n{section_header}\n{line}"
                    atomic_append(self._mem_path, text)
                else:
                    # Insert after section header
                    lines = current.splitlines(keepends=True)
                    new_lines = []
                    inserted = False
                    for i, ln in enumerate(lines):
                        new_lines.append(ln)
                        if ln.strip() == section_header and not inserted:
                            # Find where the section content starts
                            j = i + 1
                            while j < len(lines) and (
                                lines[j].strip().startswith("- ")
                                or not lines[j].strip()
                            ):
                                j += 1
                            # Insert before next section or end
                            has_content_after = i + 1 < len(lines)
                            indent = "  " if (has_content_after and lines[i + 1] and lines[i + 1][0].isspace()) else ""
                            new_lines.insert(j, f"{indent}{line}")
                            inserted = True
                    if inserted:
                        atomic_write(self._mem_path, "".join(new_lines))
            else:
                atomic_append(self._mem_path, line)
        
        return True
    
    def read(self, query: str, **filters) -> list[dict]:
        """Grep-based search through memories.md, rules.md, preferences.md."""
        results: list[dict] = []
        query_lower = query.lower()
        
        for filepath, label in [
            (self._mem_path, "global/memories.md"),
            (self._rules_path, "global/rules.md"),
            (self._prefs_path, "global/preferences.md"),
        ]:
            content = read_file_safe(filepath)
            if not content:
                continue
            
            lines = content.splitlines()
            current_section = ""
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("## "):
                    current_section = stripped[3:]
                if query_lower in stripped.lower():
                    result = {
                        "source": "file",
                        "file": label,
                        "line": i + 1,
                        "section": current_section,
                        "content": stripped,
                    }
                    # Add context lines
                    context_start = max(0, i - filters.get("context_lines", 0))
                    context_end = min(len(lines), i + filters.get("context_lines", 0) + 1)
                    result["context"] = lines[context_start:context_end]
                    results.append(result)
        
        limit = filters.get("limit", 0)
        if limit and len(results) > limit:
            results = results[:limit]
        
        return results
    
    def delete(self, entry_ids: list[str]) -> int:
        """Delete lines by content match. entry_ids are substrings to match."""
        if not entry_ids:
            return 0
        
        count = 0
        with FileLock(self._mem_path):
            content = read_file_safe(self._mem_path)
            if not content:
                return 0
            lines = content.splitlines(keepends=True)
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if any(eid in stripped for eid in entry_ids):
                    count += 1
                else:
                    new_lines.append(line)
            if count:
                # Collapse multiple blank lines
                result = re.sub(r"\n{3,}", "\n\n", "".join(new_lines))
                atomic_write(self._mem_path, result)
        return count
    
    def count(self) -> dict:
        """Count entries by section, total lines, file sizes."""
        content = read_file_safe(self._mem_path)
        if not content:
            return {"total": 0, "by_section": {}, "size_bytes": 0, "last_modified": None}
        
        stats: dict[str, Any] = {"by_section": {}}
        current_section = "Uncategorized"
        entries = 0
        
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("### "):
                current_section = stripped[3:]
            elif stripped.startswith("- ") and len(stripped) > 3:
                # Count top-level bullets only — exclude sub-bullets (4+ leading spaces)
                # Top-level entries have 0 or 2 spaces of indent (the latter from
                # FlatFileAdapter.write() inserting under an existing section).
                leading_spaces = len(line) - len(line.lstrip())
                if leading_spaces <= 2:
                    entries += 1
                    stats["by_section"][current_section] = \
                        stats["by_section"].get(current_section, 0) + 1
        
        try:
            mtime = os.path.getmtime(self._mem_path)
            stats["last_modified"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        except OSError:
            stats["last_modified"] = None
        
        stats["total"] = entries
        stats["size_bytes"] = len(content.encode("utf-8"))
        return stats
    
    def health(self) -> dict:
        issues: list[str] = []
        for path, label in [
            (self._mem_path, "memories.md"),
        ]:
            if not os.path.isfile(path):
                issues.append(f"{label} not found")
            elif not os.access(path, os.R_OK):
                issues.append(f"{label} not readable")
            elif not os.access(os.path.dirname(path), os.W_OK):
                issues.append(f"{label} directory not writable")
        
        if self.count().get("by_section", {}).get("Hard Rules", 0) < 1:
            issues.append("Hard Rules section is empty")
        
        return {"ok": len(issues) == 0, "issues": issues}


register_adapter("file", FlatFileAdapter)
