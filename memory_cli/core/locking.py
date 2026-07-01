from __future__ import annotations
"""File locking using fcntl.flock (Unix/macOS only)."""

import fcntl
import os
import time


class FileLock:
    """Exclusive file lock via fcntl.flock with timeout.
    
    Usage:
        with FileLock("/path/to/file.md", timeout=5.0):
            # safe to read/write the file
    """
    
    def __init__(self, filepath: str, timeout: float = 5.0):
        self._filepath = filepath
        self._lockpath = filepath + ".lock"
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        os.makedirs(os.path.dirname(self._lockpath), exist_ok=True)
        self._fd = os.open(self._lockpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (BlockingIOError, OSError):
                if time.monotonic() > deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise TimeoutError(
                        f"Could not acquire lock on {self._filepath} "
                        f"within {self._timeout}s"
                    )
                time.sleep(0.1)

    def __exit__(self, *exc_args) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
        # Don't delete .lock — avoids race conditions


class NullLock:
    """No-op lock for environments without fcntl support."""
    
    def __enter__(self) -> "NullLock":
        return self
    
    def __exit__(self, *exc_args) -> None:
        pass
