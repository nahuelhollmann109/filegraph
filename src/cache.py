"""Cache logic: key generation, freshness validation, and get-or-scan wrapper."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from src.store import get_cache as _store_get, get_file_set, set_cache as _store_set


def make_cache_key(tool_name: str, path: str, **kwargs) -> str:
    """Generate a deterministic SHA256 cache key.

    Args:
        tool_name: Name of the tool (e.g. "scan_directory").
        path: Scanned directory path.
        **kwargs: Additional options that affect the result.

    Returns:
        Hex-encoded SHA256 hash string.
    """
    # Sort kwargs for determinism
    opts_json = json.dumps(kwargs, sort_keys=True, default=str)
    raw = f"{tool_name}\x00{path}\x00{opts_json}"
    return hashlib.sha256(raw.encode()).hexdigest()


def extract_file_set(result: dict, tool_name: str) -> list[tuple[str, float]]:
    """Extract (file_path, mtime) tuples from a tool result dict.

    Handles different result shapes:
    - scan_directory: nested tree structure
    - search_by_type: flat list under 'results'
    - find_duplicates: flat list under 'duplicates' with 'files' sublists
    - find_patterns: list under 'patterns' with 'files' sublists

    Args:
        result: The tool result dict.
        tool_name: Name of the tool that produced the result.

    Returns:
        List of (file_path, mtime) tuples.
    """
    file_set: list[tuple[str, float]] = []
    seen: set[str] = set()

    def _add_file(fpath: str) -> None:
        if fpath in seen:
            return
        seen.add(fpath)
        try:
            mtime = os.stat(fpath).st_mtime
            file_set.append((fpath, mtime))
        except (PermissionError, OSError):
            pass

    if tool_name == "scan_directory":
        # Walk the nested tree structure; root node name is the directory basename
        tree = result.get("tree", {})
        root_path = result.get("_root_path", tree.get("name", ""))
        _walk_tree(tree, _add_file, base_path=root_path)

    elif tool_name == "search_by_type":
        for item in result.get("results", []):
            if "path" in item:
                _add_file(item["path"])

    elif tool_name == "find_duplicates":
        for group in result.get("duplicates", []):
            for fpath in group.get("files", []):
                _add_file(fpath)

    elif tool_name == "find_patterns":
        for group in result.get("patterns", []):
            for fpath in group.get("files", []):
                _add_file(fpath)

    return file_set


def _walk_tree(node: dict, add_file: Callable[[str], None], base_path: str = "") -> None:
    """Recursively walk a scan_tree result node, collecting file paths.

    Args:
        node: Current tree node (dict with 'name', 'type', optional 'children').
        add_file: Callback to register a file path.
        base_path: Accumulated directory path so far.
    """
    node_type = node.get("type")
    if node_type != "directory":
        return

    # For root node, base_path already represents the scanned directory.
    # For child directories, append this node's name.
    name = node.get("name", "")
    if base_path and name and not base_path.endswith(name):
        dir_path = f"{base_path}/{name}"
    elif not base_path:
        dir_path = name
    else:
        dir_path = base_path

    # Exclude .filegraph directory (matches check_freshness walk exclusions)
    _EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".filegraph"}

    for child in node.get("children", []):
        child_name = child.get("name", "")
        child_type = child.get("type")
        if child_type == "file":
            add_file(f"{dir_path}/{child_name}")
        elif child_type == "directory" and child_name not in _EXCLUDED_DIRS:
            _walk_tree(child, add_file, base_path=dir_path)


def check_freshness(project_root: Path, cache_key: str) -> bool:
    """Check whether a cached result is still fresh.

    Freshness rules:
    1. If any recorded file has mtime > max_mtime → stale (modified)
    2. If any recorded file is missing → stale (deleted)
    3. If current file set differs from recorded set → stale (new files)

    Args:
        project_root: Project root path.
        cache_key: Cache key to validate.

    Returns:
        True if fresh, False if stale.
    """
    entry = _store_get(project_root, cache_key)
    if entry is None:
        return False

    max_mtime = entry["max_mtime"]

    # Load recorded file set
    recorded_files = get_file_set(project_root, cache_key)
    if not recorded_files:
        # No files recorded — empty result, always fresh
        return True

    # Check for deleted files and mtime changes
    recorded_set: set[str] = set()
    for rf in recorded_files:
        fpath = rf["file_path"]
        recorded_set.add(fpath)

        try:
            current_mtime = os.stat(fpath).st_mtime
            # If any file is newer than the recorded max_mtime, it was modified
            if current_mtime > max_mtime:
                return False
        except (PermissionError, OSError):
            # Skip unstatable files per spec
            continue

    # Check for new files by walking the directory
    scan_path = Path(entry["path"])
    if scan_path.is_dir():
        current_set: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(scan_path, topdown=True):
            # Skip excluded dirs (matching scanner defaults) and .filegraph cache dir
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", "node_modules", "__pycache__", ".venv", ".filegraph"}
                and not Path(dirpath, d).is_symlink()
            ]
            dirnames.sort()
            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                if not fpath.is_symlink() and fpath.is_file():
                    current_set.add(str(fpath))

        if recorded_set != current_set:
            return False

    return True


def get_or_scan(
    project_root: Path,
    tool_name: str,
    path: str,
    scan_fn: Callable[[], dict],
    **kwargs,
) -> dict:
    """Return cached result if fresh, otherwise scan and cache.

    Args:
        project_root: Project root path.
        tool_name: Name of the tool.
        path: Scanned directory path.
        scan_fn: Callable that performs the live scan and returns a result dict.
        **kwargs: Additional options for cache key generation.

    Returns:
        The scan result dict (from cache or fresh scan).
    """
    cache_key = make_cache_key(tool_name, path, **kwargs)

    # Check cache
    entry = _store_get(project_root, cache_key)
    if entry is not None:
        # Cache hit — validate freshness
        if check_freshness(project_root, cache_key):
            return json.loads(entry["result_json"])

    # Cache miss or stale — scan live
    result = scan_fn()

    # Extract file set and store
    file_set = extract_file_set(result, tool_name)
    result_json = json.dumps(result, default=str)
    _store_set(project_root, cache_key, tool_name, path, result_json, file_set)

    return result
