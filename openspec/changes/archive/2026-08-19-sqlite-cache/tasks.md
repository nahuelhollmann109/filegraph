# Tasks: sqlite-cache — Scan Result Caching

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~445 (src: 265, tests: 180) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Store + cache modules with unit tests | PR 1 | `pytest tests/test_store.py tests/test_cache.py -v` | Create tmp dirs with files, verify cache round-trips | `src/store.py`, `src/cache.py`, `tests/test_store.py`, `tests/test_cache.py` |
| 2 | Tool integration + CLI commands | PR 2 | `pytest tests/ -v && filegraph index /tmp/test && filegraph status` | Full CLI invocation with real directory scan | `src/tools.py`, `src/cli.py` changes |

PR #1 base = feature branch; PR #2 base = PR #1 branch.

---

## Phase 1: Store + Schema (~100 lines)

- [x] 1.1 Create `src/store.py` with `init_db(project_root: Path) -> None` — create `.filegraph/cache.db`, enable WAL mode, create `cache` table (cache_key, tool_name, path, result_json, cached_at, max_mtime), `cache_files` table (cache_key, file_path, mtime), and indexes
  - Files: `src/store.py`
  - Deps: none
  - Verify: `python -c "from src.store import init_db; init_db(Path('/tmp/test'))"` — creates `.filegraph/cache.db`

- [x] 1.2 Add `get_cache(cache_key: str) -> dict | None` — query cache table by key, return `{result_json, cached_at, max_mtime, path, tool_name}` or None
  - Files: `src/store.py`
  - Deps: 1.1
  - Verify: set then get returns same data

- [x] 1.3 Add `set_cache(cache_key, tool_name, path, result_json, file_set)` — upsert into cache table + insert file_set rows into cache_files, use ON CONFLICT for upsert
  - Files: `src/store.py`
  - Deps: 1.1
  - Verify: set same key twice, only one row exists

- [x] 1.4 Add `invalidate_path(path: str) -> int` — delete all cache entries matching path (cascade deletes cache_files via FK), return count deleted
  - Files: `src/store.py`
  - Deps: 1.1
  - Verify: insert entries for two paths, invalidate one, only other remains

- [x] 1.5 Add `search_fts(query: str) -> list[dict]` — query FTS5 virtual table with LIKE fallback if FTS5 unavailable
  - Files: `src/store.py`
  - Deps: 1.1
  - Verify: insert files, search substring, get matches

- [x] 1.6 Add `cache_stats() -> dict` — return `{entries: N, total_files: N, size_bytes: N}` from cache + cache_files tables
  - Files: `src/store.py`
  - Deps: 1.1
  - Verify: after inserting entries, stats reflect counts

---

## Phase 2: Cache Logic (~70 lines)

- [x] 2.1 Create `src/cache.py` with `make_cache_key(tool_name: str, path: str, **kwargs) -> str` — SHA256 hash of (tool_name, path, sorted_json(kwargs)), deterministic
  - Files: `src/cache.py`
  - Deps: none
  - Verify: same inputs → same key, different options → different key

- [x] 2.2 Add `extract_file_set(result: dict, tool_name: str) -> list[tuple[str, float]]` — walk result dict to extract (file_path, mtime) tuples; handle different tool result shapes (scan_tree returns nested, search_files returns flat)
  - Files: `src/cache.py`
  - Deps: none
  - Verify: extract from scan_tree result and search_files result

- [x] 2.3 Add `check_freshness(cache_key: str) -> bool` — load entry from store, compare recorded files vs current disk state: check max_mtime > cached_at, check for deleted files (cache_files row but file missing), check for new files (file exists but not in cache_files), check mtime of each recorded file; skip PermissionError/OSError files
  - Files: `src/cache.py`
  - Deps: 1.2, 1.4, 2.2
  - Verify: cache entry + modify file mtime → returns False; cache entry + no changes → returns True

- [x] 2.4 Add `get_or_scan(tool_name: str, path: str, scan_fn, **kwargs) -> dict` — check cache hit via `get_cache(make_cache_key(...))`, if hit call `check_freshness`, if fresh return cached result_json parsed as dict, if stale or miss call `scan_fn`, `set_cache` result + file_set, return result
  - Files: `src/cache.py`
  - Deps: 2.1, 2.3, 1.3
  - Verify: call twice, second call returns cached result without re-scanning

---

## Phase 3: Tool Integration (~15 lines)

