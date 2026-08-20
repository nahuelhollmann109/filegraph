# Design: v2-features — Core Enhancements, CLI Mode, and CI

## Technical Approach

The change introduces five capabilities in four phases, each building on the previous. Phase 1 extracts a shared `walk_directory` helper and adds exclusion logic. Phase 2 adds `find_duplicates` and `find_patterns` as pure scanner functions with MCP tool wrappers. Phase 3 adds a CLI entry point using stdlib `argparse`. Phase 4 adds a GitHub Actions CI workflow. All new scanner functions live in `src/scanner.py`; MCP wrappers stay in `src/tools.py`; CLI logic stays in `src/cli.py`. Zero new runtime dependencies — `argparse` is stdlib.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Walk helper design | `walk_directory(root, exclude_dirs, max_depth)` yields `Path` objects | `rglob` with post-filter; `os.walk` with depth tracking | `os.walk` supports pruning (skip `descend`) without stat-ing children; yields one path per entry; depth tracking is trivial with a counter |
| scan_tree traversal | Keep recursive `_scan_node` with exclusion logic baked in, don't use `walk_directory` | Force `scan_tree` to call `walk_directory` then reconstruct tree | `scan_tree` needs parent→child hierarchy; `walk_directory` yields flat paths; reconstructing a tree from flat paths is more code and slower. Exclusion logic is 3 lines — duplicating it in `_scan_node` is simpler than a complex adapter |
| CLI framework | stdlib `argparse` with subcommands | `click`, `typer` | Zero new dependencies. Project already has minimal deps (`fastmcp` only). `argparse` handles subcommands, help, and validation adequately |
| Tree output format (CLI) | Simple indentation with `├──` / `│` / `└──` characters, hand-built | `rich.tree`, custom formatter | Zero deps. The tree structure is shallow and predictable — a recursive formatter is ~20 lines |
| Pattern detection strategy | Regex for sequences/dates, longest common prefix/suffix for text patterns | ML-based clustering, filesystem metadata analysis | Deterministic, fast, no deps. Regex is sufficient for `_001`..`_010` and `2024-01-15` patterns. LCS for prefix/suffix is O(n·m) but m (filename length) is tiny |
| Exclusion constant name | `DEFAULT_EXCLUDED_DIRS` (matches spec exactly) | `EXCLUDE_DIRS`, `_EXCLUDE` | Spec mandates this exact name |

## Data Flow

```
User (MCP) ──→ tools.py ──→ scanner.py ──→ os.walk (pruning)
User (CLI)  ──→ cli.py  ──→ scanner.py ──→ os.walk (pruning)
                        └──→ hashlib (duplicates)
                        └──→ re (patterns)

scanner.py functions:
  walk_directory()     ← shared traversal primitive
  scan_tree()          ← uses _scan_node with exclusions (not walk_directory)
  search_files()       ← calls walk_directory
  find_duplicates()    ← calls walk_directory, groups by size, hashes
  find_patterns()      ← calls walk_directory, regex + LCS analysis
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/scanner.py` | Modify | Add `DEFAULT_EXCLUDED_DIRS`, `walk_directory()`, `find_duplicates()`, `find_patterns()`. Update `search_files()` to use `walk_directory`. Add exclusion params to `scan_tree` via `_scan_node` |
| `src/tools.py` | Modify | Add `find_duplicates()`, `find_patterns()` MCP wrappers. Update `scan_directory()` and `search_by_type()` to pass `exclude_dirs`/`include_excluded` params |
| `src/main.py` | Modify | Register `find_duplicates` and `find_patterns` on MCP server |
| `src/cli.py` | Create | CLI entry point with `argparse` subcommands: `scan`, `find-duplicates`, `search`, `find-patterns`. Tree formatter. JSON output |
| `pyproject.toml` | Modify | Add `[project.scripts] graph = "src.cli:main"`. No new runtime deps |
| `.github/workflows/ci.yml` | Create | GitHub Actions workflow: push/PR trigger, Python 3.12 matrix, `pip install -e ".[dev]"`, `pytest`, optional `ruff check` |
| `tests/test_scanner.py` | Modify | Add `TestWalkDirectory`, `TestFindDuplicates`, `TestFindPatterns`, exclusion tests for existing functions |
| `tests/test_cli.py` | Create | CLI integration tests using `subprocess.run` or `CliRunner`-style invocation |

## Interfaces / Contracts

### scanner.py — New functions

```python
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset({".git", "node_modules", "__pycache__", ".venv"})

def walk_directory(
    root: Path,
    exclude_dirs: set[str] | None = None,
    max_depth: int | None = None,
) -> Iterator[Path]:
    """Yield every file path under root, pruning excluded dirs. Skips symlinks."""

def find_duplicates(
    path: Path,
    exclude_dirs: set[str] | None = None,
    hash_algo: str = "sha256",
    min_size: int = 0,
) -> list[dict]:
    """Return list of duplicate groups: [{"hash": str, "size": int, "files": [str, ...]}]"""

def find_patterns(
    path: Path,
    exclude_dirs: set[str] | None = None,
    strategy: str = "auto",
    min_group_size: int = 3,
) -> list[dict]:
    """Return list of pattern groups: [{"type": str, "pattern": str, "files": [str, ...]}]"""
```

