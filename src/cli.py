"""CLI entry point for directory scanning tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.cache import check_freshness, get_or_scan, make_cache_key
from src.scanner import scan_tree, _resolve_exclusions
from src.store import cache_stats, invalidate_path, list_entries_by_path
from src.tools import (
    find_duplicates as _find_duplicates,
    find_patterns as _find_patterns,
    scan_directory,
    search_by_type,
)


def _format_tree(node: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    """Convert a tree dict to indented lines with box-drawing characters."""
    lines: list[str] = []
    connector = "└── " if is_last else "├── "
    lines.append(f"{prefix}{connector}{node['name']}")

    if node.get("type") == "directory" and "children" in node:
        children = node["children"]
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            lines.extend(_format_tree(child, child_prefix, i == len(children) - 1))

    return lines


def _print_json(data: dict) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_tree(data: dict) -> None:
    """Print tree data with box-drawing characters."""
    if "tree" in data:
        lines = _format_tree(data["tree"])
        print("\n".join(lines))
        if data.get("warnings"):
            print("\nWarnings:")
            for w in data["warnings"]:
                print(f"  ⚠ {w}")
    else:
        _print_json(data)


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute the scan subcommand."""
    result = scan_directory(
        path=args.path,
        max_depth=args.depth,
        include_excluded=args.no_exclude,
    )
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1
    if args.format == "json":
        _print_json(result)
    else:
        _print_tree(result)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Execute the search subcommand."""
    result = search_by_type(
        path=args.path,
        file_type=args.type,
        include_excluded=args.no_exclude,
    )
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1
    if args.format == "json":
        _print_json(result)
    else:
        results = result.get("results", [])
        if not results:
            print("No files found.")
        else:
            for r in results:
                print(f"{r['name']}  ({r['size']} bytes)")
    return 0


def cmd_find_duplicates(args: argparse.Namespace) -> int:
    """Execute the find-duplicates subcommand."""
    result = _find_duplicates(
        path=args.path,
        hash_algo=args.algo,
        min_size=args.min_size,
    )
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1
    groups = result.get("duplicates", [])
    if args.format == "json":
        _print_json(result)
    else:
        if not groups:
            print("No duplicates found.")
        else:
            for group in groups:
                print(f"\nHash: {group['hash'][:12]}... ({group['size']} bytes)")
                for f in group["files"]:
                    print(f"  {f}")
    return 0


def cmd_find_patterns(args: argparse.Namespace) -> int:
    """Execute the find-patterns subcommand."""
    result = _find_patterns(
        path=args.path,
        strategy=args.strategy,
        min_group_size=args.min_group,
    )
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1
    groups = result.get("patterns", [])
    if args.format == "json":
        _print_json(result)
    else:
        if not groups:
            print("No patterns found.")
        else:
            for group in groups:
                print(f"\n{group['type'].upper()}: {group['pattern']}")
                for f in group["files"]:
                    print(f"  {f}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Index a directory — scan and store results in cache."""
    target = Path(args.path).resolve()
    if not target.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        return 1
    if not target.is_dir():
        print(f"Error: Expected a directory: {args.path}", file=sys.stderr)
        return 1

    def _live_scan() -> dict:
        effective_exclude = _resolve_exclusions(None, False)
        result = scan_tree(target, exclude_dirs=effective_exclude)
        result["_root_path"] = str(target)
        return result

    result = get_or_scan(target, "scan_directory", str(target), _live_scan)
    tree = result.get("tree")
    if tree is None:
        print(f"Error: {result.get('error', 'Scan failed')}", file=sys.stderr)
        return 1
    print(f"Indexed {args.path}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync cache — re-scan stale entries for the given path."""
    target = Path(args.path).resolve()
    if not target.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        return 1
    if not target.is_dir():
        print(f"Error: Expected a directory: {args.path}", file=sys.stderr)
        return 1

    entries = list_entries_by_path(target, str(target))
    if not entries:
        print(f"No cached entries for {args.path}. Run 'filegraph index' first.")
        return 1

    refreshed = 0
    fresh = 0
    for entry in entries:
        if check_freshness(target, entry["cache_key"]):
            fresh += 1
        else:
            refreshed += 1

    print(f"Synced: {refreshed} refreshed, {fresh} fresh")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show cache statistics."""
    # Walk up from cwd to find nearest .filegraph/cache.db
    current = Path.cwd()
    while True:
        db_path = current / ".filegraph" / "cache.db"
        if db_path.exists():
            break
        parent = current.parent
        if parent == current:
            # Reached filesystem root without finding cache
            print("Cache entries: 0")
            print("Total files:   0")
            print("DB size:       0 bytes")
            return 0
        current = parent

    stats = cache_stats(current)
    print(f"Cache entries: {stats['entries']}")
    print(f"Total files:   {stats['total_files']}")
    print(f"DB size:       {stats['size_bytes']} bytes")
    return 0


def cmd_unindex(args: argparse.Namespace) -> int:
    """Remove cache entries for the given path."""
    target = Path(args.path).resolve()
    removed = invalidate_path(target, str(target))
    print(f"Removed {removed} cached entries")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="filegraph",
        description="Directory scanning and file system inspection tools",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan directory hierarchy")
    scan_parser.add_argument("path", help="Directory to scan")
    scan_parser.add_argument("--format", choices=["json", "tree"], default="tree")
    scan_parser.add_argument("--depth", type=int, default=None, help="Max depth")
    scan_parser.add_argument("--no-exclude", action="store_true", help="Include excluded dirs")
    scan_parser.set_defaults(func=cmd_scan)

    # find-duplicates
    dup_parser = subparsers.add_parser("find-duplicates", help="Find duplicate files")
    dup_parser.add_argument("path", help="Directory to scan")
    dup_parser.add_argument("--format", choices=["json", "tree"], default="tree")
    dup_parser.add_argument("--algo", default="sha256", help="Hash algorithm")
    dup_parser.add_argument("--min-size", type=int, default=0, help="Min file size")
    dup_parser.set_defaults(func=cmd_find_duplicates)

    # search
    search_parser = subparsers.add_parser("search", help="Search files by type")
    search_parser.add_argument("path", help="Directory to search")
    search_parser.add_argument("type", help="File extension (e.g. jpg, png)")
    search_parser.add_argument("--format", choices=["json", "tree"], default="tree")
    search_parser.add_argument("--no-exclude", action="store_true", help="Include excluded dirs")
    search_parser.set_defaults(func=cmd_search)

    # find-patterns
    pattern_parser = subparsers.add_parser("find-patterns", help="Find naming patterns")
    pattern_parser.add_argument("path", help="Directory to scan")
    pattern_parser.add_argument("--format", choices=["json", "tree"], default="tree")
    pattern_parser.add_argument("--strategy", default="auto", help="Detection strategy")
    pattern_parser.add_argument("--min-group", type=int, default=3, help="Min group size")
    pattern_parser.set_defaults(func=cmd_find_patterns)

    # index
    index_parser = subparsers.add_parser("index", help="Create/update cache for directory")
    index_parser.add_argument("path", help="Directory to index")
    index_parser.set_defaults(func=cmd_index)

    # sync
    sync_parser = subparsers.add_parser("sync", help="Incremental cache update")
    sync_parser.add_argument("path", help="Directory to sync")
    sync_parser.set_defaults(func=cmd_sync)

    # status
    status_parser = subparsers.add_parser("status", help="Show cache statistics")
    status_parser.set_defaults(func=cmd_status)

    # unindex
    unindex_parser = subparsers.add_parser("unindex", help="Remove cache for path")
    unindex_parser.add_argument("path", help="Directory to unindex")
    unindex_parser.set_defaults(func=cmd_unindex)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
