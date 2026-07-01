"""Canonical markdown parser for memories.md.

Produces typed MemoryEntry objects with stable content-hash IDs,
heading hierarchy tracking, and block-level chunking.

Usage:
    from memory_cli.core.parser import parse_memory_file, MemoryEntry

    entries = parse_memory_file("~/.agent-memory/global/memories.md")
    for e in entries:
        print(e.id, e.kind, e.content[:50])
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    """A single searchable memory derived from canonical markdown.

    Fields:
        id: Stable content-hash ID (does not depend on line number).
        kind: Type of memory entry.
        section_path: Heading hierarchy, e.g. ["Project Conventions", "tolom"].
        timestamp: ISO date string like "2026-07-01" or None.
        content: Clean text content for display.
        search_text: Content enriched with section context for FTS indexing.
        source_path: Relative path of source file.
        line_start: Line number in source file (metadata only).
        line_end: Line number (inclusive).
        content_hash: SHA-256 of normalized content for dedup.
        raw: Raw source text of the entry.
    """

    id: str
    kind: str
    section_path: list[str]
    timestamp: str | None
    content: str
    search_text: str
    source_path: str
    line_start: int
    line_end: int
    content_hash: str
    raw: str


# ── Heading hierarchy tracking ────────────────────────────────────


def _build_section_path(
    heading_stack: list[tuple[int, str]],
    heading_level: int,
    heading_text: str,
) -> list[str]:
    """Build the current section path from heading hierarchy."""
    # Pop headings at same or deeper level
    while heading_stack and heading_stack[-1][0] >= heading_level:
        heading_stack.pop()
    heading_stack.append((heading_level, heading_text))
    return [h[1] for h in heading_stack]


# ── Content hash ──────────────────────────────────────────────────


def _content_hash(content: str) -> str:
    """SHA-256 of normalized content (stripping timestamps before hashing)."""
    # Strip bullet prefix and timestamp for semantic dedup
    clean = re.sub(r"^-\s*\[?\d{4}-\d{2}-\d{2}\]?\s*", "", content.strip().lower())
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def _entry_id(content: str, section_path: list[str], line_start: int = 0) -> str:
    """Generate stable ID from section path + content hash + line number.
    
    Includes line_start to disambiguate identical content on different lines
    (e.g., multi-line entries where the first line is the same).
    """
    path_part = "-".join(section_path[-2:]) if section_path else "root"
    path_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", path_part).lower()[:32]
    h = _content_hash(content)
    return f"mem_md_{path_slug}_{h}" + (f"_ln{line_start}" if line_start else "")


# ── Ignored line patterns ────────────────────────────────────────


def _is_ignored(line: str) -> bool:
    """Check if a line should be skipped."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("<!--") and stripped.endswith("-->"):
        return True
    if stripped.startswith("> "):
        return False  # blockquotes are meaningful
    if stripped in ("---",):
        return True
    # Header-level description lines like "*47 entries*"
    if re.match(r"^\*[\d, ]+ entries\*$", stripped):
        return True
    return False


# ── Kind classification ─────────────────────────────────────────


def _classify_kind(
    text: str,
    section_path: list[str],
    section_heading: str,
    is_dated: bool,
) -> str:
    """Classify the kind of memory entry."""
    if section_heading == "Project Conventions" and len(section_path) >= 2:
        return "project_profile"
    if is_dated:
        return "dated_bullet"
    if text.startswith("|") and text.endswith("|"):
        return "table"
    if text.startswith("```"):
        return "code_note"
    return "bullet"


# ── ISO date extraction ──────────────────────────────────────────


_DATE_PATTERN = re.compile(r"\[(\d{4}-\d{2}-\d{2})\]")

_HARD_SECTION_NAMES = {
    "hard rules", "user preferences", "project conventions",
    "tool quirks", "validated approaches", "key learnings",
    "model configuration", "key decisions",
    "conventions", "gotchas & traps", "architecture decisions",
    "workflows",
}


# ── Main parser ──────────────────────────────────────────────────


