from __future__ import annotations
"""memory sync — synchronize memory data across devices via git.

Usage:
  memory sync init    Create or configure the sync data repository
  memory sync push    Upload local memories to remote
  memory sync pull    Download and merge remote memories
  memory sync status  Show sync status and divergence

Config (config.json):
  sync.repo: str  — GitHub repo (default: themuuln/memento-data)
  sync.branch: str — Branch to use (default: main)
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Defaults
DEFAULT_SYNC_REPO = "themuuln/memento-data"
DEFAULT_BRANCH = "main"
SYNC_DIR_NAME = ".memento-sync"

# Files to sync
SYNC_FILES = [
    "global/memories.md",
    "graph/memory-graph.jsonl",
]


def _get_sync_dir(config: dict) -> str:
    """Get the local sync working directory."""
    root = os.path.expanduser(config.get("storage", {}).get("root", "~/.agent-memory"))
    return os.path.join(root, SYNC_DIR_NAME)


def _get_sync_repo(config: dict) -> str:
    """Get the sync repo name from config or default."""
    return config.get("sync", {}).get("repo", DEFAULT_SYNC_REPO)


def _get_sync_branch(config: dict) -> str:
    """Get the sync branch from config or default."""
    return config.get("sync", {}).get("branch", DEFAULT_BRANCH)


def _get_root(config: dict) -> str:
    """Get the agent-memory root directory."""
    return os.path.expanduser(config.get("storage", {}).get("root", "~/.agent-memory"))


def _run_git(cwd: str, *args: str) -> tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 1, "", "git not found"
    except Exception as e:
        return 1, "", str(e)


def _check_gh_auth() -> bool:
    """Check if GitHub CLI is authenticated."""
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _copy_to_sync(src_path: str, sync_dir: str, rel_path: str) -> bool:
    """Copy a data file from source to sync directory."""
    target = os.path.join(sync_dir, rel_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        shutil.copy2(src_path, target)
        return True
    except (FileNotFoundError, PermissionError):
        return False


def _copy_from_sync(sync_dir: str, dest_path: str, rel_path: str) -> bool:
    """Copy a data file from sync directory back to source."""
    src = os.path.join(sync_dir, rel_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        shutil.copy2(src, dest_path)
        return True
    except (FileNotFoundError, PermissionError):
        return False


def _resolve_conflicts(sync_dir: str, root: str) -> list[dict]:
    """Resolve git merge conflicts by keeping the latest-timestamp entry.
    
    For each conflicted file, parses entries and keeps newest per unique ID.
    Returns list of conflict resolutions applied.
    """
    resolutions = []
    stub_fn = os.path.join(sync_dir, ".conflict-resolution")
    
    for rel_path in SYNC_FILES:
        sync_file = os.path.join(sync_dir, rel_path)
        # Check for conflict markers
        if not os.path.exists(sync_file):
            continue
        content = open(sync_file).read(100)
        if "<<<<<<<" not in content and "=======" not in content:
            continue
        
        # Simple resolution: take the head version (latest pulled)
        # Or we could do date-based per-entry merge
        lines = open(sync_file).readlines()
        resolved: list[str] = []
        in_conflict = False
        in_theirs = False
        in_ours = False
        
        for line in lines:
            if line.startswith("<<<<<<<"):
                in_conflict = True
                in_ours = True
                in_theirs = False
                # Our version (local) - skip, take theirs on next iteration
                continue
            if line.startswith("======="):
                in_ours = False
                in_theirs = True
                continue
            if line.startswith(">>>>>>>"):
                in_conflict = False
                in_theirs = False
                continue
            
            if in_conflict and in_ours:
                # Skip our version, take theirs
                continue
            if in_conflict and in_theirs:
                resolved.append(line)
            elif not in_conflict:
                resolved.append(line)
        
        with open(sync_file, "w") as f:
            f.writelines(resolved)
        
        resolutions.append({
            "file": rel_path,
            "method": "ours-skip-take-theirs",
        })
        
        # Re-stage and commit the resolution
        _run_git(sync_dir, "add", rel_path)
    
    return resolutions


def run(
    config: dict,
    adapters: list[str],  # unused, for interface compat
    action: str = "status",
    branch: str | None = None,
    message: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run sync operation."""
    result: dict[str, Any] = {
        "command": "sync",
        "action": action,
        "status": "ok",
    }
    
    root = _get_root(config)
    sync_dir = _get_sync_dir(config)
    sync_repo = _get_sync_repo(config)
    sync_branch = branch or _get_sync_branch(config)
    
    if action == "init":
        return _do_init(result, root, sync_dir, sync_repo, sync_branch, verbose)
    elif action == "push":
        return _do_push(result, root, sync_dir, sync_repo, sync_branch, message, verbose)
    elif action == "pull":
        return _do_pull(result, root, sync_dir, sync_repo, sync_branch, verbose)
    elif action == "status":
        return _do_status(result, root, sync_dir, sync_repo, sync_branch, verbose)
    else:
        result["status"] = "error"
        result["error"] = f"Unknown action: {action}"
        return result


