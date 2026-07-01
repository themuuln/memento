"""Tests for atomic write operations and file locking."""

import os
import pytest
from memory_cli.core.atomic import atomic_write, atomic_append, read_file_safe
from memory_cli.core.locking import FileLock


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        f = tmp_path / "test.txt"
        atomic_write(str(f), "hello world")
        assert f.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("old content")
        atomic_write(str(f), "new content")
        assert f.read_text() == "new content"

    def test_empty_content(self, tmp_path):
        f = tmp_path / "empty.txt"
        atomic_write(str(f), "")
        assert f.read_text() == ""

    def test_utf8_works(self, tmp_path):
        f = tmp_path / "unicode.txt"
        atomic_write(str(f), "héllo wörld 🎉")
        assert f.read_text() == "héllo wörld 🎉"


class TestAtomicAppend:
    def test_append_to_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        atomic_append(str(f), "first line\n")
        assert "first line" in f.read_text()

    def test_append_to_existing_file(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("line 1\n")
        atomic_append(str(f), "line 2\n")
        text = f.read_text()
        assert "line 1" in text
        assert "line 2" in text

    def test_append_without_trailing_newline(self, tmp_path):
        f = tmp_path / "trailing.txt"
        atomic_append(str(f), "no-newline")
        text = f.read_text()
        assert "no-newline" in text


class TestReadFileSafe:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("content")
        assert read_file_safe(str(f)) == "content"

    def test_returns_empty_string_for_missing(self):
        assert read_file_safe("/nonexistent/path.txt") == ""


class TestFileLock:
    def test_acquire_and_release(self, tmp_path):
        lock_path = str(tmp_path / "test.lock")
        lock = FileLock(lock_path)
        with lock:
            # Lock should be held without error
            pass
        # Should not crash on release

    def test_nested_lock_different_paths(self, tmp_path):
        f1 = str(tmp_path / "lock1.lock")
        f2 = str(tmp_path / "lock2.lock")
        lock1 = FileLock(f1)
        lock2 = FileLock(f2)
        with lock1:
            with lock2:
                pass

    def test_lock_context_manager_works(self, tmp_path):
        lock_path = str(tmp_path / "ctx.lock")
        lock = FileLock(lock_path)
        with lock:
            pass
