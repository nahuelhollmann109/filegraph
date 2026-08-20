# Exploration: SQLite Storage/Persistence Layer for filegraph

## Current State

filegraph is a **stateless** Python 3.12 MCP server (`fastmcp`) that scans directories on every tool call. No caching, no persistence, no background processes.

| Module | Role | Notes |
|--------|------|-------|
| `src/scanner.py` (512 lines) | Core scanning logic | `walk_directory` (os.walk, prunes excluded dirs), `scan_tree` (recursive JSON tree), `search_files`, `find_duplicates` (two-pass: size groups → hash), `find_patterns` (sequence/prefix/suffix/date), `file_info` |
| `src/tools.py` (151 lines) | MCP tool wrappers | 5 tools: `scan_directory`, `search_by_type`, `get_file_metadata`, `find_duplicates`, `find_patterns`. All resolve + validate path, then call scanner |
| `src/main.py` (24 lines) | FastMCP server | Registers the 5 tools, `mcp.run()` |
| `src/cli.py` (194 lines) | `filegraph` CLI | argparse subcommands: scan, search, find-duplicates, find-patterns (uses `src.tools` directly) |
| `tests/` | 729-line scanner tests + CLI tests | Existing coverage is the safety net for any refactor |

**Key characteristics that shape the design:**
- Every call walks the filesystem from scratch (I/O-bound; `os.walk` + stat on each file).
- `find_duplicates` re-hashes file contents on every call — the most expensive operation (full file reads).
- Tools accept arbitrary paths — the server is not anchored to one project like CodeGraph is.
- Default exclusions: `.git`, `node_modules`, `__pycache__`, `.venv` (frozenset, overridable per call).
- All v2 work (exclusions, duplicates, patterns, CLI, CI) is complete — this change builds on the current codebase.

## CodeGraph Reference (what we copy)

Inspected a real CodeGraph 1.1.4 index (`~/.codegraph` daemon + `Portal-Pacientes/.codegraph/codegraph.db`). The storage patterns that transfer to filegraph:

1. **`.codegraph/` directory in the project root**, gitignored (`*` + `!.gitignore`). DB lives with the data it describes.
2. **`codegraph.db` — SQLite with:**
   - `files(path PK, content_hash, language, size, modified_at, indexed_at, node_count, errors)` — the **incremental-sync anchor**: `modified_at` + `content_hash` are compared against the filesystem to detect what changed.
   - `nodes` — symbol rows with line/col spans.
   - `edges` — graph relationships (FK → nodes, ON DELETE CASCADE).
   - `nodes_fts` — **FTS5 external-content table** over `(id, name, qualified_name, docstring, signature)`.
   - `project_metadata(key PK, value, updated_at)` — key/value config.
   - `schema_versions(version PK, applied_at, description)` — **migration tracking**.
3. **Incremental sync, not full rebuilds**: daemon log shows `Auto-synced 1 file(s) in 82ms` and `Caught up 3 file(s) changed since last run`. Only changed files are re-indexed; `content_hash`/`modified_at` are the change detectors.
4. **File watcher daemon** (`daemon.sock`, `daemon.log`, pid): watches the project, auto-syncs on FS events, idle-timeout backstop (5 min). Lazy init: a missing `.codegraph/` is the trigger to initialize.
5. No FTS triggers — external content is maintained by indexer code during sync.

filegraph has **no symbol model**, so `nodes`/`edges`/`unresolved_refs` do not transfer. What transfers: the `files` table pattern, `content_hash`/`modified_at` as the staleness anchor, FTS5 filename search, `schema_versions` migrations, per-root storage directory, incremental sync.

## Proposed Storage Architecture

### Storage location

**`<root>/.filegraph/filegraph.db` per indexed root** — CodeGraph parity. Written only when the root is **explicitly indexed** (`filegraph index <path>` or env `FILEGRAPH_CACHE=1`), never implicitly by an MCP scan:

- Cache lives with the data it describes; per-project isolation; `.filegraph/` is gitignore-able (CodeGraph ships `*` + `!.gitignore` inside its dir).
- Non-invasive default: filegraph is an MCP server that scans **arbitrary** paths — silently creating `.filegraph/` inside user directories would be hostile. Explicit opt-in avoids that.
- Override via `--db` / `FILEGRAPH_DB_DIR` for centralized setups (e.g. all caches under `~/.local/share/filegraph/`).
- If a root is not indexed, tools fall back to the current live-scan behavior — **zero behavior change for existing users**.

### Sync model — on-demand reconciliation (core), watcher deferred (v2)

