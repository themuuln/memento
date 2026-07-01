from __future__ import annotations
"""Path constants, default patterns, and configuration defaults."""

import os

# ── Root ──────────────────────────────────────────────────────────
AGENT_MEMORY_DIR = os.environ.get(
    "AGENT_MEMORY_DIR",
    os.path.expanduser("~/.agent-memory"),
)

# ── Storage paths ──────────────────────────────────────────────────
GLOBAL_MEM_PATH = os.path.join(AGENT_MEMORY_DIR, "global", "memories.md")
GLOBAL_RULES_PATH = os.path.join(AGENT_MEMORY_DIR, "global", "rules.md")
GLOBAL_PREFERENCES_PATH = os.path.join(AGENT_MEMORY_DIR, "global", "preferences.md")
GRAPH_FILE = os.path.join(AGENT_MEMORY_DIR, "graph", "memory-graph.jsonl")
ARCHIVE_DIR = os.path.join(AGENT_MEMORY_DIR, "archive", "entries")
HOT_DIR = os.path.join(ARCHIVE_DIR, "hot")
WARM_DIR = os.path.join(ARCHIVE_DIR, "warm")
COLD_DIR = os.path.join(ARCHIVE_DIR, "cold")
LOG_DIR = os.path.join(AGENT_MEMORY_DIR, "logs")
CONSOLIDATION_LOG = os.path.join(LOG_DIR, "consolidation.log")
CLI_LOG = os.path.join(LOG_DIR, "memory-cli.log")
LOCK_DIR = os.path.join(AGENT_MEMORY_DIR, ".locks")
CONFIG_PATH = os.path.join(AGENT_MEMORY_DIR, "config.json")

# ── Compaction inbox ───────────────────────────────────────────────
COMPACTION_INBOX_DIR = os.path.join(AGENT_MEMORY_DIR, "inbox", "compaction")
COMPACTION_PROCESSED_DIR = os.path.join(COMPACTION_INBOX_DIR, "..", "processed")

# ── Archive tier defaults ──────────────────────────────────────────
TIER_DEFAULTS = {
    "hot": {"max_entries": 20, "dir": "archive/entries/hot"},
    "warm": {"max_entries": 200, "dir": "archive/entries/warm"},
    "cold": {"max_entries": 2000, "dir": "archive/entries/cold"},
}

# ── Capture triggers ───────────────────────────────────────────────
CAPTURE_TRIGGERS = [
    "remember this:",
    "note:",
    "we decided:",
    "important:",
    "key insight:",
    "lesson learned:",
    "decision:",
    "learning:",
    "preference:",
]

NATURAL_LANGUAGE_PATTERNS = {
    "decision": [
        "we decided", "we chose", "we switched to",
        "we migrated", "we adopted", "we moved to",
        "we went with", "we settled on",
    ],
    "learning": [
        "i learned", "i discovered", "i realized",
        "key takeaway", "turns out", "important lesson",
    ],
    "preference": [
        "i prefer", "i like", "i find it easier",
        "works better", "much nicer",
    ],
    "gotcha": [
        "watch out", "be careful", "gotcha",
        "this is tricky", "easy to miss",
    ],
}

# ── Dedup ──────────────────────────────────────────────────────────
DEDUP_DEFAULT_THRESHOLD = 0.55
DEDUP_METHOD = "jaccard"

# ── LLM defaults ───────────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_URL = "https://opencode.ai/zen/go/v1/chat/completions"

# ── Consolidation limits ───────────────────────────────────────────
MAX_EXCHANGES = 20
MAX_CHARS_PER_EXCHANGE = 600
MAX_MEMORY_CONTEXT_CHARS = 5000

# ── Section mapping ────────────────────────────────────────────────
PREFIX_MAP = {
    "DECISION": "Validated Approaches",
    "PREFERENCE": "User Preferences",
    "LEARNING": "Key Learnings",
    "PROJECT-FACT": "Project Conventions",
    "GOTCHA": "Gotchas & Traps",
    "RULE": "Hard Rules",
    "CONVENTION": "Conventions",
    "ARCHITECTURE": "Architecture Decisions",
    "WORKFLOW": "Workflows",
}

# ── Sections that are never auto-edited ────────────────────────────
PROTECTED_SECTIONS = {"Hard Rules"}

# ── Compaction capture paths ───────────────────────────────────────
COMPACTION_EXTENSION_PATH = os.path.join(
    os.path.expanduser("~"), ".pi", "agent", "extensions", "memory-compaction-capture.ts"
)
