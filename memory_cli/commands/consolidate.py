from __future__ import annotations
"""memory consolidate — LLM session consolidation.

Merges patterns from consolidate-session.sh and consolidate.py:
  - Parses transcript (Pi JSON stdin or Factory log file)
  - Sends last N exchanges to cheap LLM
  - Parses CATEGORY: lines from response
  - Classifies, dedups, and promotes to memories.md sections
  - Seeds MCP graph
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from memory_cli.adapters import resolve_adapters
from memory_cli.core.atomic import read_file_safe, atomic_write
from memory_cli.core.config import get_api_key
from memory_cli.core.dedup import is_duplicate
from memory_cli.constants import (
    GLOBAL_MEM_PATH,
    DEFAULT_MODEL,
    DEFAULT_API_URL,
    MAX_EXCHANGES,
    MAX_CHARS_PER_EXCHANGE,
    MAX_MEMORY_CONTEXT_CHARS,
    PREFIX_MAP,
    PROTECTED_SECTIONS,
    CONSOLIDATION_LOG,
)


def run(
    config: dict,
    adapters: list[str],
    source: str | None = None,
    session: str | None = None,
    transcript: str | None = None,
    dry_run: bool = False,
    no_llm: bool = False,
    model: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Consolidate session transcript into memory entries."""
    result: dict[str, Any] = {
        "command": "consolidate",
        "status": "ok",
        "session_id": session or "unknown",
        "source": source or "unknown",
        "exchanges_analyzed": 0,
        "findings": 0,
        "promoted": 0,
        "duplicates_skipped": 0,
        "discovery_blocks_cleared": 0,
        "llm_used": False,
        "results": [],
    }
    
    # Parse transcript
    messages = _parse_transcript(source, session, transcript)
    if not messages:
        result["status"] = "no_transcript"
        result["error"] = "Could not parse transcript — no messages found"
        return result
    
    # Keep last N exchanges
    exchanges = _extract_exchanges(messages)
    result["exchanges_analyzed"] = len(exchanges)
    
    if not exchanges:
        result["status"] = "no_exchanges"
        return result
    
    # LLM or rule-based extraction
    if no_llm:
        findings = _rule_based_extraction(exchanges)
    else:
        api_key = get_api_key(config)
        if not api_key:
            result["status"] = "error"
            result["error"] = "No API key found — set OPENCODE_GO_API_KEY or use --no-llm"
            return result
        findings = _llm_extraction(
            exchanges=exchanges,
            config=config,
            api_key=api_key,
            model=model or config.get("llm", {}).get("model", DEFAULT_MODEL),
        )
        result["llm_used"] = True
    
    result["findings"] = len(findings)
    
    if not findings:
        result["status"] = "nothing_found"
        return result
    
    # Dedup against existing memories
    existing_content = _get_existing_entries()
    deduped = []
    for f in findings:
        if is_duplicate(f["content"], existing_content, threshold=0.55):
            result["duplicates_skipped"] += 1
        else:
            deduped.append(f)
    
    # Promote to memories.md
    if not dry_run and deduped:
        _promote_to_memory(deduped, existing_content, result)
        result["promoted"] = len(deduped)
        
        # Update existing_content for graph seeding
        existing_content.extend(f["content"] for f in deduped)
    
    result["findings"] = find_report if (find_report := result.setdefault("findings", len(findings))) else len(findings)
    result["results"] = deduped
    
    # Write to adapters (graph)
    if not dry_run and deduped:
        adapter_instances = resolve_adapters(adapters, config, capability="write")
        for entry in deduped:
            for a in adapter_instances:
                if a.name != "file":  # file already written by _promote_to_memory
                    a.write(entry)
    
    # Log
    _log_consolidation(result)
    
    return result


def _parse_transcript(
    source: str | None,
    session: str | None,
    transcript: str | None,
) -> list[dict]:
    """Parse transcript into list of {role, content} messages."""
    messages: list[dict] = []
    
    if source == "pi" or (source is None and not transcript):
        # Read Pi JSON from stdin
        try:
            data = json.loads(sys.stdin.read())
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        role = item.get("role", "user")
                        content = item.get("content", "")
                        if content:
                            messages.append({"role": role, "content": str(content)})
            elif isinstance(data, dict):
                # Pi session format
                exchanges = data.get("exchanges", data.get("messages", data.get("history", [])))
                if isinstance(exchanges, list):
                    for ex in exchanges:
                        if isinstance(ex, dict):
                            role = ex.get("role", ex.get("type", "user"))
                            content = ex.get("content", ex.get("message", ""))
                            if content:
                                messages.append({"role": role, "content": str(content)})
        except (json.JSONDecodeError, ValueError):
            pass
    
    if source == "factory" and transcript:
        # Factory Droid log file — one message per line
        try:
            with open(transcript) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("User:") or line.startswith("U:"):
                        messages.append({"role": "user", "content": line[line.index(":")+1:].strip()})
                    elif line.startswith("Assistant:") or line.startswith("A:"):
                        messages.append({"role": "assistant", "content": line[line.index(":")+1:].strip()})
        except OSError:
            pass
    
    return messages