| Option | Pros | Cons |
|--------|------|------|
| **A. On-demand reconcile (recommended)** | No daemon, no new deps, survives server restarts, matches stateless MCP reality. Cheap: `os.scandir` dirent metadata (no extra stat calls on most platforms) diffed against `files.modified_at`/`size`; upsert changed, delete missing, reset `content_hash` on change | First call after index creation walks the tree once (unavoidable); does not catch changes while the server is *idle* (irrelevant — nothing is served while idle) |
| **B. File watcher daemon (CodeGraph parity)** | Auto-sync in ~80ms, always fresh for long-running servers | Needs `watchdog` dep + daemon lifecycle (socket, pid, idle backstop), thread integration with FastMCP's asyncio loop, handles only changes while the process runs — the DB persists anyway so on-demand covers restarts. High complexity for marginal gain in an MCP context |
| **C. Hybrid: reconcile-on-read + optional `filegraph watch`** | Best of both; watcher is a CLI command, not a server requirement | Two code paths to maintain; watcher still optional v2 |

**Recommendation: A, with C's watcher explicitly deferred to v2.** The MCP server IS the long-running process; a reconcile-on-read guarantees correctness at every tool call with zero lifecycle machinery. The expensive operations are content hashing (fixed by the hash cache) and repeated full-tree walks (fixed by diffing against the DB).

### What gets cached

| Data | Table | Value |
|------|-------|-------|
| File rows (path, name, ext, size, mtime, mode, symlink) | `files` | `search_by_type` → SQL by extension; `scan_directory` tree → SQL grouped by parent; `get_file_metadata` → row lookup + mtime/size re-verify |
| **Content hashes** (sha256) | `files.content_hash` | `find_duplicates` re-hashes **only** files whose (size, mtime) changed or whose hash is NULL — the biggest win; full-file reads become one-time |
| Filename FTS | `files_fts` | `search_by_type` and future name-search via FTS5 `MATCH` |
| Root config (exclusions, hash algo, depth) | `roots` | Per-root scan parameters — config change invalidates the index |

Not cached (cheap, derived): `find_patterns` runs over DB rows (names only, no I/O).

### Freshness guarantee

- `files.modified_at` (st_mtime_ns) + `size` are the staleness key, exactly like CodeGraph's `content_hash` + `modified_at`.
- A cached `content_hash` is trusted **only** when the current (size, mtime) match the indexed row — a hash is never served for a changed file.
- `scan_directory` / `search_by_type` answers come from the DB **only after** the reconcile diff has run in the same call.

## Schema Design

```sql
-- Migration tracking (CodeGraph `schema_versions` parity)
CREATE TABLE schema_versions (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL,
    description TEXT NOT NULL
);

-- One row per explicitly indexed root
CREATE TABLE roots (
    root_path      TEXT PRIMARY KEY,              -- absolute, normalized
    created_at     INTEGER NOT NULL,
    last_indexed_at INTEGER,
    file_count     INTEGER NOT NULL DEFAULT 0,
    config_json    TEXT NOT NULL DEFAULT '{}'     -- exclusions, hash_algo, max_depth
);

-- File entries — the incremental-sync anchor (CodeGraph `files` parity)
CREATE TABLE files (
    id           INTEGER PRIMARY KEY,
    root_path    TEXT NOT NULL REFERENCES roots(root_path) ON DELETE CASCADE,
    path         TEXT NOT NULL UNIQUE,            -- absolute path
    name         TEXT NOT NULL,
    extension    TEXT NOT NULL DEFAULT '',        -- lowercase, no dot
    parent_dir   TEXT NOT NULL,                   -- for tree assembly
    size         INTEGER NOT NULL,
    modified_at  INTEGER NOT NULL,                -- st_mtime_ns
    created_at   INTEGER,
    mode         INTEGER,
    is_symlink   INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,                            -- sha256; NULL until first duplicate analysis
    indexed_at   INTEGER NOT NULL
);
CREATE INDEX idx_files_root        ON files(root_path);
CREATE INDEX idx_files_root_ext    ON files(root_path, extension);
CREATE INDEX idx_files_parent      ON files(parent_dir);
CREATE INDEX idx_files_modified    ON files(root_path, modified_at);

-- FTS5 external-content filename search (CodeGraph `nodes_fts` parity)
CREATE VIRTUAL TABLE files_fts USING fts5(
    name, path, extension,
    content='files',
    content_rowid='id'
);

-- FTS kept in sync by triggers during reconcile writes
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, path, extension)
    VALUES (new.id, new.name, new.path, new.extension);
END;
CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path, extension)
    VALUES ('delete', old.id, old.name, old.path, old.extension);
END;
CREATE TRIGGER files_au AFTER UPDATE OF name, path, extension ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path, extension)
    VALUES ('delete', old.id, old.name, old.path, old.extension);
    INSERT INTO files_fts(rowid, name, path, extension)
    VALUES (new.id, new.name, new.path, new.extension);
END;
```

Pragmas: `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON` — safe for concurrent MCP server restarts.

