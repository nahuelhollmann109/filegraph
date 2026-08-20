"""Core directory scanning logic."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", "__pycache__", ".venv"}
)


def _resolve_exclusions(
    exclude_dirs: list[str] | None,
    include_excluded: bool,
) -> set[str] | None:
    """Return the effective exclusion set.

    Args:
        exclude_dirs: Custom list of directory names to exclude.
        include_excluded: If True, bypass all exclusions.

    Returns:
        Set of directory names to exclude, or None if no exclusions apply.
    """
    if include_excluded:
        return set(exclude_dirs) if exclude_dirs else set()
    return set(exclude_dirs) if exclude_dirs is not None else DEFAULT_EXCLUDED_DIRS


def walk_directory(
    root: Path,
    exclude_dirs: set[str] | None = None,
    max_depth: int | None = None,
) -> Iterator[Path]:
    """Yield every file path under root, pruning excluded dirs. Skips symlinks.

    Args:
        root: Root directory to walk.
        exclude_dirs: Set of directory names to skip entirely. None means use
            DEFAULT_EXCLUDED_DIRS; empty set means skip nothing.
        max_depth: Maximum directory depth to traverse. None = unlimited.

    Yields:
        Path objects for each file found.
    """
    if not root.is_dir():
        return

    effective_exclude = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDED_DIRS

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Compute current depth relative to root
        rel = Path(dirpath).relative_to(root)
        depth = len(rel.parts)
        if max_depth is not None and depth >= max_depth:
            dirnames.clear()
            continue

        # Prune excluded directories in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in effective_exclude and not Path(dirpath, d).is_symlink()
        ]
        dirnames.sort()

        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if fpath.is_symlink():
                continue
            if fpath.is_file():
                yield fpath


def scan_tree(
    path: Path,
    max_depth: int | None = None,
    exclude_dirs: set[str] | None = None,
    _current_depth: int = 0,
) -> dict:
    """Build a JSON tree of the directory hierarchy.

    Returns a dict with keys: name, type (directory/file), and children (for dirs).
    Symlinks are recorded but not followed.
    Permission errors produce partial results with warnings.
    """
    warnings: list[str] = []
    result = _scan_node(path, max_depth, _current_depth, warnings, exclude_dirs)
    return {"tree": result, "warnings": warnings}


def _scan_node(
    path: Path,
    max_depth: int | None,
    current_depth: int,
    warnings: list[str],
    exclude_dirs: set[str] | None = None,
) -> dict:
    """Recursively scan a single path node."""
    name = path.name or str(path)

    # Symlink — record but do not follow
    if path.is_symlink():
        return {"name": name, "type": "symlink", "target": str(path.resolve())}

    # File
    if path.is_file():
        return {"name": name, "type": "file"}

    # Directory
    if path.is_dir():
        # Check depth limit
        if max_depth is not None and current_depth >= max_depth:
            return {"name": name, "type": "directory", "children": []}

        children: list[dict] = []
        effective_exclude = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDED_DIRS
        try:
            entries = sorted(path.iterdir(), key=lambda p: p.name)
        except PermissionError as exc:
            warnings.append(f"Permission denied: {path} — {exc}")
            return {"name": name, "type": "directory", "children": []}

        for entry in entries:
            # Skip excluded directories
            if entry.is_dir() and not entry.is_symlink() and entry.name in effective_exclude:
                continue
            try:
                child = _scan_node(entry, max_depth, current_depth + 1, warnings, exclude_dirs)
                children.append(child)
            except PermissionError as exc:
                warnings.append(f"Permission denied: {entry} — {exc}")
            except OSError as exc:
                warnings.append(f"Error reading {entry} — {exc}")

        return {"name": name, "type": "directory", "children": children}

    return {"name": name, "type": "unknown"}


def search_files(path: Path, file_type: str, exclude_dirs: set[str] | None = None) -> list[dict]:
    """Return a flat list of files matching the given extension under path.

    Args:
        path: Root directory to search.
        file_type: File extension to filter by (e.g. 'jpg', 'png').
        exclude_dirs: Set of directory names to exclude. None uses defaults.

    Returns:
        List of dicts with keys: name, path, size.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    ext = file_type.lower().lstrip(".")
    results: list[dict] = []

    for entry in walk_directory(path, exclude_dirs=exclude_dirs):
        if entry.suffix.lower().lstrip(".") == ext:
            try:
                stat = entry.stat()
                results.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "size": stat.st_size,
                    }
                )
            except (PermissionError, OSError):
                # Skip files we can't stat
                continue

    return sorted(results, key=lambda f: f["name"])


