"""Tests for FTS5 alias expansion and OR fallback."""

import pytest
from memory_cli.core.search_index import expand_aliases, SearchIndex


class TestExpandAliases:
    def test_no_alias_passthrough(self):
        assert expand_aliases("hello world") == "hello world"

    def test_empty_input(self):
        assert expand_aliases("") == ""
        assert expand_aliases("   ") == "   "

    def test_nextjs_expands(self):
        result = expand_aliases("nextjs setup")
        assert "next.js" in result

    def test_postgres_expands(self):
        result = expand_aliases("postgres connection")
        assert "postgresql" in result

    def test_tailwind_expands(self):
        result = expand_aliases("tailwind classes")
        assert "tailwindcss" in result

    def test_vscode_expands(self):
        result = expand_aliases("vscode extensions")
        assert "vs code" in result or "visual studio code" in result

    def test_canonical_also_expands_to_aliases(self):
        result = expand_aliases("next.js routing")
        assert "nextjs" in result or "next-js" in result

    def test_typescript_expands(self):
        result = expand_aliases("ts compiler")
        assert "typescript" in result

    def test_react_expands(self):
        result = expand_aliases("react components")
        assert "reactjs" in result or "react.js" in result

    def test_multiple_aliases_expand(self):
        result = expand_aliases("nextjs tailwind postgres")
        assert "next.js" in result
        assert "tailwindcss" in result
        assert "postgresql" in result


class TestOrFallback:
    """OR fallback test: FTS5 should find results when AND fails."""

    @pytest.fixture
    def index(self, tmp_path):
        idx = SearchIndex(db_path=str(tmp_path / "test_memory.db"))
        idx.open()
        idx.rebuild([
            {"id": "t1", "content": "tailwindcss utility classes",
             "search_text": "tailwindcss utility classes for responsive design",
             "section_path": ["Test"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 1},
            {"id": "t2", "content": "next.js file conventions",
             "search_text": "next.js file conventions and routing patterns",
             "section_path": ["Test"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 2},
            {"id": "t3", "content": "postgres connection pooling",
             "search_text": "postgres connection pooling with supavisor",
             "section_path": ["Test"], "kind": "bullet",
             "source_path": "/tmp/test.md", "line_start": 3},
        ])
        yield idx
        idx.close()

    def test_and_query_returns_results(self, index):
        """Exact AND matches should still work (possibly via alias expansion or OR fallback)."""
        results = index.search("tailwindcss utility", limit=5)
        # Should find results (source may be fts5, fts5_or_fallback, or alias-expanded)
        assert len(results) >= 1

    def test_or_fallback_finds_results(self, index):
        """Query with no AND match should fall back to OR."""
        results = index.search("tailwind classes", limit=5)
        assert len(results) >= 1
        # Should be fts5_or_fallback source
        assert any(r["source"] == "fts5_or_fallback" for r in results)

    def test_alias_expansion_helps_search(self, index):
        """Alias expansion should help find entries with canonical terms."""
        results = index.search("nextjs conventions", limit=5)
        assert len(results) >= 1

    def test_postgres_alias_helps(self, index):
        """postgres alias should expand to postgresql."""
        results = index.search("postgres pooling", limit=5)
        assert len(results) >= 1
