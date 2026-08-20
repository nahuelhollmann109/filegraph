# Archive Report: sqlite-cache

## Change Summary

**Change**: sqlite-cache — Scan Result Caching
**Project**: filegraph
**Date**: 2026-08-19
**Status**: COMPLETE

## What Was Delivered

Per-project SQLite cache for scan results with mtime-based invalidation. Two PRs shipped:
- **PR 1**: `src/store.py` (schema/CRUD) + `src/cache.py` (invalidation logic) + unit tests
- **PR 2**: `src/tools.py` (cache-aware wrappers) + `src/cli.py` (index/sync/status/unindex) + integration tests

## Final State Facts

| Metric | Value |
|--------|-------|
| Tasks completed | 22/22 |
| Tests passing | 154 |
| Lines changed | ~777 across 8 files |
| Cache location | `.filegraph/cache.db` (per project root) |
| New dependencies | None (sqlite3 stdlib) |

### CLI Commands Added
- `filegraph index <path>` — pre-scan and cache a directory
- `filegraph sync <path>` — refresh stale cache entries
- `filegraph status` — show cache hit/miss statistics
- `filegraph unindex <path>` — clear cache for a path

## Spec Sync Summary

### scan-cache (new spec)
- Created `openspec/specs/scan-cache/spec.md` — full spec with 4 requirements:
  - Cache location and schema
  - CRUD operations
  - FTS5 filename search
  - mtime-based invalidation

### directory-scanning (modified)
- Added: **Cache key generation** requirement (SHA256 of canonical tuple)
- Modified: **scan_directory** — cache-aware; returns cached tree on hit, re-scans on miss/stale
- Modified: **search_by_type** — cache-aware; flat list on hit, re-scans on miss/stale
- Modified: **get_file_metadata** — cache-aware; serves cached metadata when fresh

### v2-cli (modified)
- Added: **Cache management subcommands** requirement — index, sync, status, unindex

## Archive Contents

```
openspec/changes/archive/2026-08-19-sqlite-cache/
├── proposal.md
├── design.md
├── tasks.md
└── specs/
    ├── scan-cache/spec.md
    ├── directory-scanning/spec.md
    └── v2-cli/spec.md
```

## Source of Truth Updated

The following main specs now reflect the new behavior:
- `openspec/specs/scan-cache/spec.md` — created (new capability)
- `openspec/specs/directory-scanning/spec.md` — updated with cache-aware requirements
- `openspec/specs/v2-cli/spec.md` — updated with cache management subcommands

## Observations Read

- proposal.md (archived)
- design.md (archived)
- tasks.md (archived) — all 22 tasks checked
- specs/scan-cache/spec.md (archived)
- specs/directory-scanning/spec.md (archived)
- specs/v2-cli/spec.md (archived)
- openspec/specs/directory-scanning/spec.md (main, pre-merge)
- openspec/specs/v2-cli/spec.md (main, pre-merge)
- openspec/config.yaml

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived.
