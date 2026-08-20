# CLI Interface Specification

## Purpose

Provides a standalone `graph` command that exposes scanning, duplicate detection, search, and pattern analysis without the MCP server, reusing the same scanner logic.

## Requirements

### Requirement: graph entry point

The package MUST define a `graph` console entry point via `pyproject.toml [project.scripts]`. Invoking `graph` without a subcommand MUST print usage and exit with a non-zero status.

#### Scenario: No arguments

- GIVEN a user runs `graph` with no arguments
- WHEN the CLI parses arguments
- THEN usage text is printed and the process exits non-zero

#### Scenario: Entry point installed

- GIVEN the package is installed with `pip install -e .`
- WHEN the user runs `graph --help`
- THEN the command resolves to the CLI and lists the available subcommands

### Requirement: Subcommands

The CLI MUST provide `scan`, `find-duplicates`, `search`, and `find-patterns` subcommands. Each MUST mirror its MCP tool counterpart in behavior and arguments (`path`, `max_depth`, `exclude_dirs`, `hash_algo`, `min_size`, `strategy`).

#### Scenario: scan mirrors MCP tool

- GIVEN a user runs `graph scan /tmp/proj --max-depth 2`
- WHEN the CLI executes
- THEN the output matches `scan_directory` for the same arguments

#### Scenario: find-duplicates standalone

- GIVEN a user runs `graph find-duplicates /tmp/proj`
- WHEN the CLI executes
- THEN duplicate groups are printed without starting the MCP server

### Requirement: Output formats

The CLI MUST accept `--format json|tree` (default `json`). `json` MUST emit machine-readable output equivalent to the MCP tool result; `tree` MUST emit a human-readable indented rendering.

#### Scenario: JSON format

- GIVEN a user runs `graph scan /tmp/proj --format json`
- WHEN the CLI emits output
- THEN the output is valid JSON parseable by standard tools

#### Scenario: Tree format

- GIVEN a user runs `graph scan /tmp/proj --format tree`
- WHEN the CLI emits output
- THEN entries are rendered as an indented hierarchy

#### Scenario: Invalid format

- GIVEN a user runs `graph scan /tmp/proj --format xml`
- WHEN the CLI validates arguments
- THEN the CLI errors and exits non-zero

### Requirement: --no-exclude flag

The CLI MUST accept `--no-exclude` on traversal subcommands. When set, the CLI MUST disable default exclusions (equivalent to passing an empty exclusion list).

#### Scenario: Flag disables exclusions

- GIVEN a user runs `graph scan /tmp/proj --no-exclude`
- WHEN the CLI executes
- THEN `.git` and `node_modules` appear in the results

### Requirement: No MCP dependency at runtime

The CLI MUST import scanner logic directly and MUST NOT require the MCP server or a running MCP connection.

#### Scenario: Runs without MCP

- GIVEN the `fastmcp` server is not running
- WHEN a user runs `graph find-duplicates /tmp/proj`
- THEN the command succeeds and prints results

#### Scenario: Error path exit code

- GIVEN a user passes a nonexistent path
- WHEN the CLI executes
- THEN an error message is printed and the process exits non-zero

### Requirement: Cache management subcommands

The CLI MUST provide `index`, `sync`, `status`, and `unindex` subcommands operating on the `.filegraph/cache.db` store. None of them MUST require the MCP server.

#### Scenario: index caches a path

- GIVEN a user runs `filegraph index /tmp/proj`
- WHEN the command performs a live scan
- THEN results are written to `.filegraph/cache.db` and the process exits zero

#### Scenario: index rejects an invalid path

- GIVEN a user runs `filegraph index /nonexistent`
- WHEN the command resolves the path
- THEN an error is printed and the process exits non-zero

#### Scenario: sync refreshes a stale path

- GIVEN a cached path with a newer file on disk
- WHEN a user runs `filegraph sync /tmp/proj`
- THEN the cache entry is refreshed and the process exits zero

#### Scenario: sync reports an up-to-date cache

- GIVEN a fresh cache entry for a path
- WHEN a user runs `filegraph sync /tmp/proj`
- THEN the command reports the cache is current without re-scanning

#### Scenario: status shows statistics

- GIVEN a cache with stored entries
- WHEN a user runs `filegraph status`
- THEN per-tool entry, hit, and miss counts are printed and the process exits zero

#### Scenario: status with no cache

- GIVEN no cache database exists
- WHEN a user runs `filegraph status`
- THEN zero counts are printed and the process exits zero

#### Scenario: unindex clears a path

- GIVEN cached entries for /tmp/proj
- WHEN a user runs `filegraph unindex /tmp/proj`
- THEN all entries for that path are removed and the process exits zero

#### Scenario: unindex is idempotent

- GIVEN no cache entry exists for /tmp/proj
- WHEN a user runs `filegraph unindex /tmp/proj`
- THEN the command succeeds and the process exits zero

## Acceptance Criteria

- index, sync, status, and unindex run without the MCP server
- Invalid paths fail with a non-zero exit code
- unindex is idempotent
- status works with an empty or missing cache
- No new CLI dependency is introduced (stdlib sqlite3)