- [x] 3.1 Modify `src/tools.py` — import `get_or_scan` from `src.cache`, wrap `scan_directory` to call `get_or_scan("scan_directory", path, _live_scan, ...)` with a `_live_scan` helper that calls the original scanner, pass through existing return type unchanged
  - Files: `src/tools.py`
  - Deps: 2.4
  - Verify: `scan_directory("/tmp/test")` returns same result format; second call is faster (cached)

- [x] 3.2 Wrap `search_by_type`, `find_duplicates`, `find_patterns` in `src/tools.py` — same pattern: each gets a `_live_<tool>` helper, wrapped with `get_or_scan`; `get_file_metadata` skipped (single-file, not worth caching per proposal)
  - Files: `src/tools.py`
  - Deps: 3.1
  - Verify: all existing tool return types preserved, no regressions

---

## Phase 4: CLI Commands (~80 lines)

- [x] 4.1 Add `cmd_index(args)` to `src/cli.py` — resolve path, call `get_or_scan` for `scan_directory` to populate cache, print "Indexed N files"
  - Files: `src/cli.py`
  - Deps: 2.4
  - Verify: `filegraph index /tmp/test` creates `.filegraph/cache.db`

- [x] 4.2 Add `cmd_sync(args)` to `src/cli.py` — for each cached entry matching path, call `check_freshness`, re-scan stale entries, print "Synced: N refreshed, M fresh"
  - Files: `src/cli.py`
  - Deps: 2.4
  - Verify: `filegraph sync /tmp/test` after modifying a file shows "refreshed"

- [x] 4.3 Add `cmd_status(args)` to `src/cli.py` — call `cache_stats()`, print entries count, total files, DB size
  - Files: `src/cli.py`
  - Deps: 1.6
  - Verify: `filegraph status` shows cache stats after indexing

- [x] 4.4 Add `cmd_unindex(args)` to `src/cli.py` — call `invalidate_path(path)` for exact match + prefix match (entries where path starts with arg), print "Removed N cached entries"
  - Files: `src/cli.py`
  - Deps: 1.4
  - Verify: `filegraph unindex /tmp/test` removes cache, subsequent scan is live

- [x] 4.5 Register all four subcommands in `build_parser()` — add `index`, `sync`, `status`, `unindex` subparsers with appropriate args (path required for index/sync/unindex, no args for status)
  - Files: `src/cli.py`
  - Deps: 4.1, 4.2, 4.3, 4.4
  - Verify: `filegraph --help` shows all four new commands

---

## Phase 5: Tests (~180 lines)

- [x] 5.1 Create `tests/test_store.py` — test `init_db` creates DB with correct tables, test `set_cache`/`get_cache` round-trip, test upsert overwrites, test `invalidate_path` removes one path not others, test `cache_stats` returns correct counts
  - Files: `tests/test_store.py`
  - Deps: 1.1-1.6
  - Verify: `pytest tests/test_store.py -v` all pass

- [x] 5.2 Add FTS5 tests to `tests/test_store.py` — test `search_fts` returns matching filenames, test LIKE fallback path when FTS5 unavailable
  - Files: `tests/test_store.py`
  - Deps: 1.5
  - Verify: `pytest tests/test_store.py::TestSearchFts -v`

- [x] 5.3 Create `tests/test_cache.py` — test `make_cache_key` determinism and option sensitivity, test `extract_file_set` for scan_tree and search_files result shapes
  - Files: `tests/test_cache.py`
  - Deps: 2.1, 2.2
  - Verify: `pytest tests/test_cache.py -v` all pass

- [x] 5.4 Add freshness validation tests to `tests/test_cache.py` — test fresh cache served (no file changes), test modified file invalidates (touch file → stale), test new file invalidates (add file → stale), test deleted file invalidates (remove file → stale), test unstatable file skipped (chmod 000 → still fresh if others OK)
  - Files: `tests/test_cache.py`
  - Deps: 2.3
  - Verify: `pytest tests/test_cache.py::TestFreshness -v`

- [x] 5.5 Add `get_or_scan` integration test to `tests/test_cache.py` — call `get_or_scan` twice, verify second call returns cached result (mock scanner to count calls), test cache miss triggers scan, test stale cache triggers re-scan
  - Files: `tests/test_cache.py`
  - Deps: 2.4
  - Verify: `pytest tests/test_cache.py::TestGetOrScan -v`