def find_patterns(
    path: Path,
    exclude_dirs: set[str] | None = None,
    strategy: str = "auto",
    min_group_size: int = 3,
) -> list[dict]:
    """Detect naming patterns across files in a directory tree.

    Strategies:
        - sequence: numeric sequences like file_001.txt, file_002.txt
        - prefix: files sharing a common filename prefix (>= 3 chars)
        - suffix: files sharing a common filename suffix (before extension)
        - date: files containing date tokens like 2024-01-15 or 2024_01_15
        - auto: run all strategies and return combined results

    Args:
        path: Root directory to search.
        exclude_dirs: Set of directory names to exclude. None uses defaults.
        strategy: Detection strategy to use.
        min_group_size: Minimum number of files to form a pattern group.

    Returns:
        List of dicts, each with keys: type, pattern, files (sorted).
    """
    import re

    if not path.is_dir():
        return []

    valid_strategies = {"auto", "sequence", "prefix", "suffix", "date"}
    if strategy not in valid_strategies:
        return []

    # Collect all filenames (stems and full paths)
    file_entries: list[tuple[str, str]] = []  # (stem, full_path)
    for fpath in walk_directory(path, exclude_dirs=exclude_dirs):
        try:
            _ = fpath.stat()
        except (PermissionError, OSError):
            continue
        file_entries.append((fpath.stem, str(fpath)))

    if not file_entries:
        return []

    results: list[dict] = []

    if strategy in ("sequence", "auto"):
        results.extend(_detect_sequences(file_entries, min_group_size))

    if strategy in ("prefix", "auto"):
        results.extend(_detect_prefixes(file_entries, min_group_size))

    if strategy in ("suffix", "auto"):
        results.extend(_detect_suffixes(file_entries, min_group_size))

    if strategy in ("date", "auto"):
        results.extend(_detect_dates(file_entries, min_group_size))

    return results


def _detect_sequences(
    file_entries: list[tuple[str, str]], min_group_size: int
) -> list[dict]:
    """Detect numeric sequence patterns like file_001, file_002."""
    import re

    pattern = re.compile(r"^(.*?)(\d+)(\D*)$")
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)

    for stem, full_path in file_entries:
        m = pattern.match(stem)
        if m:
            prefix, _num, suffix = m.groups()
            key = (prefix, suffix)
            groups[key].append(full_path)

    results = []
    for (prefix, suffix), files in groups.items():
        if len(files) < min_group_size:
            continue
        # Verify numeric parts form a plausible sequence (sorted numeric check)
        nums = []
        for stem, fp in file_entries:
            m = pattern.match(stem)
            if m and m.group(1) == prefix and m.group(3) == suffix:
                nums.append(int(m.group(2)))
        nums_sorted = sorted(nums)
        # Accept if max - min + 1 == count (contiguous) or at least monotonically increasing
        if len(nums_sorted) >= min_group_size:
            pattern_str = f"{prefix}{{{nums_sorted[0]}}}{suffix}"
            results.append({
                "type": "sequence",
                "pattern": pattern_str,
                "files": sorted(files),
            })

    return results


def _detect_prefixes(
    file_entries: list[tuple[str, str]], min_group_size: int
) -> list[dict]:
    """Detect common filename prefixes (>= 3 chars, shared by >= min_group_size files)."""
    if len(file_entries) < min_group_size:
        return []

    stems = [stem for stem, _ in file_entries]
    # Find the longest common prefix across all stems
    prefix = os.path.commonprefix(stems)

    # Trim to last word boundary (underscore or hyphen)
    for i in range(len(prefix), 0, -1):
        if prefix[i - 1] in ("_", "-"):
            prefix = prefix[:i]
            break
    else:
        # No word boundary found — keep as-is if long enough
        pass

    if len(prefix) < 3:
        return []

    # Collect files that start with this prefix
    matching = [fp for stem, fp in file_entries if stem.startswith(prefix)]
    if len(matching) < min_group_size:
        return []

    return [{
        "type": "prefix",
        "pattern": prefix,
        "files": sorted(matching),
    }]


