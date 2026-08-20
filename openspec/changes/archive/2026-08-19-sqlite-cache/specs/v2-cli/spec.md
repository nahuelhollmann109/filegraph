# Delta for CLI Interface

## ADDED Requirements

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