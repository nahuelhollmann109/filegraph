"""MCP tool definitions for directory scanning."""

from __future__ import annotations

from pathlib import Path

from src.cache import check_freshness, get_or_scan
from src.scanner import (
    DEFAULT_EXCLUDED_DIRS,
    _resolve_exclusions,
    file_info,
    find_duplicates as _find_duplicates,
    find_patterns as _find_patterns,
    scan_tree,
    search_files,
)
from src.store import cache_stats, invalidate_path, list_entries_by_path


def scan_directory(
    path: str,
    max_depth: int | None = None,
    exclude_dirs: list[str] | None = None,
    include_excluded: bool = False,
) -> dict:
    """Scan a directory and return its hierarchy as a JSON tree.

    Args:
        path: Absolute or relative path to the directory to scan. REQUIRED.
        max_depth: Maximum depth to traverse (None = unlimited).
        exclude_dirs: Custom list of directory names to exclude.
        include_excluded: If True, bypass all exclusions.

    Returns:
        Dict with 'tree' (nested dict) and 'warnings' (list of strings).
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"error": f"Path not found: {path}", "tree": None, "warnings": []}

    if not target.is_dir():
        return {"error": f"Expected a directory: {path}", "tree": None, "warnings": []}

    effective_exclude = _resolve_exclusions(exclude_dirs, include_excluded)

    def _live_scan() -> dict:
        result = scan_tree(target, max_depth=max_depth, exclude_dirs=effective_exclude)
        result["_root_path"] = str(target)
        return result

    result = get_or_scan(target, "scan_directory", str(target), _live_scan)
    result.pop("_root_path", None)
    return result


def search_by_type(
    path: str,
    file_type: str,
    exclude_dirs: list[str] | None = None,
    include_excluded: bool = False,
) -> dict:
    """Search for files by extension under the given path.

    Args:
        path: Root directory to search. REQUIRED.
        file_type: File extension to filter by (e.g. 'jpg', 'png').
        exclude_dirs: Custom list of directory names to exclude.
        include_excluded: If True, bypass all exclusions.

    Returns:
        Dict with 'results' (list of file dicts).
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"error": f"Path not found: {path}", "results": []}

    if not target.is_dir():
        return {"error": f"Expected a directory: {path}", "results": []}

    effective_exclude = _resolve_exclusions(exclude_dirs, include_excluded)

    def _live_scan() -> dict:
        results = search_files(target, file_type, exclude_dirs=effective_exclude)
        return {"results": results}

    return get_or_scan(target, "search_by_type", str(target), _live_scan, file_type=file_type)


def get_file_metadata(path: str) -> dict:
    """Get metadata for a specific file.

    Args:
        path: Path to the file. REQUIRED.

    Returns:
        Dict with file metadata or error.
    """
    target = Path(path).resolve()

    try:
        info = file_info(target)
        return info
    except FileNotFoundError:
        return {"error": f"Path not found: {path}"}
    except IsADirectoryError:
        return {"error": f"Expected a file, got a directory: {path}"}


def find_duplicates(
    path: str,
    hash_algo: str = "sha256",
    min_size: int = 0,
) -> dict:
    """Find duplicate files by content hash under the given path.

    Args:
        path: Root directory to search. REQUIRED.
        hash_algo: Hash algorithm name (default: sha256).
        min_size: Minimum file size in bytes to consider.

    Returns:
        Dict with 'duplicates' (list of duplicate group dicts).
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"error": f"Path not found: {path}", "duplicates": []}

    if not target.is_dir():
        return {"error": f"Expected a directory: {path}", "duplicates": []}

    def _live_scan() -> dict:
        effective_exclude = _resolve_exclusions(None, False)
        results = _find_duplicates(target, exclude_dirs=effective_exclude, hash_algo=hash_algo, min_size=min_size)
        return {"duplicates": results}

    return get_or_scan(target, "find_duplicates", str(target), _live_scan)


def find_patterns(
    path: str,
    strategy: str = "auto",
    min_group_size: int = 3,
) -> dict:
    """Detect naming patterns across files under the given path.

    Args:
        path: Root directory to search. REQUIRED.
        strategy: Detection strategy (auto, sequence, prefix, suffix, date).
        min_group_size: Minimum files to form a pattern group.

    Returns:
        Dict with 'patterns' (list of pattern group dicts).
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"error": f"Path not found: {path}", "patterns": []}

    if not target.is_dir():
        return {"error": f"Expected a directory: {path}", "patterns": []}

    def _live_scan() -> dict:
        effective_exclude = _resolve_exclusions(None, False)
        results = _find_patterns(target, exclude_dirs=effective_exclude, strategy=strategy, min_group_size=min_group_size)
        return {"patterns": results}

    return get_or_scan(target, "find_patterns", str(target), _live_scan)


# Cache management tools


def index_directory(path: str) -> dict:
    """Index a directory — scan and store results in cache.

    Args:
        path: Directory to index. REQUIRED.

    Returns:
        Dict with status and optional error message.
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"status": "error", "error": f"Path not found: {path}"}

    if not target.is_dir():
        return {"status": "error", "error": f"Expected a directory: {path}"}

    def _live_scan() -> dict:
        effective_exclude = _resolve_exclusions(None, False)
        result = scan_tree(target, exclude_dirs=effective_exclude)
        result["_root_path"] = str(target)
        return result

    result = get_or_scan(target, "scan_directory", str(target), _live_scan)
    tree = result.get("tree")

    if tree is None:
        return {"status": "error", "error": result.get("error", "Scan failed")}

    return {"status": "indexed", "path": str(target)}


def sync_cache(path: str) -> dict:
    """Sync cache — re-scan stale entries for the given path.

    Args:
        path: Directory to sync. REQUIRED.

    Returns:
        Dict with refreshed/fresh counts and optional error message.
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"status": "error", "error": f"Path not found: {path}"}

    if not target.is_dir():
        return {"status": "error", "error": f"Expected a directory: {path}"}

    entries = list_entries_by_path(target, str(target))
    if not entries:
        return {"status": "error", "error": f"No cached entries for {path}. Run index first."}

    refreshed = 0
    fresh = 0
    for entry in entries:
        if check_freshness(target, entry["cache_key"]):
            fresh += 1
        else:
            refreshed += 1

    return {"status": "synced", "refreshed": refreshed, "fresh": fresh}


def cache_status(path: str | None = None) -> dict:
    """Show cache statistics.

    Args:
        path: Optional directory path. If not provided, searches from cwd upward.

    Returns:
        Dict with entries, total_files, and size_bytes.
    """
    if path:
        target = Path(path).resolve()
    else:
        # Walk up from cwd to find nearest .filegraph/cache.db
        current = Path.cwd()
        target = None
        while True:
            db_path = current / ".filegraph" / "cache.db"
            if db_path.exists():
                target = current
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        if target is None:
            return {"entries": 0, "total_files": 0, "size_bytes": 0}

    stats = cache_stats(target)
    return stats


def unindex_directory(path: str) -> dict:
    """Remove cache entries for the given path.

    Args:
        path: Directory to unindex. REQUIRED.

    Returns:
        Dict with removed count and optional error message.
    """
    target = Path(path).resolve()
    removed = invalidate_path(target, str(target))
    return {"status": "unindexed", "removed": removed}
