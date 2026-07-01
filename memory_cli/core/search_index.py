"""Search index: SQLite FTS5 + BM25 for lexical/semantic memory search.

The search index is a **disposable cache** rebuilt from canonical memory
sources via `memory index --search --rebuild`. It is NOT a source of truth.

Schema:
  canonical_memories  — flat table with content_hash, section_path, kind, ...
  memories_fts        — FTS5 virtual table for BM25 search (porter + unicode61)

Usage:
    index = SearchIndex()
    index.open()
    index.rebuild(entries)
    results = index.search("sqlite caching")
    index.close()
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from memory_cli.constants import AGENT_MEMORY_DIR

# ── DB path ───────────────────────────────────────────────────────

SEARCH_DB_DIR = os.path.join(AGENT_MEMORY_DIR, "search")
SEARCH_DB_PATH = os.path.join(SEARCH_DB_DIR, "memory.db")
SCHEMA_VERSION = 1

# ── Query sanitizer ───────────────────────────────────────────────


# Characters that have special meaning in FTS5 queries
_FTS5_SPECIAL = re.compile(r'[\^"()\+\~\*]')
# Characters that need escaping in FTS5 token queries
_FTS5_UNSAFE = re.compile(r'[^\w@.\\/_-]')

# ── Alias / synonym map (configurable) ────────────────────────────
# Keys are canonical forms. Values are lists of common aliases.
# Applied during query expansion: if any alias is found, the
# canonical form is added to the query.
ALIAS_MAP: dict[str, list[str]] = {
    "next.js": ["nextjs", "next-js", "next_js"],
    "postgresql": ["postgres", "pg"],
    "tailwindcss": ["tailwind", "tailwind-css", "tailwind_css"],
    "javascript": ["js", "ecmascript"],
    "typescript": ["ts", "type script"],
    "reactjs": ["react", "react.js", "react-js"],
    "vscode": ["vs code", "visual studio code"],
}


def expand_aliases(query: str) -> str:
    """Expand aliases in a query string.

    For each token in the query, check if it matches any alias
    in ALIAS_MAP. If so, append the canonical form to the query.
    """
    if not query or not query.strip():
        return query

    query_lower = query.lower()
    tokens = set(query_lower.split())
    extra_terms: list[str] = []

    for canonical, aliases in ALIAS_MAP.items():
        canonical_lower = canonical.lower()
        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower in tokens or alias_lower in query_lower:
                if canonical_lower not in tokens:
                    extra_terms.append(canonical)
                break
        # Also check if canonical is in query → add aliases
        if canonical_lower in tokens:
            for alias in aliases:
                alias_lower = alias.lower()
                if alias_lower not in tokens:
                    extra_terms.append(alias)

    if extra_terms:
        return query + " " + " ".join(extra_terms)
    return query


def sanitize_fts_query(query: str) -> str:
    """Sanitize a user query for SQLite FTS5 MATCH.

    Strategy:
      1. Split query into tokens (whitespace-separated).
      2. For each token, also expand sub-tokens by splitting on
         punctuation (. / - _) — the unicode61 tokenizer splits
         these, so 'Next.js' becomes tokens 'Next' and 'js'.
      3. Escape/quote each token individually for FTS5.
      4. Join with implicit AND (space in FTS5).
      5. If MATCH throws an error, caller falls back to LIKE.

    Returns a safe FTS5 query string.
    """
    if not query or not query.strip():
        return ""

    query = query.strip()
    tokens = query.split()

    escaped_tokens = []
    for token in tokens:
        if not token:
            continue

        # Remove FTS5 special characters from token
        cleaned = _FTS5_SPECIAL.sub("", token)
        if not cleaned.strip():
            continue

        # If token has punctuation that FTS5 splits on, expand sub-tokens
        if re.search(r'[.\\/_-]', cleaned):
            # Add the full token (quoted)
            safe = cleaned.replace('"', '""')
            escaped_tokens.append(f'"{safe}"')
            # Also add sub-tokens (for FTS5 tokenizer splits)
            sub_tokens = [t for t in re.split(r'[.\\/_-]', cleaned) if len(t) > 1]
            escaped_tokens.extend(sub_tokens)
        elif _FTS5_UNSAFE.search(cleaned):
            # Token has other unsafe chars — wrap in quotes
            safe = cleaned.replace('"', '""')
            escaped_tokens.append(f'"{safe}"')
        else:
            escaped_tokens.append(cleaned)

    if not escaped_tokens:
        return ""

    # Join with space = implicit AND in FTS5
    return " ".join(escaped_tokens)


def sanitize_fts_query_with_fallback(query: str, db: sqlite3.Connection) -> str:
    """Sanitize query and validate against FTS5 syntax."""
    safe = sanitize_fts_query(query)
    if not safe:
        return ""

    # Test the query syntax if DB is provided
    if db:
        try:
            db.execute("SELECT rank FROM memories_fts WHERE memories_fts MATCH ? LIMIT 0", (safe,))
            return safe
        except sqlite3.OperationalError:
            # FTS syntax error — fall back to simpler query
            fallback = " ".join(
                f'"{re.sub(_FTS5_SPECIAL, "", t)}"'
                for t in query.split()
                if re.sub(_FTS5_SPECIAL, "", t).strip()
            )
            return fallback

    return safe


# ── SearchIndex ───────────────────────────────────────────────────


class SearchIndex:
    """SQLite FTS5 search index for memory entries.

    Not thread-safe. Use one instance per process.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or SEARCH_DB_PATH
        self._db: sqlite3.Connection | None = None

    @property
    def is_open(self) -> bool:
        return self._db is not None

    def open(self) -> None:
        """Open or create the search index database."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._db = sqlite3.connect(self._db_path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    def _ensure_schema(self) -> None:
        """Create schema if it doesn't exist or needs migration."""
        if self._db is None:
            return

        # Check schema version
        cur = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone() is None:
            version = 0
        else:
            version = self._db.execute("SELECT version FROM schema_version").fetchone()[0]

        if version < 1:
            self._create_v1()

    def _create_v1(self) -> None:
        """Create or migrate to schema version 1."""
        if self._db is None:
            return

        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS canonical_memories (
                memory_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                search_text TEXT NOT NULL,
                section_path TEXT,
                kind TEXT,
                timestamp TEXT,
                source_path TEXT,
                line_start INTEGER,
                content_hash TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                memory_id UNINDEXED,
                search_text,
                section_path,
                content='canonical_memories',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON canonical_memories BEGIN
                INSERT INTO memories_fts(rowid, memory_id, search_text, section_path)
                VALUES (new.rowid, new.memory_id, new.search_text, new.section_path);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON canonical_memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, memory_id, search_text, section_path)
                VALUES ('delete', old.rowid, old.memory_id, old.search_text, old.section_path);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON canonical_memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, memory_id, search_text, section_path)
                VALUES ('delete', old.rowid, old.memory_id, old.search_text, old.section_path);
                INSERT INTO memories_fts(rowid, memory_id, search_text, section_path)
                VALUES (new.rowid, new.memory_id, new.search_text, new.section_path);
            END;

            CREATE TABLE IF NOT EXISTS search_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER);
            DELETE FROM schema_version;
            INSERT INTO schema_version (version) VALUES (1);
        """)
        self._db.commit()

    def rebuild(self, entries: list[dict]) -> dict[str, Any]:
        """Rebuild the search index from canonical memory entries.

        Args:
            entries: List of dicts with keys from MemoryEntry dataclass.

        Returns:
            Stats dict with counts and timing.
        """
        if self._db is None:
            raise RuntimeError("SearchIndex not opened")

        t0 = datetime.now()
        self._db.execute("PRAGMA synchronous=OFF")
        self._db.execute("PRAGMA cache_size=-8000")  # 8MB cache

        # Use a transaction for bulk insert
        self._db.execute("BEGIN")
        try:
            # Clear existing data (without dropping the table → triggers fire)
            self._db.execute("DELETE FROM canonical_memories")
            self._db.execute("DELETE FROM memories_fts")
            self._db.execute("DELETE FROM search_index_meta")

            for entry in entries:
                self._db.execute(
                    """INSERT OR REPLACE INTO canonical_memories
                       (memory_id, content, search_text, section_path, kind,
                        timestamp, source_path, line_start, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.get("id", ""),
                        entry.get("content", ""),
                        entry.get("search_text", ""),
                        json.dumps(entry.get("section_path", [])),
                        entry.get("kind", ""),
                        entry.get("timestamp"),
                        entry.get("source_path", ""),
                        entry.get("line_start", 0),
                        entry.get("content_hash", ""),
                    ),
                )

            self._db.execute("END")

            # Count results
            count = self._db.execute("SELECT COUNT(*) FROM canonical_memories").fetchone()[0]

            self._db.execute("PRAGMA synchronous=NORMAL")
            elapsed = (datetime.now() - t0).total_seconds()

            return {
                "entries_count": count,
                "elapsed_seconds": round(elapsed, 3),
                "schema_version": SCHEMA_VERSION,
                "db_path": self._db_path,
            }
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def search(
        self, query: str, limit: int = 20, include_raw: bool = False
    ) -> list[dict[str, Any]]:
        """Search the FTS5 index with BM25 ranking.

        Args:
            query: User query string (auto-sanitized).
            limit: Max results.
            include_raw: Include raw FTS match info.

        Returns:
            List of result dicts with id, content, score, section, ...
        """
        if self._db is None:
            raise RuntimeError("SearchIndex not opened")

        if not query or not query.strip():
            return []

        safe_query = sanitize_fts_query_with_fallback(query, self._db)
        if not safe_query:
            return []

        # Expand aliases before the OR fallback
        expanded_query = expand_aliases(safe_query)
        if expanded_query != safe_query:
            safe_query = sanitize_fts_query_with_fallback(expanded_query, self._db)
            if not safe_query:
                safe_query = sanitize_fts_query_with_fallback(query, self._db)
                if not safe_query:
                    return []

        try:
            cur = self._db.execute(
                """SELECT
                       cm.memory_id, cm.content, cm.search_text, cm.section_path,
                       cm.kind, cm.timestamp, cm.source_path, cm.line_start,
                       rank
                   FROM memories_fts
                   JOIN canonical_memories cm ON memories_fts.rowid = cm.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, limit),
            )

            results = []
            for row in cur.fetchall():
                result = {
                    "id": row[0],
                    "content": row[1],
                    "search_text": row[2],
                    "section_path": json.loads(row[3]) if row[3] else [],
                    "kind": row[4],
                    "timestamp": row[5],
                    "source_path": row[6],
                    "line_start": row[7],
                    "score": round(-row[8], 4),  # BM25 rank is negative → higher = better
                    "source": "fts5",
                }
                if include_raw:
                    result["raw_query"] = safe_query
                results.append(result)

            # OR fallback: if AND returned nothing and query has multiple tokens
            if len(results) == 0 and len(query.split()) > 1:
                or_tokens = [t for t in query.split() if len(t) > 1]
                if or_tokens:
                    or_query = " OR ".join(or_tokens)
                    cur = self._db.execute(
                        """SELECT
                               cm.memory_id, cm.content, cm.search_text, cm.section_path,
                               cm.kind, cm.timestamp, cm.source_path, cm.line_start,
                               rank
                           FROM memories_fts
                           JOIN canonical_memories cm ON memories_fts.rowid = cm.rowid
                           WHERE memories_fts MATCH ?
                           ORDER BY rank
                           LIMIT ?""",
                        (or_query, limit),
                    )
                    for row in cur.fetchall():
                        result = {
                            "id": row[0],
                            "content": row[1],
                            "search_text": row[2],
                            "section_path": json.loads(row[3]) if row[3] else [],
                            "kind": row[4],
                            "timestamp": row[5],
                            "source_path": row[6],
                            "line_start": row[7],
                            "score": round(-row[8], 4),
                            "source": "fts5_or_fallback",
                        }
                        results.append(result)

            return results

        except sqlite3.OperationalError as e:
            # Query syntax error — fall back to LIKE
            like_query = f"%{query}%"
            cur = self._db.execute(
                """SELECT memory_id, content, search_text, section_path,
                          kind, timestamp, source_path, line_start
                   FROM canonical_memories
                   WHERE search_text LIKE ?
                   LIMIT ?""",
                (like_query, limit),
            )
            results = []
            for row in cur.fetchall():
                results.append({
                    "id": row[0],
                    "content": row[1],
                    "search_text": row[2],
                    "section_path": json.loads(row[3]) if row[3] else [],
                    "kind": row[4],
                    "timestamp": row[5],
                    "source_path": row[6],
                    "line_start": row[7],
                    "score": 0.0,
                    "source": "fts_like_fallback",
                })
            return results

    def upsert(self, entry: dict) -> bool:
        """Upsert a single memory entry into the index.

        Args:
            entry: Dict with id, content, search_text, ...

        Returns:
            True on success.
        """
        if self._db is None:
            return False

        try:
            self._db.execute(
                """INSERT OR REPLACE INTO canonical_memories
                   (memory_id, content, search_text, section_path, kind,
                    timestamp, source_path, line_start, content_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    entry.get("id", ""),
                    entry.get("content", ""),
                    entry.get("search_text", ""),
                    json.dumps(entry.get("section_path", [])),
                    entry.get("kind", ""),
                    entry.get("timestamp"),
                    entry.get("source_path", ""),
                    entry.get("line_start", 0),
                    entry.get("content_hash", ""),
                ),
            )
            self._db.commit()
            return True
        except sqlite3.OperationalError:
            return False

    def delete(self, memory_ids: list[str]) -> int:
        """Delete entries by memory ID.

        Returns:
            Count of deleted rows.
        """
        if self._db is None or not memory_ids:
            return 0

        count = 0
        for mid in memory_ids:
            cur = self._db.execute(
                "DELETE FROM canonical_memories WHERE memory_id = ?", (mid,)
            )
            count += cur.rowcount
        self._db.commit()
        return count

    def count(self) -> dict[str, Any]:
        """Return index stats."""
        if self._db is None:
            return {"total": 0, "error": "not open"}

        total = self._db.execute("SELECT COUNT(*) FROM canonical_memories").fetchone()[0]
        kinds = {}
        try:
            cur = self._db.execute("SELECT kind, COUNT(*) FROM canonical_memories GROUP BY kind")
            for row in cur:
                kinds[row[0]] = row[1]
        except sqlite3.OperationalError:
            pass

        db_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0

        return {
            "total": total,
            "by_kind": kinds,
            "db_size_bytes": db_size,
            "db_path": self._db_path,
            "schema_version": SCHEMA_VERSION,
        }

    def health(self) -> dict[str, Any]:
        """Return health check info."""
        counts = self.count()
        issues = []
        if counts.get("total", 0) == 0:
            issues.append("Search index is empty — run `memory index --search --rebuild`")
        return {
            "ok": len(issues) == 0,
            "issues": issues,
            **(counts if counts else {}),
        }
