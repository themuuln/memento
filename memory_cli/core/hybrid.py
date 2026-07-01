"""HybridRetriever — merge grep + FTS5 results via RRF.

Deduplicates by memory_id, applies Reciprocal Rank Fusion scoring,
and logs shadow metrics for evaluation.

Usage:
    retriever = HybridRetriever(config)
    results = retriever.search("sqlite caching", limit=5)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.constants import LOG_DIR


# Default RRF constant
K = 60


def _rrf_score(rank: int, k: int = K) -> float:
    """Reciprocal rank fusion score for a single rank."""
    return 1.0 / (k + rank)


class HybridRetriever:
    """Merge results from multiple adapters with RRF scoring."""

    def __init__(self, config: dict):
        self._config = config

    def search(
        self,
        query: str,
        limit: int = 20,
        adapters: list[str] | None = None,
        shadow_log: bool = True,
    ) -> dict[str, Any]:
        """Search all adapters, merge via RRF.

        Args:
            query: Search query.
            limit: Max results.
            adapters: Adapter names to search (default: file, search).
            shadow_log: If True, log latency/overlap metrics.

        Returns:
            dict with results, scores, and shadow metrics.
        """
        t0 = datetime.now()
        result: dict[str, Any] = {
            "query": query,
            "matches": 0,
            "results": [],
            "hybrid": {
                "sources": [],
            },
        }

        if not query or not query.strip():
            return result

        adapter_names = adapters or ["file", "search"]
        instances = resolve_adapters(adapter_names, self._config, capability="read")

        # Collect candidates from each adapter with source-local rank
        all_candidates: list[dict] = []
        source_times: dict[str, float] = {}

        for inst in instances:
            src_t0 = datetime.now()
            try:
                candidates = inst.read(query, limit=limit * 2)
            except Exception:
                candidates = []
            src_elapsed = (datetime.now() - src_t0).total_seconds()
            source_times[inst.name] = round(src_elapsed, 4)

            # Assign source tag and track source-local rank
            for rank, c in enumerate(candidates):
                if "source" not in c:
                    c["source"] = inst.name
                c["_source_rank"] = rank

            all_candidates.extend(candidates)

        if not all_candidates:
            result["hybrid"]["latency_ms"] = source_times
            result["hybrid"]["total_time_ms"] = round(
                (datetime.now() - t0).total_seconds() * 1000, 1
            )
            return result

        # Merge via RRF
        merged = self._rrf_merge(all_candidates)

        # Top-k
        merged = merged[:limit]
        result["results"] = merged
        result["matches"] = len(merged)

        t_elapsed = (datetime.now() - t0).total_seconds() * 1000
        result["hybrid"] = {
            "sources": list(source_times.keys()),
            "latency_ms": source_times,
            "total_time_ms": round(t_elapsed, 1),
        }

        # Shadow log
        if shadow_log:
            self._log_shadow(query, result, source_times)

        return result

    def _rrf_merge(self, candidates: list[dict]) -> list[dict]:
        """Merge candidates via RRF, deduping by content."""
        import hashlib

        def _content_key(c: dict) -> str:
            """Generate a dedup key from the candidate's content (not adapter-specific ID)."""
            content = c.get("content", "") or c.get("search_text", "") or ""
            clean = content.strip().lower()[:200]
            return hashlib.sha256(clean.encode()).hexdigest()[:16]

        # Group by dedup key
        dedup_map: dict[str, dict] = {}
        for i, c in enumerate(candidates):
            # Use memory_id if available, otherwise content hash
            dedup_key = _content_key(c)

            if dedup_key not in dedup_map:
                c["_scores"] = {c.get("source", "unknown"): []}
                c["_rrf"] = 0.0
                dedup_map[dedup_key] = c
            else:
                existing = dedup_map[dedup_key]
                # Track which sources matched
                source = c.get("source", "unknown")
                if source not in existing["_scores"]:
                    existing["_scores"][source] = []

            # Apply RRF score from this candidate's source-local rank
            source = c.get("source", "unknown")
            rank = c.get("_source_rank", 0)
            dedup_map[dedup_key]["_scores"][source].append(rank)

        # Calculate final RRF per entry
        for entry in dedup_map.values():
            total_rrf = 0.0
            for source, positions in entry["_scores"].items():
                for pos in positions:
                    total_rrf += _rrf_score(pos)
            entry["_rrf"] = round(total_rrf, 4)
            # Cleanup internal fields
            sources = list(entry["_scores"].keys())
            del entry["_scores"]
            for k in ("_position", "_source_rank"):
                entry.pop(k, None)
            # Add source metadata
            entry["_matched_sources"] = sources

        # Sort by RRF score descending
        sorted_entries = sorted(
            dedup_map.values(),
            key=lambda e: e.get("_rrf", 0),
            reverse=True,
        )

        # Rename _rrf to score for output
        for e in sorted_entries:
            e["score"] = e.pop("_rrf")

        return sorted_entries

    def _log_shadow(
        self,
        query: str,
        result: dict,
        source_times: dict[str, float],
    ) -> None:
        """Append shadow evaluation log."""
        try:
            log_path = self._log_path()
            entry = {
                "t": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "matches": result.get("matches", 0),
                "sources": list(source_times.keys()),
                "latency_ms": source_times,
                "total_time_ms": result.get("hybrid", {}).get("total_time_ms", 0),
            }
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
        except OSError:
            pass

    def _log_path(self) -> str:
        import os
        os.makedirs(LOG_DIR, exist_ok=True)
        return os.path.join(LOG_DIR, "hybrid-search-shadow.log")
