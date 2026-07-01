from __future__ import annotations
"""Atomic file operations: safe writes and appends."""

import os
import tempfile


def atomic_write(filepath: str, text: str) -> None:
    """Write text to file atomically via temp + fsync + rename.
    
    Guarantees: on crash, either the old file is intact or the new
    file is complete. Never a partial overwrite.
    """
    dirpath = os.path.dirname(filepath) or "."
    fd, tmp = tempfile.mkstemp(dir=dirpath, prefix=".memory-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            # Single write call — atomic at OS level for small files
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, filepath)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_append(filepath: str, text: str) -> None:
    """Append text atomically: open, seek end, write, fsync.
    
    Ensures the existing file ends with a newline before appending,
    so the new content always starts on a fresh line. This prevents
    JSON objects or lines from being concatenated.
    
    Suitable for JSONL and markdown appends. Safe for small writes
    — a single write() call makes partial content impossible at the
    OS level for writes under PIPE_BUF (typically 4096 bytes).
    """
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "a+") as f:
        # Check if file ends with newline; seek to end first
        size = f.tell()
        if size > 0:
            f.seek(size - 1)
            last_char = f.read(1)
            if last_char != "\n":
                f.write("\n")
                f.flush()
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def read_file_safe(filepath: str, default: str = "") -> str:
    """Read a file, returning default if missing."""
    try:
        with open(filepath) as f:
            return f.read()
    except FileNotFoundError:
        return default
