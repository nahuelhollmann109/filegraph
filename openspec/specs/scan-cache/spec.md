# Scan Cache Specification

## Purpose

SQLite-backed cache of scan results with mtime-based invalidation, stored per project root. The cache is opt-in: when absent, tools scan live and behave exactly as before.

## Requirements

### Requirement: Cache location and schema

The cache MUST be stored in SQLite at `.filegraph/cache.db` relative to the scanned root. The store MUST create a `cache` table with `cache_key` (unique), `tool_name`, `path`, `result_json`, `cached_at`, `max_mtime`, and a `cache_files` table recording the `file_path` and `mtime` of every file in each cached result. The store MUST enable WAL mode.

#### Scenario: Schema created on first use

- GIVEN no cache exists for a project
- WHEN the store is first accessed
- THEN `.filegraph/cache.db` is created with both tables and WAL enabled

#### Scenario: File set recorded with result

- GIVEN a scan result is cached
- WHEN the result is stored
- THEN every file path and its mtime are recorded in `cache_files`

### Requirement: CRUD operations

The store MUST provide `get_cache(cache_key)` (returns result and metadata or None), `set_cache(...)` (upserts a result and its file set), `invalidate_path(path)` (deletes all entries for a path), and `cache_stats()` (entry and hit/miss counts).

#### Scenario: Set then get round-trip

- GIVEN a result stored for key K
- WHEN get_cache(K) is called
- THEN the stored JSON and max_mtime are returned

#### Scenario: Upsert overwrites

- GIVEN a key K that already exists
- WHEN set_cache(K) stores a new result
- THEN the old value is replaced, not duplicated

#### Scenario: Invalidate removes one path

- GIVEN entries for paths /a and /b
- WHEN invalidate_path("/a") is called
- THEN entries for /a are removed and /b remains

### Requirement: FTS5 filename search

The store MUST index cached file names in an FTS5 virtual table. If the runtime SQLite lacks FTS5, the store MUST fall back to LIKE queries with equivalent semantics.

#### Scenario: Filename lookup from index

- GIVEN cached results containing photo.jpg
- WHEN a filename query for "photo" runs
- THEN matching file paths are returned from the index

### Requirement: mtime-based invalidation

Before serving a hit, the system MUST verify freshness: the cache is stale if any current file has mtime newer than `cached_at`, if any file recorded in `cache_files` is missing on disk, or if the current file set differs from the recorded set. Stale caches MUST trigger a re-scan and refresh. Files that fail to stat MUST be skipped.

#### Scenario: Fresh cache served

- GIVEN every current file mtime is older than cached_at and the file set matches
- WHEN a tool requests the cached result
- THEN the cached result is returned without re-scanning

#### Scenario: Modified file invalidates

- GIVEN a cached file whose mtime is now newer than cached_at
- WHEN the cache is checked
- THEN the tool re-scans and the cache is refreshed

#### Scenario: New file invalidates

- GIVEN a new file with mtime newer than cached_at
- WHEN the cache is checked
- THEN the tool re-scans and the new file appears in results

#### Scenario: Deleted file invalidates

- GIVEN a file recorded in cache_files no longer exists on disk
- WHEN the cache is checked
- THEN the tool re-scans and results no longer include the file

#### Scenario: Unstatable file skipped

- GIVEN a file raising PermissionError on stat
- WHEN the cache is checked
- THEN the file is skipped and the cache is served if otherwise fresh

## Acceptance Criteria

- Cache lives at `.filegraph/cache.db` with WAL enabled
- set/get/invalidate/stats round-trip correctly
- FTS5 index answers filename queries
- New, modified, and deleted files each trigger re-scan
- Unstatable files never invalidate a fresh cache