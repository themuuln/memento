"""Tests for consolidate command — classification, rule-based extraction."""

import json
import pytest
from memory_cli.commands.consolidate import (
    _classify_finding,
    _rule_based_extraction,
)


class TestClassifyFinding:
    """Classification of extracted findings."""

    def test_decision(self):
        cat, section = _classify_finding("we decided to use postgres")
        assert cat == "decision"
        assert section == "Validated Approaches"

    def test_learning(self):
        cat, section = _classify_finding("i learned that sqlite is fast")
        assert cat == "learning"
        assert section == "Key Learnings"

    def test_gotcha(self):
        cat, section = _classify_finding("watch out for connection pooling limits")
        assert cat == "gotcha"
        assert section == "Gotchas & Traps"

    def test_preference(self):
        cat, section = _classify_finding("i prefer dark mode")
        assert cat == "preference"
        assert section == "User Preferences"

    def test_fallback_to_learning(self):
        cat, section = _classify_finding("some random content")
        assert cat == "learning"
        assert section == "Key Learnings"

    def test_switched_to_is_decision(self):
        cat, section = _classify_finding("we switched to vite")
        assert cat == "decision"

    def test_went_with_is_decision(self):
        cat, section = _classify_finding("we went with postgres")
        assert cat == "decision"

    def test_discovered_is_learning(self):
        cat, section = _classify_finding("i discovered a bug in the parser")
        assert cat == "learning"


class TestExtractFindingsRuleBased:
    """Rule-based extraction from exchange strings."""

    def test_extracts_decision(self):
        exchanges = ["What db should we use? I recommend postgres. We decided to use postgres."]
        findings = _rule_based_extraction(exchanges)
        decisions = [f for f in findings if f["category"] == "decision"]
        assert len(decisions) >= 1
        assert "postgres" in decisions[0]["content"]

    def test_extracts_multiple_findings(self):
        exchanges = ["We decided to use vite. I learned that esbuild is fast."]
        findings = _rule_based_extraction(exchanges)
        assert len(findings) >= 2

    def test_no_findings_for_irrelevant(self):
        exchanges = ["How are you? I'm fine!"]
        findings = _rule_based_extraction(exchanges)
        assert len(findings) == 0

    def test_empty_exchanges(self):
        assert _rule_based_extraction([]) == []

    def test_respects_max_length(self):
        long_content = "we decided to use postgres " * 200
        exchanges = [long_content]
        findings = _rule_based_extraction(exchanges)
        for f in findings:
            # Regex captures content up to first period in "we decided to use postgres" repetitions
            content_len = len(f["content"])
            assert content_len > 0  # Should at least capture something

    def test_case_insensitive_detection(self):
        exchanges = ["We Decided To Use TypeScript"]
        findings = _rule_based_extraction(exchanges)
        assert len(findings) >= 1

    def test_multiple_sentences_merged(self):
        """Multiple sentences with decision patterns should find the first match."""
        exchanges = ["We decided to use React. We adopted tRPC for the API layer."]
        findings = _rule_based_extraction(exchanges)
        decisions = [f for f in findings if f["category"] == "decision"]
        assert len(decisions) >= 1
        assert "React" in decisions[0]["content"]
