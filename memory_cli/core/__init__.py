from __future__ import annotations
"""Structured JSON-line logger for observability."""

import json
import os
import sys
from datetime import datetime, timezone

from memory_cli.constants import CLI_LOG


def log_entry(
    entry: dict,
    logfile: str | None = None,
    stderr: bool = False,
) -> None:
    """Write a structured JSON-log line.
    
    Each line is a self-describing JSON object with a timestamp.
    Fields:
      - t: ISO-8601 timestamp
      - command, status, source, session_id, ... (passthrough)
    """
    record = {"t": datetime.now(timezone.utc).isoformat()}
    record.update(entry)
    line = json.dumps(record, default=str) + "\n"
    
    if logfile:
        try:
            os.makedirs(os.path.dirname(logfile) or ".", exist_ok=True)
            with open(logfile, "a") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass  # best-effort logging
    
    if stderr:
        print(line, file=sys.stderr, end="")


class Logger:
    """Reusable logger instance for a command session."""
    
    def __init__(self, logfile: str | None = None, verbose: bool = False):
        self._logfile = logfile or CLI_LOG
        self._verbose = verbose
    
    def info(self, **fields) -> None:
        log_entry(fields, logfile=self._logfile, stderr=self._verbose)
    
    def error(self, **fields) -> None:
        fields["level"] = "error"
        log_entry(fields, logfile=self._logfile, stderr=True)
    
    def warn(self, **fields) -> None:
        fields["level"] = "warn"
        log_entry(fields, logfile=self._logfile, stderr=self._verbose)
    
    def ok(self, **fields) -> None:
        fields["level"] = "ok"
        log_entry(fields, logfile=self._logfile, stderr=False)
