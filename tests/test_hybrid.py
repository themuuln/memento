"""Tests for hybrid retriever — RRF merge, cross-adapter dedup."""

import pytest
from memory_cli.core.hybrid import HybridRetriever


class TestHybridRetriever:
    """Tests for RRF-based grep + FTS5 merge."""

    @pytest.fixture
    def hybrid(self, tmp_path, monkeypatch):
        """Create a HybridRetriever with temp search index."""
        monkeypatch.setattr("memory_cli.core.search_index.SEARCH_DB_DIR",
                            str(tmp_path))
        h = HybridRetriever({})
        return h

    def test_initialization_does_not_crash(self, hybrid):
        assert hybrid is not None

    def test_empty_query_returns_no_matches(self, hybrid):
        result = hybrid.search("", limit=10)
        assert isinstance(result, dict)
        assert result["matches"] == 0

    def test_search_returns_ranked_results(self, hybrid):
        result = hybrid.search("sqlite", limit=10)
        assert isinstance(result, dict)
        assert "results" in result
        for r in result["results"]:
            assert "content" in r
            assert "score" in r
            assert "_matched_sources" in r

    def test_results_have_dedup_sources(self, hybrid):
        result = hybrid.search("sqlite", limit=10)
        for r in result["results"]:
            assert isinstance(r.get("_matched_sources"), list)

    def test_limit_respected(self, hybrid):
        result = hybrid.search("sqlite", limit=3)
        assert len(result["results"]) <= 3

    def test_no_match_returns_empty(self, hybrid):
        result = hybrid.search("xyznonexistent12345", limit=10)
        assert result["matches"] == 0
        assert result["results"] == []


class TestHybridRetrieverNoFile:
    """Edge case: missing memories.md file."""

    def test_missing_file_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr("memory_cli.constants.GLOBAL_MEM_PATH",
                            str(tmp_path / "nonexistent" / "memories.md"))
        monkeypatch.setattr("memory_cli.constants.GLOBAL_RULES_PATH",
                            str(tmp_path / "nonexistent" / "rules.md"))
        monkeypatch.setattr("memory_cli.constants.GLOBAL_PREFERENCES_PATH",
                            str(tmp_path / "nonexistent" / "preferences.md"))
        monkeypatch.setattr("memory_cli.core.search_index.SEARCH_DB_DIR",
                            str(tmp_path / "nonexistent"))

        h = HybridRetriever({})
        result = h.search("anything", limit=10)
        assert result["matches"] == 0