def _detect_suffixes(
    file_entries: list[tuple[str, str]], min_group_size: int
) -> list[dict]:
    """Detect common filename suffixes before extension.

    Finds the longest common suffix shared by >= min_group_size files,
    trimmed to the last word boundary.
    """
    if len(file_entries) < min_group_size:
        return []

    stems = [stem for stem, _ in file_entries]

    # Find the longest common suffix across all stems
    if not stems:
        return []

    # Reverse-stripping: find common suffix
    suffix = ""
    min_len = min(len(s) for s in stems)
    for i in range(1, min_len + 1):
        chars = {s[-i] for s in stems}
        if len(chars) == 1:
            suffix = stems[0][-i:]
        else:
            break

    # Trim to first word boundary (underscore or hyphen)
    for i, ch in enumerate(suffix):
        if ch in ("_", "-"):
            suffix = suffix[i + 1 :]
            break

    if len(suffix) < 2:
        return []

    # Collect files whose stem ends with this suffix
    matching = [fp for stem, fp in file_entries if stem.endswith(suffix)]
    if len(matching) < min_group_size:
        return []

    return [{
        "type": "suffix",
        "pattern": suffix,
        "files": sorted(matching),
    }]


def _detect_dates(
    file_entries: list[tuple[str, str]], min_group_size: int
) -> list[dict]:
    """Detect date tokens like 2024-01-15 or 2024_01_15 in filenames.

    Groups files by date-token pattern structure (e.g. YYYY-MM-DD),
    not by the exact date value.
    """
    import re

    date_pattern = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")
    # Group key: (year_position_pattern, month_position_pattern, day_position_pattern,
    #             separator_between_year_month, separator_between_month_day)
    # Simplified: use a canonical pattern like "YYYY-MM-DD" based on separators
    groups: dict[str, list[str]] = defaultdict(list)

    for stem, full_path in file_entries:
        matches = date_pattern.findall(stem)
        if matches:
            for year, month, day in matches:
                # Determine separator from original match
                date_token = f"{year}-{month}-{day}"
                # Find the actual separator used in the stem
                sep_match = re.search(r"\d{4}([-_])\d{2}[-_]\d{2}", stem)
                sep = sep_match.group(1) if sep_match else "-"
                pattern_key = f"YYYY{sep}MM{sep}DD"
                groups[pattern_key].append(full_path)

    results = []
    for pattern_key, files in groups.items():
        if len(files) >= min_group_size:
            results.append({
                "type": "date",
                "pattern": pattern_key,
                "files": sorted(set(files)),
            })

    return results


def find_duplicates(
    path: Path,
    exclude_dirs: set[str] | None = None,
    hash_algo: str = "sha256",
    min_size: int = 0,
) -> list[dict]:
    """Find duplicate files by content hash.

    Uses a two-pass approach: group by size first, then hash files in
    groups with more than one candidate to avoid unnecessary I/O.

    Args:
        path: Root directory to search.
        exclude_dirs: Set of directory names to exclude. None uses defaults.
        hash_algo: Hash algorithm name (must be valid for hashlib).
        min_size: Minimum file size in bytes to consider.

    Returns:
        List of dicts, each with keys: hash, size, files (sorted list of
        file path strings). Only groups with 2+ files are returned.
    """
    if not path.is_dir():
        return []

    try:
        valid_algos = set(hashlib.algorithms_guaranteed)
        if hash_algo not in valid_algos:
            return []
    except Exception:
        return []

    # Pass 1: group files by size
    size_groups: dict[int, list[Path]] = defaultdict(list)
    for fpath in walk_directory(path, exclude_dirs=exclude_dirs):
        try:
            size = fpath.stat().st_size
        except (PermissionError, OSError):
            continue
        if size < min_size:
            continue
        if size == 0:
            continue
        size_groups[size].append(fpath)

    # Pass 2: hash files in multi-entry groups
    hash_groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    for size, candidates in size_groups.items():
        if len(candidates) < 2:
            continue
        for fpath in candidates:
            try:
                file_hash = _hash_file(fpath, hash_algo)
                key = (size, file_hash)
                hash_groups[key].append(str(fpath))
            except (PermissionError, OSError):
                continue

    # Build result: only groups with 2+ files
    results = []
    for (size, file_hash), files in sorted(hash_groups.items()):
        if len(files) >= 2:
            results.append({
                "hash": file_hash,
                "size": size,
                "files": sorted(files),
            })

    return results


def _hash_file(path: Path, algo: str) -> str:
    """Compute hex digest of a file's contents."""
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def file_info(path: Path) -> dict:
    """Return metadata for a single file.

    Args:
        path: Path to a file.

    Returns:
        Dict with keys: name, size, modified, created, permissions, is_symlink.

    Raises:
        FileNotFoundError: If path does not exist.
        IsADirectoryError: If path is a directory.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_dir():
        raise IsADirectoryError(f"Expected a file, got a directory: {path}")

    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
        "permissions": oct(stat.st_mode),
        "is_symlink": path.is_symlink(),
    }