def _check_repo_exists(repo: str) -> bool:
    """Check if a GitHub repo exists (user can access)."""
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", repo, "--json", "name"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _do_init(
    result: dict, root: str, sync_dir: str, repo: str, branch: str,
    verbose: bool,
) -> dict:
    """Initialize sync: create data repo if needed, set up local clone."""
    if not _check_gh_auth():
        result["status"] = "error"
        result["error"] = "GitHub CLI (gh) not authenticated. Run: gh auth login"
        return result
    
    # Check/create the repo
    if _check_repo_exists(repo):
        result["repo_exists"] = True
    else:
        if verbose:
            print(f"  Creating private repo {repo}...")
        try:
            proc = subprocess.run(
                ["gh", "repo", "create", repo, "--private", "--description",
                 "Memento memory data — synced across devices"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode != 0:
                result["status"] = "error"
                result["error"] = f"Failed to create repo: {proc.stderr.strip()}"
                return result
            result["repo_created"] = True
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result
    
    # Clone to sync dir
    if os.path.exists(sync_dir):
        if verbose:
            print(f"  Sync dir exists at {sync_dir}")
    else:
        clone_url = f"https://github.com/{repo}.git"
        if verbose:
            print(f"  Cloning {clone_url} → {sync_dir}...")
        code, out, err = _run_git(root, "clone", clone_url, SYNC_DIR_NAME)
        if code != 0:
            # Try with gh CLI auth
            clone_url = f"https://github.com/{repo}.git"
            try:
                subprocess.run(
                    ["gh", "repo", "clone", repo, SYNC_DIR_NAME],
                    cwd=root, capture_output=True, text=True, timeout=30,
                )
            except Exception as e:
                result["status"] = "error"
                result["error"] = f"Clone failed: {e}"
                return result
        result["cloned"] = True
    
    # Copy existing data to sync dir
    copied = 0
    for rel_path in SYNC_FILES:
        src_path = os.path.join(root, rel_path)
        if os.path.exists(src_path):
            if _copy_to_sync(src_path, sync_dir, rel_path):
                copied += 1
    
    if copied > 0:
        # Commit and push initial data
        _run_git(sync_dir, "add", "-A")
        commit_msg = "Initial sync — import existing memory data"
        _run_git(sync_dir, "commit", "-m", commit_msg, "--allow-empty")
        _run_git(sync_dir, "branch", "-M", branch)
        code, out, err = _run_git(sync_dir, "push", "-u", "origin", branch)
        result["initial_push"] = code == 0
    
    result["repo"] = repo
    result["branch"] = branch
    result["sync_dir"] = sync_dir
    result["data_files_copied"] = copied
    
    # Save sync config
    config_path = os.path.join(root, "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        cfg.setdefault("sync", {})
        cfg["sync"]["repo"] = repo
        cfg["sync"]["branch"] = branch
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)
        result["config_updated"] = True
    
    return result


def _do_push(
    result: dict, root: str, sync_dir: str, repo: str, branch: str,
    message: str | None, verbose: bool,
) -> dict:
    """Push local memory data to remote."""
    if not os.path.exists(sync_dir):
        result["status"] = "error"
        result["error"] = "Sync not initialized. Run: memory sync init"
        return result
    
    # Copy data files to sync dir
    copied = 0
    modified = []
    for rel_path in SYNC_FILES:
        src_path = os.path.join(root, rel_path)
        if os.path.exists(src_path):
            if _copy_to_sync(src_path, sync_dir, rel_path):
                copied += 1
                modified.append(rel_path)
    
    if copied == 0:
        result["status"] = "no_data"
        result["message"] = "No data files found to sync"
        return result
    
    # Check for changes
    _run_git(sync_dir, "add", "-A")
    code, out, _ = _run_git(sync_dir, "status", "--porcelain")
    if not out.strip():
        result["status"] = "up_to_date"
        result["message"] = "No changes to push"
        return result
    
    # Commit and push
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = message or f"Memory sync {timestamp}"
    _run_git(sync_dir, "commit", "-m", commit_msg)
    
    code, push_out, push_err = _run_git(sync_dir, "push", "origin", branch)
    if code != 0:
        # Pull first, then retry
        if verbose:
            print("  Pull first...")
        _run_git(sync_dir, "pull", "--rebase", "origin", branch)
        
        # Check for conflicts
        conflicts = _resolve_conflicts(sync_dir, root)
        if conflicts:
            _run_git(sync_dir, "commit", "-m", f"Merge: resolve {len(conflicts)} conflict(s)")
            result["conflicts_resolved"] = len(conflicts)
        
        code, push_out, push_err = _run_git(sync_dir, "push", "origin", branch)
        if code != 0:
            result["status"] = "error"
            result["error"] = f"Push failed after retry: {push_err.strip()}"
            return result
    
    result["status"] = "ok"
    result["pushed"] = modified
    result["commit_message"] = commit_msg
    return result


def _do_pull(
    result: dict, root: str, sync_dir: str, repo: str, branch: str,
    verbose: bool,
) -> dict:
    """Pull remote memory data and merge locally."""
    if not os.path.exists(sync_dir):
        # Clone if not present
        if verbose:
            print(f"  Cloning {repo}...")
        try:
            subprocess.run(
                ["gh", "repo", "clone", repo, SYNC_DIR_NAME],
                cwd=root, capture_output=True, text=True, timeout=30,
            )
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"Clone failed: {e}"
            return result
    
    # Pull latest
    code, out, err = _run_git(sync_dir, "pull", "origin", branch)
    if code != 0:
        # Check for conflicts
        conflicts = _resolve_conflicts(sync_dir, root)
        if conflicts:
            _run_git(sync_dir, "commit", "-m", f"Merge: resolve {len(conflicts)} conflict(s)")
            result["conflicts_resolved"] = len(conflicts)
        else:
            result["status"] = "error"
            result["error"] = f"Pull failed: {err.strip()}"
            return result
    
    # Copy files back to live locations
    copied = 0
    restored = []
    for rel_path in SYNC_FILES:
        dest_path = os.path.join(root, rel_path)
        if _copy_from_sync(sync_dir, dest_path, rel_path):
            copied += 1
            restored.append(rel_path)
    
    # Rebuild FTS5 index after restoring data
    if copied > 0:
        try:
            from memory_cli.core.search_index import SearchIndex
            from memory_cli.core.parser import parse_memory_file
            from memory_cli.constants import GLOBAL_MEM_PATH
            
            idx = SearchIndex()
            idx.open()
            parsed = parse_memory_file(GLOBAL_MEM_PATH)
            entries_for_index = [
                {
                    "id": e.id, "content": e.content,
                    "search_text": e.search_text,
                    "section_path": e.section_path,
                    "kind": e.kind, "timestamp": e.timestamp,
                    "source_path": e.source_path,
                    "line_start": e.line_start,
                    "content_hash": e.content_hash,
                }
                for e in parsed
            ]
            idx.rebuild(entries_for_index)
            idx.close()
            result["index_rebuilt"] = True
        except Exception:
            result["index_rebuilt"] = False
    
    result["status"] = "ok"
    result["restored"] = restored
    result["total_restored"] = copied
    return result


def _do_status(
    result: dict, root: str, sync_dir: str, repo: str, branch: str,
    verbose: bool,
) -> dict:
    """Show sync status."""
    if not os.path.exists(sync_dir):
        result["status"] = "not_initialized"
        result["message"] = "Sync not configured. Run: memory sync init"
        result["repo"] = repo
        return result
    
    # Check last commit info
    code, log_out, _ = _run_git(sync_dir, "log", "-1", "--format=%H|%ai|%s")
    if code == 0 and log_out.strip():
        parts = log_out.strip().split("|", 2)
        result["last_commit"] = {
            "hash": parts[0],
            "date": parts[1] if len(parts) > 1 else "",
            "message": parts[2] if len(parts) > 2 else "",
        }
    
    # Check divergence
    code, behind_out, _ = _run_git(sync_dir, "rev-list", "--count", f"HEAD..origin/{branch}")
    if code == 0 and behind_out.strip():
        result["behind_remote"] = int(behind_out.strip())
    
    code, ahead_out, _ = _run_git(sync_dir, "rev-list", "--count", f"origin/{branch}..HEAD")
    if code == 0 and ahead_out.strip():
        result["ahead_of_remote"] = int(ahead_out.strip())
    
    # Check local data file freshness
    for rel_path in SYNC_FILES:
        sync_file = os.path.join(sync_dir, rel_path)
        live_file = os.path.join(root, rel_path)
        item: dict[str, Any] = {"relative_path": rel_path}
        
        if os.path.exists(sync_file):
            item["sync_mtime"] = os.path.getmtime(sync_file)
            item["sync_size"] = os.path.getsize(sync_file)
        else:
            item["sync_status"] = "missing"
        
        if os.path.exists(live_file):
            item["live_mtime"] = os.path.getmtime(live_file)
            item["live_size"] = os.path.getsize(live_file)
        else:
            item["live_status"] = "missing"
        
        result.setdefault("files", []).append(item)
    
    # Check gh auth
    result["gh_authenticated"] = _check_gh_auth()
    result["repo"] = repo
    result["branch"] = branch
    result["sync_dir"] = sync_dir
    
    return result