### scanner.py — Modified signatures

```python
def scan_tree(
    path: Path,
    max_depth: int | None = None,
    exclude_dirs: set[str] | None = None,   # NEW
    _current_depth: int = 0,
) -> dict:

def search_files(
    path: Path,
    file_type: str,
    exclude_dirs: set[str] | None = None,   # NEW
) -> list[dict]:
```

### tools.py — Modified MCP wrappers

```python
def scan_directory(
    path: str,
    max_depth: int | None = None,
    exclude_dirs: list[str] | None = None,  # NEW
    include_excluded: bool = False,          # NEW
) -> dict:

def search_by_type(
    path: str,
    file_type: str,
    exclude_dirs: list[str] | None = None,  # NEW
    include_excluded: bool = False,          # NEW
) -> dict:

def find_duplicates(
    path: str,
    hash_algo: str = "sha256",
    min_size: int = 0,
) -> dict:

def find_patterns(
    path: str,
    strategy: str = "auto",
    min_group_size: int = 3,
) -> dict:
```

### Exclusion resolution logic (shared)

```python
def _resolve_exclusions(
    exclude_dirs: list[str] | None,
    include_excluded: bool,
) -> set[str] | None:
    """Return the effective exclusion set."""
    if include_excluded:
        return set(exclude_dirs) if exclude_dirs else set()  # empty = no exclusions
    return set(exclude_dirs) if exclude_dirs is not None else DEFAULT_EXCLUDED_DIRS
```

### Pattern detection approach

```python
# Sequence detection: regex r'(.+?)(\d+)(\D*)$' applied to each filename stem.
# Group files by (prefix, suffix) from the regex match.
# Verify numeric parts form a contiguous or incrementing sequence.

# Prefix detection: longest common prefix across all filenames (minus extension).
# Require prefix length >= 3 chars and shared by >= min_group_size files.

# Suffix detection: longest common suffix (before extension).

# Date detection: regex r'(\d{4}[-_]\d{2}[-_]\d{2})' in filename stem.
# Group files sharing the same date-token pattern structure.
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit — walk_directory | Exclusion pruning, max_depth, symlink skipping, permission errors | Create tmp dirs with excluded subdirs; assert excluded dirs not yielded |
| Unit — find_duplicates | Two-pass hashing, min_size filter, hash_algo selection, unreadable files | Create dirs with identical files, varying sizes, permission-denied files |
| Unit — find_patterns | Each strategy (prefix, suffix, sequence, date), min_group_size, auto mode | Create dirs with patterned filenames; assert correct groups returned |
| Unit — exclusion integration | scan_tree and search_files respect exclude_dirs | Add excluded dirs to existing test fixtures; assert entries omitted |
| Unit — _resolve_exclusions | All combinations of exclude_dirs/include_excluded | Pure function tests, no filesystem needed |
| Integration — CLI | Each subcommand with --format json and --format tree | `subprocess.run(["python", "-m", "src.cli", "scan", ...])` in tmp dirs |
| Integration — MCP tools | find_duplicates and find_patterns via tools.py wrappers | Call wrapper functions directly with tmp dirs |
| Existing tests | All 17 existing tests still pass | Run `pytest` before and after refactor |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. The CLI invokes scanner functions directly; no shell command execution or subprocess spawning occurs within the scanned code.

## Migration / Rollout

**No data migration required.** This is a pure additive change.

**Refactor safety**: The walk helper refactor touches `search_files` (replacing `rglob`). Existing tests cover `search_files` with symlinks, nested dirs, and extensions — these validate the refactor didn't break behavior. The `_scan_node` function in `scan_tree` gets exclusion logic added as a parameter with `None` default — existing callers pass nothing, so behavior is unchanged.

**CI**: The workflow file is new and doesn't affect existing code. It runs on push/PR, so it activates automatically after merge.

**Rollback**: Delete `src/cli.py`, `.github/workflows/ci.yml`. Revert `scanner.py` and `tools.py` changes. All existing tests validate the revert.

## Open Questions

- [ ] Should `find_duplicates` exclude symlinks by default (spec says "MUST NOT follow symlinks")? Design assumes yes — `walk_directory` skips symlinks.
- [ ] Should `find_patterns` detect overlapping patterns (e.g., files matching both prefix and sequence)? Spec says "most specific pattern group(s) without duplication" — design returns all non-overlapping groups, sequence wins over prefix when both match.
- [ ] CLI tree format for `find_duplicates` and `find_patterns` — how to render groups? Design uses section headers (e.g., `Hash: abc123 (3 files)`) with indented file lists.