**Reconcile algorithm (per tool call on an indexed root):**
1. `os.scandir` walk (reuse `walk_directory` from scanner.py for exclusions) collecting `(path, size, mtime_ns, mode, is_symlink)`.
2. Diff against `files`: upsert new/changed rows (`content_hash` reset to NULL when size/mtime changed), delete missing rows. Update `roots.file_count`, `roots.last_indexed_at`.
3. Answer from SQL. For `find_duplicates`: hash only rows with NULL/stale `content_hash` in multi-size groups (existing two-pass logic moves to SQL for the size grouping, file reads only for uncached hashes).

## File Changes Needed

| File | Change | Est. lines (authored) |
|------|--------|----------------------|
| `src/store.py` | **New** — SQLite connection, schema + migrations (schema_versions), CRUD for roots/files, FTS triggers, WAL pragmas | ~120 |
| `src/indexer.py` | **New** — reconcile diff (scandir vs files), upsert/delete, hash-cache invalidation, tree assembly from rows | ~140 |
| `src/tools.py` | **Modified** — cache-aware paths in all 5 tools (reconcile-on-read, SQL answers, cached hashes) | ~80 |
| `src/main.py` | **Modified** — optional `FILEGRAPH_CACHE` env / `--cache` flag wiring | ~15 |
| `src/cli.py` | **Modified** — `index`, `sync`, `status`, `unindex` subcommands | ~90 |
| `tests/test_store.py` | **New** — schema/migrations/CRUD/FTS tests | ~140 |
| `tests/test_indexer.py` | **New** — reconcile diff, hash invalidation, staleness tests | ~110 |
| `pyproject.toml` | **Modified** — no new deps (sqlite3 stdlib); optional `watchdog` extra deferred | ~5 |
| `README.md` | **Modified** — persistence usage docs | ~20 |
| **Total** | | **~720** |

## Approaches Compared

1. **SQLite cache + reconcile-on-read (recommended)** — stdlib `sqlite3`, zero new deps, backward compatible (cache only for indexed roots), kills the two hot spots (re-hashing, re-walking). Effort: Medium.
2. **CodeGraph-parity watcher daemon** — `watchdog` + daemon lifecycle (socket/pid/idle backstop). Freshest possible data, but high complexity, only helps while running, new dependency. Effort: High. → v2.
3. **Full graph model (nodes/edges)** — does not map to filegraph (no symbol model). Effort: High. → out of scope.
4. **JSON snapshot cache** — no schema/migrations/FTS; breaks on large trees; no incremental diff. Effort: Low but wrong tool.

## Risks and Considerations

| Risk | Mitigation |
|------|------------|
| **Stale cache served to user** | Hard guarantee: answers from DB only after reconcile diff in the same call; `content_hash` trusted only when (size, mtime) match |
| **Invasive writes** (`.filegraph/` in user dirs) | Explicit opt-in only (`filegraph index`, `FILEGRAPH_CACHE=1`); never created implicitly by scans |
| **Hash cache staleness on coarse mtime** | Use `st_mtime_ns` + size as the key; hash re-computed on any mismatch |
| **First-index cost** (walk + hash warm-up) | Walk is unavoidable; hashing stays lazy (NULL until first `find_duplicates`) |
| **Concurrent server restarts / multi-client** | WAL + busy_timeout; reconcile is idempotent (upsert/delete) |
| **DB growth on huge trees** | Index on (root_path, extension); FTS5 external content keeps FTS small; `filegraph unindex` to drop |
| **Config change (exclusions/hash algo) vs stale index** | `roots.config_json` recorded; mismatch → force re-index |
| **FTS5 trigger maintenance** | Triggers are part of the migration set; covered by `tests/test_store.py` |
| **~720 lines vs 400-line budget** | **High risk** → chained PRs recommended (3 slices: foundation → sync+integration → CLI+docs), matching the auto-chain preference |

## Recommendation

Adopt **approach 1**: SQLite cache at `<root>/.filegraph/filegraph.db`, per-root explicit opt-in, reconcile-on-read with `(size, st_mtime_ns)` staleness and lazy sha256 hash caching, FTS5 filename search with triggers, `schema_versions` migrations — CodeGraph's storage patterns adapted to filegraph's arbitrary-path, stateless-MCP reality. Watcher daemon deferred to v2. Split into 3 chained PRs to respect the 400-line budget.

## Ready for Proposal

**Yes.** Enough is known: schema is concrete, sync model is decided, CodeGraph reference is real (inspected a live index), line estimates and PR slicing are forecast. The proposal phase should confirm only: (a) change name (`sqlite-persistence` suggested), (b) default DB location policy (`.filegraph/` in root vs `FILEGRAPH_DB_DIR`), (c) whether the watcher is truly v2 or in scope.