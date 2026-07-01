"""memory inbox — process captured compaction inbox files.

Lists pending compaction snapshots and processes them through the
consolidation pipeline. Files are written by the Pi extension
memory-compaction-capture.ts.

Usage:
  memory inbox                                # List pending items
  memory inbox --process                      # Process oldest pending item
  memory inbox --process --all                # Process all pending items
  memory inbox --process --file <filename>    # Process specific file
  memory inbox --process --consolidate        # Also run LLM consolidation
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from memory_cli.constants import (
    CONSOLIDATION_LOG,
    COMPACTION_INBOX_DIR,
    COMPACTION_PROCESSED_DIR,
)


def run(
    config: dict,
    adapters: list[str],
    process: bool = False,
    all_files: bool = False,
    file: str | None = None,
    consolidate: bool = False,
    no_llm: bool = False,
    model: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Process compacted messages from the inbox directory."""
    result: dict[str, Any] = {
        "command": "inbox",
        "status": "ok",
        "pending": 0,
        "processed": 0,
        "items": [],
    }

    # Ensure directories exist
    os.makedirs(COMPACTION_INBOX_DIR, exist_ok=True)
    os.makedirs(COMPACTION_PROCESSED_DIR, exist_ok=True)

    # List pending items
    pending = _list_pending()
    result["pending"] = len(pending)
    result["items"] = pending

    if not process:
        return result

    # Determine which files to process
    targets: list[dict] = []

    if file:
        # Find specific file
        for p in pending:
            if p["basename"] == file or p["jsonl_path"].endswith(file):
                targets.append(p)
                break
        if not targets:
            result["status"] = "error"
            result["error"] = f"File not found in inbox: {file}"
            return result
    elif all_files:
        targets = pending
    else:
        # Process oldest
        if pending:
            targets = [pending[0]]

    if not targets:
        result["status"] = "nothing_to_process"
        return result

    # Process each target
    for target in targets:
        processed = _process_item(
            target=target,
            config=config,
            adapters=adapters,
            consolidate=consolidate,
            no_llm=no_llm,
            model=model,
            verbose=verbose,
        )
        result["processed"] += 1
        result.setdefault("results", []).append(processed)

    return result


def _list_pending() -> list[dict]:
    """List pending compaction items, sorted oldest-first."""
    items: list[dict] = []

    if not os.path.isdir(COMPACTION_INBOX_DIR):
        return items

    # Group by prefix: <timestamp>-<sessionid>.*
    groups: dict[str, dict] = {}

    for fname in os.listdir(COMPACTION_INBOX_DIR):
        fpath = os.path.join(COMPACTION_INBOX_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        # Strip extension to get prefix
        if fname.endswith(".jsonl"):
            prefix = fname[:-6]
        elif fname.endswith(".metadata.json"):
            prefix = fname[:-14]
        elif fname.endswith(".compact.json"):
            prefix = fname[:-13]
        elif fname.endswith(".json"):
            prefix = fname[:-5]
        else:
            continue

        if prefix not in groups:
            groups[prefix] = {"prefix": prefix, "jsonl": None, "metadata": None, "compact": None}

        if fname.endswith(".jsonl"):
            groups[prefix]["jsonl"] = fpath
        elif fname.endswith(".metadata.json"):
            groups[prefix]["metadata"] = fpath
        elif fname.endswith(".compact.json"):
            groups[prefix]["compact"] = fpath

    for prefix, g in groups.items():
        if not g["jsonl"]:
            continue  # No messages to process

        # Parse timestamp from prefix
        ts_str = prefix.split("-")[0] if "-" in prefix else ""
        timestamp = ""
        try:
            ts_int = int(ts_str)
            timestamp = datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            pass

        # Read metadata if available
        meta = {}
        if g["metadata"]:
            try:
                with open(g["metadata"]) as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass

        # Count messages
        message_count = 0
        if g["jsonl"]:
            try:
                with open(g["jsonl"]) as f:
                    message_count = sum(1 for line in f if line.strip())
            except OSError:
                pass

        items.append({
            "basename": prefix,
            "jsonl_path": g["jsonl"],
            "metadata_path": g["metadata"],
            "compact_path": g["compact"],
            "timestamp": timestamp or meta.get("captured_at", ""),
            "session_id": meta.get("session_id", ""),
            "reason": meta.get("reason", ""),
            "message_count": message_count,
            "tokens_before": meta.get("tokens_before", 0),
        })

    # Sort oldest first
    items.sort(key=lambda i: i["basename"])

    return items


def _process_item(
    target: dict,
    config: dict,
    adapters: list[str],
    consolidate: bool,
    no_llm: bool,
    model: str | None,
    verbose: bool,
) -> dict[str, Any]:
    """Process a single compaction item."""
    result: dict[str, Any] = {
        "basename": target["basename"],
        "status": "ok",
        "messages_loaded": 0,
        "findings": [],
    }

    jsonl_path = target["jsonl_path"]
    if not jsonl_path or not os.path.isfile(jsonl_path):
        result["status"] = "error"
        result["error"] = "JSONL file not found"
        return result

    # Load messages
    messages = _load_messages(jsonl_path)
    result["messages_loaded"] = len(messages)

    if not messages:
        result["status"] = "empty"
        # Still move to processed
        _move_to_processed(target, jsonl_path)
        return result

    # Apply rule-based extraction to find patterns
    findings = _extract_findings(messages, no_llm=no_llm, config=config)
    result["findings"] = findings

    # If --consolidate, run full LLM consolidation
    if consolidate:
        try:
            from memory_cli.commands.consolidate import run as consolidate_run

            exchange_text = "\n\n".join(
                f"[{m.get('role', 'unknown').upper()}]: {m.get('content', '')[:500]}"
                for m in messages[-20:]  # Last 20 exchanges
            )

            # Write to temp file for consolidate to read
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="memory-inbox-") as tf:
                tf.write(exchange_text)
                tf_path = tf.name

            consol_result = consolidate_run(
                config=config,
                adapters=adapters,
                source="factory",
                session=target.get("session_id"),
                transcript=tf_path,
                no_llm=no_llm,
                model=model,
                verbose=verbose,
            )
            result["consolidation"] = consol_result

            # Clean up temp file
            try:
                os.unlink(tf_path)
            except OSError:
                pass
        except Exception as e:
            result["consolidation_error"] = str(e)
            if verbose:
                import traceback
                print(f"  [memory inbox] Consolidation failed: {e}", file=__import__('sys').stderr)
                traceback.print_exc()

    # Move to processed
    _move_to_processed(target, jsonl_path)

    return result