def _extract_exchanges(messages: list[dict]) -> list[str]:
    """Extract last N user+assistant exchanges as text.
    
    Returns a list of formatted exchange strings.
    """
    exchanges = []
    for msg in messages[-MAX_EXCHANGES * 2:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if len(content) > MAX_CHARS_PER_EXCHANGE:
            content = content[:MAX_CHARS_PER_EXCHANGE] + "..."
        exchanges.append(f"[{role.upper()}]: {content}")
    return exchanges


def _llm_extraction(
    exchanges: list[str],
    config: dict,
    api_key: str,
    model: str,
) -> list[dict]:
    """Send exchanges to LLM and parse CATEGORY: lines from response."""
    
    # Read existing memory context
    memory_context = read_file_safe(GLOBAL_MEM_PATH)[:MAX_MEMORY_CONTEXT_CHARS]
    
    system_prompt = """You analyze coding session transcripts and extract new knowledge.

For each finding, output a line in one of these formats:
  DECISION: content
  PREFERENCE: content  
  LEARNING: content
  PROJECT-FACT: content
  GOTCHA: content
  RULE: content
  CONVENTION: content
  ARCHITECTURE: content

Rules:
- Only output findings that are NEW and NOT obvious from context
- Keep content concise (under 200 chars)
- If nothing new found, output: NOTHING
- Do NOT add any commentary or markdown"""
    
    exchange_text = "\n\n".join(exchanges)
    
    user_prompt = f"""Existing memory context (for dedup):
{memory_context}

Recent session exchanges to analyze:
{exchange_text}

Output findings:"""
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
    }
    
    try:
        response = _call_llm(config, api_key, payload)
    except Exception as e:
        return []
    
    return _parse_llm_response(response)


