# Design: sqlite-cache

## Technical Approach

Add a per-project SQLite cache layer between MCP tools/CLI and the scanner. Two new modules (`store.py` for schema/CRUD, `cache.py` for invalidation logic) handle all cache operations. Existing tools and CLI are modified to check cache before scanning, with mtime-based invalidation ensuring freshness. The cache is opt-in: uncached calls scan live and behave identically to current behavior.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Storage engine | SQLite stdlib (`sqlite3`) | Redis, JSON files, in-memory dict | Zero new deps; per-project file is portable; stdlib is available everywhere Python runs |
| Cache key scheme | SHA256 of `(tool_name, path, canonical_options)` | Path-only, composite columns | Composite key avoids collisions between tools with different options on same path |
| Invalidation strategy | `cache_files` table + per-file mtime check | Directory mtime only, content hash | Per-file check catches modifications within unmodified directories; content hash too expensive for large trees |
| FTS5 for filenames | FTS5 virtual table with LIKE fallback | LIKE-only, external search lib | FTS5 gives fast substring search when available; LIKE fallback ensures portability |
| Cache opt-in | CLI commands (`index`/`sync`) | Always-on, env var flag | Explicit control matches proposal scope; no hidden performance cliff for users |
| Concurrency model | WAL mode + single-writer | File locking, separate daemon | WAL allows concurrent reads during writes; MCP tools are sequential anyway |

## Data Flow

```
MCP tool call                          CLI command
    │                                      │
    ▼                                      ▼
tools.py                             cli.py
    │                                      │
    ▼                                      ▼
cache.py ──── get(tool, path, opts) ◄──────┘
    │
    ├── Cache HIT ──► validate(file_mtimes)
    │                      │
    │              ┌───────┴───────┐
    │              ▼               ▼
    │          FRESH           STALE
    │            │               │
    │            ▼               ▼
    │     return cached    re-scan (scanner.py)
    │                         │
    │                         ▼
    │                    set_cache(result, file_set)
    │                         │
    │                         ▼
    │                    return refreshed
    │
    └── Cache MISS ──► scan (scanner.py)
                            │
                            ▼
                       set_cache(result, file_set)
                            │
                            ▼
                       return result

    store.py ◄── All cache reads/writes ──► .filegraph/cache.db (WAL)
```

## Schema Design

```sql
-- Enable WAL mode for concurrent read/write
PRAGMA journal_mode=WAL;

-- Main cache table: one row per (tool + path + options) combo
CREATE TABLE IF NOT EXISTS cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key   TEXT UNIQUE NOT NULL,      -- SHA256(tool_name || path || sorted_opts_json)
    tool_name   TEXT NOT NULL,             -- e.g. "scan_directory", "search_by_type"
    path        TEXT NOT NULL,             -- resolved absolute path scanned
    result_json TEXT NOT NULL,             -- JSON-serialized tool result
    cached_at   REAL NOT NULL,             -- time.time() when stored
    max_mtime   REAL NOT NULL              -- max mtime across files in result
);

CREATE INDEX IF NOT EXISTS idx_cache_path ON cache(path);
CREATE INDEX IF NOT EXISTS idx_cache_tool ON cache(tool_name);

-- File manifest: one row per file in each cached result
CREATE TABLE IF NOT EXISTS cache_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key   TEXT NOT NULL,             -- FK → cache.cache_key
    file_path   TEXT NOT NULL,             -- absolute path of the file
    mtime       REAL NOT NULL,             -- file's mtime when cached
    FOREIGN KEY (cache_key) REFERENCES cache(cache_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cache_files_key ON cache_files(cache_key);

-- FTS5 virtual table for filename substring search
CREATE VIRTUAL TABLE IF NOT EXISTS cache_fts USING fts5(
    file_path,
    content=cache_files,
    content_rowid=id
);
-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS cache_files_ai AFTER INSERT ON cache_files BEGIN
    INSERT INTO cache_fts(rowid, file_path) VALUES (new.id, new.file_path);
END;
CREATE TRIGGER IF NOT EXISTS cache_files_ad AFTER DELETE ON cache_files BEGIN
    INSERT INTO cache_fts(cache_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
END;
```

**Column rationale:**
- `cache_key`: unique lookup; SHA256 prevents collisions
- `tool_name`: filter/cache per tool; useful for `status` command
- `path`: scope invalidation; `invalidate_path` deletes by this
- `result_json`: full serialized result; avoids re-scanning
- `cached_at`: timestamp for invalidation comparison
- `max_mtime`: fast pre-check — if no file is newer than `cached_at`, skip file-level scan

