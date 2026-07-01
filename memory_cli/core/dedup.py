from __future__ import annotations
"""Jaccard similarity deduplication for memory entries."""

import re
from typing import Iterable


_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "as", "is", "was", "are",
    "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "it", "its", "i", "we", "you", "they",
    "he", "she", "that", "this", "these", "those", "not", "no",
    "nor", "so", "if", "then", "else", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "only", "own", "same", "too",
})


def tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase non-stopword tokens.
    
    Strips markdown formatting, timestamps [2026-...], and
    bullet prefixes.
    """
    # Remove markdown link syntax
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove timestamps
    text = re.sub(r"\[\d{4}-\d{2}-\d{2}\]", "", text)
    # Remove bullet markers
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    # Lowercase and split on non-alpha
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def is_duplicate(
    candidate: str,
    existing: Iterable[str],
    threshold: float = 0.55,
) -> bool:
    """Check if candidate is a duplicate of any existing entry.
    
    Returns True if Jaccard similarity exceeds threshold for any
    existing entry.
    """
    candidate_tokens = tokenize(candidate)
    if not candidate_tokens:
        return False
    for entry in existing:
        entry_tokens = tokenize(entry)
        sim = jaccard_similarity(candidate_tokens, entry_tokens)
        if sim >= threshold:
            return True
    return False