def _call_llm(config: dict, api_key: str, payload: dict) -> str:
    """Call LLM via `pi -p` — same model as the agent session.

    Replaces the old curl-based API call. Uses pi's own model, auth,
    and environment — no separate API key needed. Falls back to curl
    if pi is not available.
    """
    import shutil

    messages = payload.get("messages", [])
    system_msg = ""
    user_msg = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_msg = content
        elif role == "user":
            user_msg = content

    pi_path = shutil.which("pi")
    if pi_path and user_msg:
        model = payload.get("model", DEFAULT_MODEL)
        try:
            cmd = [pi_path, "-p", "--system-prompt", system_msg]
            proc = subprocess.run(
                cmd,
                input=user_msg,
                capture_output=True,
                text=True,
                timeout=60,
            )
            stdout = proc.stdout.strip()
            if stdout:
                return stdout
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    # Fallback to curl
    api_url = config.get("llm", {}).get("api_url", DEFAULT_API_URL)
    cmd = [
        "curl", "-s", api_url,
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    result = json.loads(proc.stdout)
    return (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )


def _parse_llm_response(response: str) -> list[dict]:
    """Parse CATEGORY: lines from LLM response."""
    findings: list[dict] = []
    
    if response.strip().upper() == "NOTHING" or "NOTHING" in response.strip().upper()[:20]:
        return findings
    
    for line in response.split("\n"):
        line = line.strip()
        # Match CATEGORY: content
        for prefix in PREFIX_MAP:
            pattern = rf"^{prefix}\s*:\s*(.+)"
            m = re.match(pattern, line, re.IGNORECASE)
            if m:
                content = m.group(1).strip()
                if content and len(content) > 5:
                    findings.append({
                        "content": content,
                        "category": prefix.lower(),
                        "target_section": PREFIX_MAP[prefix],
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "source": "consolidate",
                    })
    
    return findings


def _classify_finding(content: str) -> tuple[str, str]:
    """Classify a finding string into (category, target_section)."""
    lower = content.lower()
    if re.search(r"(we )?(decided|chose|switched to|migrated|adopted|moved to|settled on|went with)", lower):
        return "decision", "Validated Approaches"
    elif re.search(r"(i |we )?(learned|discovered|realized|found that|key takeaway|turns out)", lower):
        return "learning", "Key Learnings"
    elif re.search(r"(i prefer|i like|i find it easier|works better|much nicer)", lower):
        return "preference", "User Preferences"
    elif re.search(r"(watch out|be careful|gotcha|this is tricky|easy to miss)", lower):
        return "gotcha", "Gotchas & Traps"
    else:
        return "learning", "Key Learnings"


def _rule_based_extraction(exchanges: list[str]) -> list[dict]:
    """Extract findings using rule-based patterns (no LLM)."""
    findings: list[dict] = []
    
    decision_patterns = [
        r"we (decided|chose|switched to|migrated|adopted|moved to) (.+?)(?:\.|$)",
        r"let's (use|go with|try) (.+?)(?:\.|$)",
    ]
    learning_patterns = [
        r"(i learned|key takeaway|important lesson|turns out) (.+?)(?:\.|$)",
        r"(discovered|realized|found) (that )?(.+?)(?:\.|$)",
    ]
    
    for exchange in exchanges:
        for pattern in decision_patterns:
            m = re.search(pattern, exchange, re.IGNORECASE)
            if m:
                content = m.group(0).strip()
                if len(content) > 10:
                    findings.append({
                        "content": content,
                        "category": "decision",
                        "target_section": "Validated Approaches",
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "source": "consolidate",
                    })
        
        for pattern in learning_patterns:
            m = re.search(pattern, exchange, re.IGNORECASE)
            if m:
                content = m.group(0).strip()
                if len(content) > 10:
                    findings.append({
                        "content": content,
                        "category": "learning",
                        "target_section": "Key Learnings",
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "source": "consolidate",
                    })
    
    return findings


def _get_existing_entries() -> list[str]:
    """Extract existing entry content from memories.md for dedup."""
    content = read_file_safe(GLOBAL_MEM_PATH)
    entries = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- [") and "]" in stripped:
            content_part = stripped[stripped.index("]") + 1:].strip()
            if content_part:
                entries.append(content_part)
    return entries


def _promote_to_memory(
    findings: list[dict],
    existing_content: list[str],
    result: dict,
) -> None:
    """Insert promoted findings into correct sections of memories.md."""
    content = read_file_safe(GLOBAL_MEM_PATH)
    
    for finding in findings:
        section = finding["target_section"]
        if section in PROTECTED_SECTIONS:
            continue
        
        section_header = f"## {section}"
        ts = finding["timestamp"]
        line = f"- [{ts}] {finding['content']}\n"
        
        if section_header not in content:
            # Find the last section and append after it, or add at end
            section_pattern = r"^##\s+"
            sections = re.findall(r"^## (.+)$", content, re.MULTILINE)
            if sections:
                last_section = sections[-1]
                last_header = f"## {last_section}"
                # Insert after last line of last section
                lines = content.splitlines(keepends=True)
                new_lines = []
                inserted = False
                for i, ln in enumerate(lines):
                    new_lines.append(ln)
                    if ln.strip() == last_header and not inserted:
                        # Find end of last section
                        j = i + 1
                        while j < len(lines) and not lines[j].startswith("## "):
                            j += 1
                        new_lines.insert(j, f"\n{section_header}\n{line}")
                        inserted = True
                if inserted:
                    content = "".join(new_lines)
            else:
                content += f"\n{section_header}\n{line}"
        else:
            # Insert after section header
            lines = content.splitlines(keepends=True)
            new_lines = []
            inserted = False
            for i, ln in enumerate(lines):
                new_lines.append(ln)
                if ln.strip() == section_header and not inserted:
                    j = i + 1
                    while j < len(lines) and (
                        lines[j].strip().startswith("- ")
                        or not lines[j].strip()
                    ):
                        j += 1
                    new_lines.insert(j, f"  {line}")
                    inserted = True
            if inserted:
                content = "".join(new_lines)
    
    atomic_write(GLOBAL_MEM_PATH, content)


def _log_consolidation(result: dict) -> None:
    """Append structured entry to consolidation.log."""
    try:
        os.makedirs(os.path.dirname(CONSOLIDATION_LOG) or ".", exist_ok=True)
        entry = {
            "t": datetime.now(timezone.utc).isoformat(),
            "command": "consolidate",
            "session_id": result.get("session_id"),
            "exchanges": result.get("exchanges_analyzed"),
            "findings": result.get("findings"),
            "promoted": result.get("promoted"),
            "duplicates_skipped": result.get("duplicates_skipped"),
            "llm_used": result.get("llm_used"),
        }
        with open(CONSOLIDATION_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