def parse_memory_file(filepath: str, source_path: str | None = None) -> list[MemoryEntry]:
    """Parse a memories.md file into a list of MemoryEntry objects.

    Args:
        filepath: Path to the markdown file.
        source_path: Override the source path in entries (default: basename).

    Returns:
        List of MemoryEntry objects.
    """
    from memory_cli.core.atomic import read_file_safe

    content = read_file_safe(filepath)
    if not content:
        return []

    return parse_memory_content(content, source_path or filepath)


def parse_memory_content(content: str, source_path: str = "memories.md") -> list[MemoryEntry]:
    """Parse memories.md content string into MemoryEntry objects."""
    entries: list[MemoryEntry] = []
    lines = content.split("\n")

    heading_stack: list[tuple[int, str]] = []
    current_section_path: list[str] = []
    current_section: str = "root"

    # State for bullet accumulation
    in_bullet: bool = False
    bullet_lines: list[str] = []
    bullet_start: int = 0
    is_dated_bullet: bool = False
    bullet_timestamp: str | None = None
    bullet_indent: str = ""
    in_code_block: bool = False

    # State for code block accumulation
    code_block_lines: list[str] = []
    code_block_start: int = 0

    # State for table accumulation
    in_table: bool = False
    table_lines: list[str] = []
    table_start: int = 0

    def _flush_bullet() -> None:
        nonlocal in_bullet, bullet_lines, bullet_start, is_dated_bullet, bullet_timestamp, bullet_indent
        if not bullet_lines:
            return

        # Skip single-line code fences inside bullets
        clean_lines = [l for l in bullet_lines if not l.strip().startswith("```")]
        raw = "\n".join(bullet_lines).strip()
        content_text = "\n".join(clean_lines).strip()

        if not content_text:
            in_bullet = False
            bullet_lines = []
            bullet_start = 0
            return

        kind = _classify_kind(content_text, current_section_path, current_section, is_dated_bullet)
        mem = MemoryEntry(
            id=_entry_id(content_text, current_section_path, bullet_start),
            kind=kind,
            section_path=list(current_section_path),
            timestamp=bullet_timestamp,
            content=content_text,
            search_text=_build_search_text(content_text, current_section_path, bullet_timestamp),
            source_path=source_path,
            line_start=bullet_start,
            line_end=bullet_start + len(bullet_lines) - 1,
            content_hash=_content_hash(content_text),
            raw=raw,
        )
        entries.append(mem)
        in_bullet = False
        bullet_lines = []
        bullet_start = 0
        is_dated_bullet = False
        bullet_timestamp = None
        bullet_indent = ""

    def _flush_table() -> None:
        nonlocal in_table, table_lines, table_start
        if not table_lines:
            return
        raw = "\n".join(table_lines).strip()
        if raw:
            content_text = raw
            mem = MemoryEntry(
                id=_entry_id(content_text, current_section_path, table_start),
                kind="table",
                section_path=list(current_section_path),
                timestamp=None,
                content=content_text,
                search_text=_build_search_text(content_text, current_section_path, None),
                source_path=source_path,
                line_start=table_start,
                line_end=table_start + len(table_lines) - 1,
                content_hash=_content_hash(content_text),
                raw=raw,
            )
            entries.append(mem)
        in_table = False
        table_lines = []
        table_start = 0

    def _flush_code_block() -> None:
        nonlocal in_code_block, code_block_lines, code_block_start
        if not code_block_lines:
            in_code_block = False
            code_block_lines = []
            code_block_start = 0
            return
        
        raw = "\n".join(code_block_lines) + "\n"
        content_text = raw.strip()
        if content_text:
            mem = MemoryEntry(
                id=_entry_id(content_text, current_section_path, code_block_start),
                kind="code_note",
                section_path=list(current_section_path),
                timestamp=None,
                content=content_text,
                search_text=_build_search_text(content_text, current_section_path, None),
                source_path=source_path,
                line_start=code_block_start,
                line_end=code_block_start + len(code_block_lines) - 1,
                content_hash=_content_hash(content_text),
                raw=raw,
            )
            entries.append(mem)
        in_code_block = False
        code_block_lines = []
        code_block_start = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # ── Code block toggle ──────────────────────────────────
        if stripped.startswith("```"):
            if in_code_block:
                # Exiting code block — flush it
                _flush_code_block()
            else:
                # Entering code block — flush prior state, start tracking
                _flush_bullet()
                _flush_table()
                in_code_block = True
                code_block_lines = []
                code_block_start = i
            continue

        # If we're inside a code block, collect the line
        if in_code_block:
            code_block_lines.append(stripped)
            continue

        # ── Headings ───────────────────────────────────────────
        heading_m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_m:
            _flush_bullet()
            _flush_table()
            level = len(heading_m.group(1))
            text = heading_m.group(2).strip()
            current_section_path = _build_section_path(heading_stack, level, text)
            current_section = text
            continue

        # ── Horizontal rules, comments, boilerplate ───────────
        if _is_ignored(line):
            _flush_bullet()
            _flush_table()
            continue

        # ── Tables ─────────────────────────────────────────────
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                _flush_bullet()
                _flush_table()
                in_table = True
                table_start = i
                table_lines = [stripped]
            else:
                table_lines.append(stripped)
            continue
        else:
            if in_table:
                # End of table
                _flush_table()

        # ── Bullets ────────────────────────────────────────────
        if stripped.startswith("- ") or stripped.startswith("  - "):
            _flush_table()
            
            # Extract indent and content
            bullet_m = re.match(r"^(\s*-\s+)(.*)", stripped)
            if not bullet_m:
                continue
            indent = bullet_m.group(1)
            text_after_bullet = bullet_m.group(2)

            # Check for timestamp
            date_m = _DATE_PATTERN.match(text_after_bullet)
            ts = date_m.group(1) if date_m else None
            content_only = text_after_bullet[date_m.end():].strip() if date_m else text_after_bullet

            if not content_only:
                continue

            # Start a new bullet (flush previous)
            _flush_bullet()
            in_bullet = True
            bullet_start = i
            bullet_lines = [stripped]
            is_dated_bullet = ts is not None
            bullet_timestamp = ts
            bullet_indent = indent
            continue

        # ── Continuation lines (indented, attached to current bullet) ──
        if in_bullet and stripped and (line[0] == " " or line[0] == "\t" or not line[0].strip()):
            bullet_lines.append(stripped)
            continue

        # ── Non-bullet prose (standalone block) ────────────────
        if in_bullet and not stripped.startswith("- ") and not stripped.startswith("  - "):
            _flush_bullet()
        
        # Empty lines between bullets — continue tracking current state
        if not stripped:
            continue

        # ── Standalone prose (not a bullet, not a heading, not a table) ──
        _flush_bullet()
        _flush_table()
        
        if stripped and not _is_ignored(line):
            mem = MemoryEntry(
                id=_entry_id(stripped, current_section_path, i),
                kind="prose_block",
                section_path=list(current_section_path),
                timestamp=None,
                content=stripped,
                search_text=_build_search_text(stripped, current_section_path, None),
                source_path=source_path,
                line_start=i,
                line_end=i,
                content_hash=_content_hash(stripped),
                raw=stripped,
            )
            entries.append(mem)

    # Flush final state
    _flush_bullet()
    _flush_table()
    _flush_code_block()

    return entries