## Invalidation Logic

```
function check_freshness(cache_entry):
    # Quick check: if any file was modified after caching, stale
    if cache_entry.max_mtime > cache_entry.cached_at:
        return STALE

    # Load recorded file set
    recorded_files = get_file_set(cache_entry.cache_key)
    current_files = walk_directory(cache_entry.path)

    # Check for deleted files
    for recorded in recorded_files:
        if not exists(recorded.file_path):
            return STALE

    # Check for new/modified files (compare sets)
    recorded_set = {f.file_path for f in recorded_files}
    current_set  = {str(f) for f in current_files}

    if recorded_set != current_set:
        return STALE

    # Check mtimes of recorded files (catch in-place modifications)
    for recorded in recorded_files:
        try:
            current_mtime = stat(recorded.file_path).st_mtime
            if current_mtime > cache_entry.cached_at:
                return STALE
        except (PermissionError, OSError):
            continue  # skip unstatable files per spec

    return FRESH
```

**Edge cases:**
- **PermissionError on stat**: skip file, continue validation (per spec)
- **File deleted between walk and stat**: treated as stale (will re-scan)
- **Empty directory**: cached result is always fresh (no files to change)
- **Symlinks**: not walked (existing scanner behavior), so not cached

## File Changes

| File | Action | What Changes | Est. Lines |
|------|--------|-------------|------------|
| `src/store.py` | Create | SQLite schema init, `get_cache`, `set_cache`, `invalidate_path`, `search_fts`, `cache_stats` | ~100 |
| `src/cache.py` | Create | `check_freshness`, `get_or_scan` (cache-aware scan wrapper) | ~70 |
| `src/tools.py` | Modify | Import `get_or_scan`; replace direct scanner calls with `get_or_scan` in each tool | +15 |
| `src/cli.py` | Modify | Add `index`, `sync`, `status`, `unindex` subcommands and their handlers | +80 |
| `tests/test_store.py` | Create | CRUD round-trips, upsert, invalidate, FTS search, stats | ~100 |
| `tests/test_cache.py` | Create | Freshness validation, stale detection, file set comparison | ~80 |

## Interfaces / Contracts

```python
# src/store.py
def init_db(project_root: Path) -> None: ...
def get_cache(cache_key: str) -> dict | None: ...
def set_cache(cache_key: str, tool_name: str, path: str,
              result_json: str, file_set: list[tuple[str, float]]) -> None: ...
def invalidate_path(path: str) -> int: ...  # returns rows deleted
def search_fts(query: str) -> list[dict]: ...
def cache_stats() -> dict: ...  # {"entries": N, "hits": N, "misses": N, "size_bytes": N}

# src/cache.py
def make_cache_key(tool_name: str, path: str, **kwargs) -> str: ...
def check_freshness(cache_key: str) -> bool: ...
def get_or_scan(tool_name: str, path: str, scan_fn, **kwargs) -> dict: ...
def extract_file_set(result: dict, tool_name: str) -> list[tuple[str, float]]: ...
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `store.py` CRUD round-trips | Create tmp DB, set/get/invalidate, assert values |
| Unit | `cache.py` key generation | Assert deterministic keys for same inputs |
| Unit | `cache.py` freshness validation | Create cache entry, modify file mtime, assert stale |
| Unit | `cache.py` deleted file detection | Cache entry, delete file, assert stale |
| Unit | `cache.py` new file detection | Cache entry, add file, assert stale |
| Integration | End-to-end cache hit | `get_or_scan` twice; second call must not re-walk |
| Integration | CLI `index`/`status`/`unindex` | Invoke CLI commands, verify DB state |
| Integration | FTS5 filename search | Insert file paths, query substrings, assert matches |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. New `.filegraph/cache.db` is created on first use. Existing tools continue scanning live when no cache exists — fully backward compatible.

**Rollback:** Delete `.filegraph/cache.db`, remove `src/store.py` and `src/cache.py`, revert `src/tools.py` and `src/cli.py` changes.

## Open Questions

- [ ] Should `find_duplicates` cache results? (Content-hashing is expensive, but cache invalidation is still mtime-based — so a duplicate scan result can go stale even if hashes haven't changed. The proposal includes it in scope, so yes.)
- [ ] Should `get_file_metadata` cache? (Single-file metadata is cheap; caching adds overhead with little benefit. Proposal includes it in scope — we follow spec, but could disable by default later.)
- [ ] FTS5 availability: how to detect at runtime? (Try `CREATE VIRTUAL TABLE` in a try/except; fall back to LIKE.)
