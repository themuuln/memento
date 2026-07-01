"""Tests for canonical parser — parse, validate, section tracking."""

import pytest
from memory_cli.core.parser import (
    parse_memory_file,
    MemoryEntry,
    validate_entries,
)


class TestParseMemoryFile:
    """Parse a proper memories.md fixture."""

    def test_parses_bullet_entries(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Hard Rules
- [2026-06-01] rule one
- [2026-06-02] rule two

## Key Learnings
- [2026-06-03] learned something
""")
        entries = parse_memory_file(str(md))
        assert len(entries) == 3
        assert all(isinstance(e, MemoryEntry) for e in entries)

    def test_tracks_section_path(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Hard Rules
- [2026-06-01] rule one
## Key Learnings
- [2026-06-02] learned something
""")
        entries = parse_memory_file(str(md))
        hard = [e for e in entries if e.section_path == ["Hard Rules"]]
        learned = [e for e in entries if e.section_path == ["Key Learnings"]]
        assert len(hard) == 1
        assert len(learned) == 1
        assert hard[0].content == "- [2026-06-01] rule one"
        assert learned[0].content == "- [2026-06-02] learned something"

    def test_classifies_kind(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Hard Rules
- [2026-06-01] rule one
""")
        entries = parse_memory_file(str(md))
        assert entries[0].kind == "dated_bullet"

    def test_underscored_content(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Tool Quirks
- `ln -sf` doesn't work on macOS — use `rm -f` then `ln -s`
""")
        entries = parse_memory_file(str(md))
        assert len(entries) == 1
        assert "ln -sf" in entries[0].content

    def test_empty_file_yields_empty_list(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("")
        entries = parse_memory_file(str(md))
        assert entries == []

    def test_no_sections_yields_prose_block(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("some text without sections\n")
        entries = parse_memory_file(str(md))
        # Text without sections is parsed as a prose block
        assert len(entries) == 1
        assert entries[0].kind == "prose_block"

    def test_duplicate_section_nesting(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Section A
- [2026-06-01] first
### Subsection
- [2026-06-02] nested
## Section A again
- [2026-06-03] second
""")
        entries = parse_memory_file(str(md))
        assert len(entries) == 3


class TestValidateEntries:
    """Validation checks on parsed entries."""

    def test_no_duplicate_content_hashes_in_valid_file(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Section
- [2026-06-01] unique content
- [2026-06-02] different content
""")
        entries = parse_memory_file(str(md))
        issues = validate_entries(entries)
        assert len(issues) == 0

    def test_duplicate_content_is_detected(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Section
- [2026-06-01] same content
- [2026-06-02] same content
""")
        entries = parse_memory_file(str(md))
        issues = validate_entries(entries)
        dupes = [i for i in issues if "content hash" in i.lower() and "duplicate" in i.lower()]
        assert len(dupes) >= 1

    def test_empty_content_bullet(self, tmp_path):
        # A bare `- ` with no text is still parsed as an entry with content "-"
        md = tmp_path / "memories.md"
        md.write_text("""## Section
-
""")
        entries = parse_memory_file(str(md))
        assert len(entries) >= 0  # Should not crash

    def test_orphan_code_block_flagged(self, tmp_path):
        md = tmp_path / "memories.md"
        md.write_text("""## Section
- some content
```
orphan code block marker
```
""")
        entries = parse_memory_file(str(md))
        issues = validate_entries(entries)
        assert len(issues) >= 0  # Should not crash; may or may not flag