def _build_search_text(content: str, section_path: list[str], timestamp: str | None) -> str:
    """Build search text with section hierarchy prefix."""
    path = " > ".join(section_path) if section_path else ""
    parts = [path, content] if path else [content]
    if timestamp:
        parts.insert(1, f"[{timestamp}]")
    return "\n".join(parts)


# ── Validation ────────────────────────────────────────────────────


def validate_entries(entries: list[MemoryEntry]) -> list[str]:
    """Validate a list of entries, returning warnings."""
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()

    for entry in entries:
        if entry.id in seen_ids:
            warnings.append(f"Duplicate ID: {entry.id} at line {entry.line_start}")
        seen_ids.add(entry.id)

        if entry.content_hash in seen_hashes:
            warnings.append(f"Duplicate content hash: {entry.content_hash} at line {entry.line_start}")
        seen_hashes.add(entry.content_hash)

        if not entry.content.strip():
            warnings.append(f"Empty content at line {entry.line_start}")
        
        if entry.timestamp and not _DATE_PATTERN.match(f"[{entry.timestamp}]"):
            warnings.append(f"Invalid timestamp at line {entry.line_start}: {entry.timestamp}")

    return warnings


def count_by_kind(entries: list[MemoryEntry]) -> dict[str, int]:
    """Count entries grouped by kind."""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    return counts
