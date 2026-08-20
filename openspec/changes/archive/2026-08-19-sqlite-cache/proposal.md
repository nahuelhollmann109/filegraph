# Proposal: sqlite-cache — Scan Result Caching

## Intent

filegraph re-scans directories from scratch on every tool call. For large directories or repeated queries, this wastes time and tokens. This change adds a per-project SQLite cache so agents get instant results after the first scan, with automatic invalidation when files change.

## Scope

### In Scope
- SQLite cache store in `.filegraph/cache.db` (per project root)
- Cache results from `scan_directory`, `search_by_type`, `find_duplicates`, `find_patterns`, `get_file_metadata`
- Cache key = hash of (tool_name + path + options)
- Invalidation: check `(size, mtime)` — if any file in path has `mtime > cached_at`, re-scan
- CLI commands: `filegraph index <path>`, `filegraph sync <path>`, `filegraph status`, `filegraph unindex <path>`
- Opt-in: uncached calls scan live (backward compatible)

### Out of Scope
- Daemon or file watcher (no background processes)
- Content-based hashing for invalidation (too expensive)
- Cross-project cache sharing
- Cache size limits or eviction policies (deferred)
- Cache warming or precomputation

## Capabilities

### New Capabilities
- `scan-cache`: SQLite-backed cache for scan results with mtime-based invalidation

### Modified Capabilities
- `directory-scanning`: Tools check cache before scanning; cache-aware read path added
- `cli-interface`: New subcommands for cache management (index, sync, status, unindex)

## Approach

**Phase 1 — Cache store (`src/store.py`)**:
Single SQLite table `cache` with columns: `id`, `tool_name`, `cache_key`, `result_json`, `path`, `cached_at`, `max_mtime`. CRUD functions: `get_cache`, `set_cache`, `invalidate_path`, `cache_stats`. SQLite3 is stdlib — no new deps.

**Phase 2 — Invalidation logic (`src/cache.py`)**:
On cache hit: walk `path`, check if any file has `mtime > cached_at`. If yes → re-scan, update cache. If no → return cached result. Use `os.stat()` per file in the scanned set (not full re-walk).

**Phase 3 — Cache-aware tools (`src/tools.py`)**:
Wrap each tool: check cache first, fall back to live scan. Cache the JSON result. Maintain same return type — callers see no difference.

**Phase 4 — CLI commands (`src/cli.py`)**:
Add `index`, `sync`, `status`, `unindex` subcommands. `index` pre-scans and caches. `sync` checks invalidation. `status` shows hit/miss counts. `unindex` clears cache for a path.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/store.py` | New | SQLite schema + CRUD (~60 lines) |
| `src/cache.py` | New | Invalidation logic (~50 lines) |
| `src/tools.py` | Modified | Cache-aware tool wrappers (~40 lines) |
| `src/cli.py` | Modified | index/sync/status/unindex commands (~50 lines) |
| `tests/test_store.py` | New | Cache CRUD and invalidation tests (~80 lines) |
| `pyproject.toml` | Modified | No new deps (sqlite3 is stdlib) |
| `README.md` | Modified | Document cache commands |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Cache grows unbounded | Low | `unindex` manual cleanup; eviction deferred |
| Stale cache served after external edits | Low | mtime check catches most cases; `sync` for manual refresh |
| SQLite lock contention under concurrent access | Low | Single-writer model; MCP tools are sequential |
| Cache key collision (hash mismatch) | Low | Use SHA256 of full (tool+path+options) tuple |

## Rollback Plan

Delete `.filegraph/cache.db`. Remove `src/store.py`, `src/cache.py`. Revert `src/tools.py` and `src/cli.py` to remove cache wrappers. All tools fall back to live scan — zero behavioral change.

## Dependencies

- Python 3.12+ (sqlite3 is stdlib)
- No new external dependencies

## Success Criteria

- [ ] `filegraph index <path>` caches scan results to `.filegraph/cache.db`
- [ ] Second `scan_directory` call on same path returns instantly from cache
- [ ] Adding a file to a cached directory invalidates the cache on next call
- [ ] `filegraph status` shows cache hit/miss statistics
- [ ] `filegraph unindex <path>` clears cache for that path
- [ ] All existing tools continue to work without caching (backward compatible)
- [ ] No new external dependencies added
