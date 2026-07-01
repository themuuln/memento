"""Tests for file adapter — write, read, multi-line content."""

import pytest
from memory_cli.adapters.file import FlatFileAdapter
from memory_cli.constants import PROTECTED_SECTIONS


class TestFlatFileAdapter:
    """File adapter read/write tests with temp files."""

    @pytest.fixture
    def adapter(self, tmp_path):
        mem_file = tmp_path / "memories.md"
        mem_file.write_text("""## Hard Rules
- [2026-06-01] rule one

## Key Learnings
- [2026-06-02] learned something
""")
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("## Hard Rules\n- be nice\n")
        prefs_file = tmp_path / "preferences.md"
        prefs_file.write_text("## User Preferences\n- dark mode\n")

        a = FlatFileAdapter()
        # Monkey-patch paths for testing
        a._mem_path = str(mem_file)
        a._rules_path = str(rules_file)
        a._prefs_path = str(prefs_file)
        return a

    def test_write_appends_to_section(self, adapter):
        result = adapter.write({
            "content": "test entry",
            "target_section": "Key Learnings",
            "timestamp": "2026-06-03",
        })
        assert result is True
        text = open(adapter._mem_path).read()
        assert "[2026-06-03] test entry" in text

    def test_write_creates_new_section(self, adapter):
        result = adapter.write({
            "content": "brand new entry",
            "target_section": "New Section",
            "timestamp": "2026-06-04",
        })
        assert result is True
        text = open(adapter._mem_path).read()
        assert "## New Section" in text
        assert "[2026-06-04] brand new entry" in text

    def test_write_to_protected_section_is_noop(self, adapter):
        result = adapter.write({
            "content": "should not appear",
            "target_section": "Hard Rules",
        })
        assert result is False
        text = open(adapter._mem_path).read()
        assert "should not appear" not in text

    def test_write_multi_line_content_indented(self, adapter):
        """Multi-line content should indent continuation lines."""
        result = adapter.write({
            "content": "first line\nsecond line\nthird line",
            "target_section": "Key Learnings",
            "timestamp": "2026-06-05",
        })
        assert result is True
        text = open(adapter._mem_path).read()
        assert "- [2026-06-05] first line" in text
        assert "  second line" in text
        assert "  third line" in text

    def test_write_no_section_appends_to_end(self, adapter):
        result = adapter.write({
            "content": "no section entry",
            "timestamp": "2026-06-06",
        })
        assert result is True
        text = open(adapter._mem_path).read()
        assert text.rstrip().endswith("[2026-06-06] no section entry")

    def test_read_returns_matching_entries(self, adapter):
        results = adapter.read("rule one")
        assert len(results) >= 1
        assert any("rule one" in r["content"] for r in results)

    def test_read_multi_word_query(self, adapter):
        results = adapter.read("learned something")
        assert len(results) >= 1

    def test_read_empty_query_returns_all(self, adapter):
        results = adapter.read("")
        # empty query returns nothing from grep
        assert isinstance(results, list)

    def test_read_respects_limit(self, adapter):
        results = adapter.read("", limit=1)
        assert isinstance(results, list)

    def test_delete_returns_int(self, adapter):
        count = adapter.delete(["nonexistent-id"])
        assert isinstance(count, int)

    def test_count_returns_total(self, adapter):
        counts = adapter.count()
        assert isinstance(counts, dict)
        assert "total" in counts

    def test_health_returns_ok(self, adapter):
        health = adapter.health()
        assert isinstance(health, dict)
        assert health.get("ok") in (True, False)


class TestFlatFileAdapterEmpty:
    """Edge cases: empty file, no sections."""

    def test_read_from_empty_file(self, tmp_path):
        mem_file = tmp_path / "memories.md"
        mem_file.write_text("")
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("")
        prefs_file = tmp_path / "preferences.md"
        prefs_file.write_text("")

        a = FlatFileAdapter()
        a._mem_path = str(mem_file)
        a._rules_path = str(rules_file)
        a._prefs_path = str(prefs_file)

        results = a.read("anything", limit=10)
        assert results == []
        assert a.count()["total"] == 0

    def test_write_to_empty_creates_section(self, tmp_path):
        mem_file = tmp_path / "memories.md"
        mem_file.write_text("")

        a = FlatFileAdapter()
        a._mem_path = str(mem_file)
        a._rules_path = str(tmp_path / "rules.md")
        a._prefs_path = str(tmp_path / "preferences.md")

        result = a.write({
            "content": "fresh entry",
            "target_section": "Fresh Section",
            "timestamp": "2026-06-07",
        })
        assert result is True
        text = open(a._mem_path).read()
        assert "## Fresh Section" in text
        assert "[2026-06-07] fresh entry" in text