def _load_messages(path: str) -> list[dict]:
    """Load messages from a JSONL file."""
    messages: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return messages


def _extract_findings(
    messages: list[dict],
    no_llm: bool,
    config: dict,
) -> list[dict]:
    """Extract findings from messages using rule-based patterns."""
    findings: list[dict] = []

    decision_patterns = [
        r"(?:we )?(?:decided|chose|switched to|migrated|adopted|moved to) (.+?)(?:\.|$)",
        r"let's (use|go with|try) (.+?)(?:\.|$)",
    ]
    learning_patterns = [
        r"(?:i |we )?(learned|key takeaway|important lesson|turns out|discovered|realized|found) (?:that )?(.+?)(?:\.|$)",
    ]
    gotcha_patterns = [
        r"(?:watch out|be careful|gotcha|pitfall|trap|common mistake|issue is that) (.+?)(?:\.|$)",
    ]
    architecture_patterns = [
        r"architecture(?: decision)?(?: is|:)? (.+?)(?:\.|$)",
        r"(?:app|system|service) (?:uses|runs on|built with|deployed to) (.+?)(?:\.|$)",
    ]

    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue

        # Check decisions
        for pat in decision_patterns:
            import re
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                findings.append({
                    "content": m.group(0).strip()[:200],
                    "category": "decision",
                    "source": f"compaction:{msg.get('role', 'unknown')}",
                })

        # Check learnings
        for pat in learning_patterns:
            import re
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                findings.append({
                    "content": m.group(0).strip()[:200],
                    "category": "learning",
                    "source": f"compaction:{msg.get('role', 'unknown')}",
                })

        # Check gotchas
        for pat in gotcha_patterns:
            import re
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                findings.append({
                    "content": m.group(0).strip()[:200],
                    "category": "gotcha",
                    "source": f"compaction:{msg.get('role', 'unknown')}",
                })

        # Check architecture
        for pat in architecture_patterns:
            import re
            m = re.search(pat, content, re.IGNORECASE)
            if m:
                findings.append({
                    "content": m.group(0).strip()[:200],
                    "category": "architecture",
                    "source": f"compaction:{msg.get('role', 'unknown')}",
                })

    # Dedup by content
    seen = set()
    deduped = []
    for f in findings:
        key = f["content"][:80]
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    
    return deduped


def _move_to_processed(target: dict, jsonl_path: str) -> None:
    """Move processed inbox files to processed/ directory."""
    prefix = target["basename"]

    # Move JSONL
    if jsonl_path and os.path.isfile(jsonl_path):
        dest = os.path.join(COMPACTION_PROCESSED_DIR, f"{prefix}.jsonl")
        try:
            shutil.move(jsonl_path, dest)
        except OSError:
            pass

    # Move metadata
    if target.get("metadata_path") and os.path.isfile(target["metadata_path"]):
        dest = os.path.join(COMPACTION_PROCESSED_DIR, f"{prefix}.metadata.json")
        try:
            shutil.move(target["metadata_path"], dest)
        except OSError:
            pass

    # Move compact log
    if target.get("compact_path") and os.path.isfile(target["compact_path"]):
        dest = os.path.join(COMPACTION_PROCESSED_DIR, f"{prefix}.compact.json")
        try:
            shutil.move(target["compact_path"], dest)
        except OSError:
            pass
