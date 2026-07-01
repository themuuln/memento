"""Tests for dedup logic — Jaccard similarity, tokenization."""

import pytest
from memory_cli.core.dedup import (
    tokenize,
    jaccard_similarity,
    is_duplicate,
)


class TestTokenize:
    def test_lowercases(self):
        tokens = tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_strips_timestamps(self):
        tokens = tokenize("[2026-06-01] hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_strips_bullet_prefix(self):
        tokens = tokenize("- hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_strips_stopwords(self):
        tokens = tokenize("the and for hello")
        assert "the" not in tokens
        assert "hello" in tokens

    def test_removes_single_chars(self):
        tokens = tokenize("a b c hello")
        assert "a" not in tokens
        assert "hello" in tokens

    def test_empty_returns_empty(self):
        tokens = tokenize("")
        assert tokens == set()

    def test_only_stopwords_returns_empty(self):
        tokens = tokenize("the and for")
        assert tokens == set()

    def test_strips_markdown_links(self):
        tokens = tokenize("[link](url) here")
        assert "link" in tokens


class TestJaccardSimilarity:
    def test_identical_texts(self):
        assert jaccard_similarity(tokenize("hello world"), tokenize("hello world")) == 1.0

    def test_completely_different(self):
        assert jaccard_similarity(tokenize("abc"), tokenize("xyz")) == 0.0

    def test_partial_overlap(self):
        ts = tokenize("hello world")
        ts2 = tokenize("hello there")
        score = jaccard_similarity(ts, ts2)
        assert 0.0 < score < 1.0

    def test_empty_returns_zero(self):
        assert jaccard_similarity(set(), tokenize("hello")) == 0.0
        assert jaccard_similarity(set(), set()) == 0.0


class TestIsDuplicate:
    def test_exact_above_threshold(self):
        assert is_duplicate("We decided to use postgres",
                            ["We decided to use postgres"])

    def test_different_below_threshold(self):
        assert not is_duplicate("We decided to use postgres",
                                ["The sky is blue"])

    def test_similar_above_default_threshold(self):
        assert is_duplicate("We decided to use postgres for the database",
                            ["We decided to use postgres"])

    def test_custom_threshold(self):
        assert is_duplicate("hello world", ["hello there"], threshold=0.2)
        assert not is_duplicate("hello world", ["completely different"], threshold=0.2)

    def test_empty_candidate_returns_false(self):
        assert not is_duplicate("", ["anything"])

    def test_empty_existing_returns_false(self):
        assert not is_duplicate("hello", [])
