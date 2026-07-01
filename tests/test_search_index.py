"""Tests for FTS5 search index — index, query, sanitize."""

import pytest
from memory_cli.core.search_index import SearchIndex, sanitize_fts_query


class TestSanitizeFtsQuery:
    def test_basic_query_passes_through(self):
        result = sanitize_fts_query("hello world")
        assert isinstance(result, str) and len(result) > 0

    def test_handles_special_chars(self):
        result = sanitize_fts_query("ln -sf")
        assert result is not None and len(result) > 0

    def test_handles_code_syntax(self):
        result = sanitize_fts_query("Next.js sqlite")
        assert result is not None

    def test_handles_path_chars(self):
        result = sanitize_fts_query("~/.agent-memory/test")
        assert result is not None

    def test_empty_input_returns_empty(self):
        assert sanitize_fts_query("") == ""

    def test_punctuation_expansion(self):
        """Next.js should expand for FTS5 tokenizer."""
        result = sanitize_fts_query("Next.js")
        assert result is not None and len(result) > 0

    def test_wraps_leading_dash_terms(self):
        """Terms starting with - need to be wrapped in quotes for FTS5."""
        result = sanitize_fts_query("-force-with-lease")
        assert result is not None and len(result) > 0


class TestSearchIndex:
    """Full round-trip tests with temp database."""

    @pytest.fixture
    def index(self, tmp_path):
        idx = SearchIndex(db_path=str(tmp_path / "test_memory.db"))
        idx.open()
        yield idx
        idx.close()

    def test_rebuild_and_count(self, index):
        entries = [
            {"id": "test_001", "content": "- [2026-06-01] we decided to use sqlite",
             "search_text": "decisions we decided to use sqlite",
             "section_path": ["Decisions"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 1},
            {"id": "test_002", "content": "- [2026-06-02] postgres needs connection pooling",
             "search_text": "learnings postgres needs connection pooling",
             "section_path": ["Learnings"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 2},
        ]
        result = index.rebuild(entries)
        assert result["entries_count"] == 2
        stats = index.count()
        assert stats["total"] == 2

    def test_search_basic(self, index):
        entries = [
            {"id": "test_003", "content": "- [2026-06-01] sqlite local caching",
             "search_text": "sqlite local caching decisions",
             "section_path": ["Decisions"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 1},
        ]
        index.rebuild(entries)
        results = index.search("sqlite", limit=10)
        assert len(results) >= 1

    def test_search_no_match(self, index):
        entries = [
            {"id": "test_004", "content": "- [2026-06-01] postgres connection pooling",
             "search_text": "postgres connection pooling",
             "section_path": ["Learnings"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 1},
        ]
        index.rebuild(entries)
        results = index.search("notpresent", limit=10)
        assert len(results) == 0

    def test_rebuild_empty_list(self, index):
        result = index.rebuild([])
        assert isinstance(result, dict)
        assert "entries_count" in result

    def test_health_returns_dict(self, index):
        health = index.health()
        assert isinstance(health, dict)
        assert "total" in health

    def test_multiple_queries_preserve_index(self, index):
        entries = []
        for i in range(5):
            entries.append({
                "id": f"test_multi_{i}",
                "content": f"- entry number {i}",
                "search_text": f"entry number {i} section",
                "section_path": ["Test"], "kind": "bullet",
                "source_path": "/tmp/test.md", "line_start": i,
            })
        index.rebuild(entries)
        r1 = index.search("entry", limit=10)
        assert len(r1) >= 5

    def test_initial_count_on_fresh_index(self, index):
        stats = index.count()
        assert "total" in stats
