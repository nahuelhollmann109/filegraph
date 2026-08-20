# Tasks: v2-features — Core Enhancements, CLI Mode, and CI

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~520 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Walk helper + default exclusions | PR 1 | `pytest tests/test_scanner.py -k "walk or exclude"` | Create tmp dir with `.git`, `node_modules` subdirs; verify excluded entries absent | Revert `scanner.py` walk/exclusion changes; existing tests still pass |
| 2 | find_duplicates + find_patterns | PR 2 | `pytest tests/test_scanner.py -k "duplicate or pattern"` | Tmp dir with identical files and patterned filenames; verify groups returned | Remove `find_duplicates`/`find_patterns` from `scanner.py` and `tools.py` |
| 3 | CLI mode | PR 3 | `pytest tests/test_cli.py` | `graph scan /tmp/proj --format json` in tmp dir; verify output | Delete `src/cli.py`, revert `pyproject.toml` |
| 4 | CI + docs | PR 3 | `act -j test` or push to branch | GitHub Actions workflow runs on push | Delete `.github/workflows/ci.yml` |

## Phase 1: Shared Walk Helper + Exclusion Logic

Foundation for all traversal — everything else depends on this.

- [x] 1.1 Add `DEFAULT_EXCLUDED_DIRS: frozenset[str]` constant to `src/scanner.py` — value `{".git", "node_modules", "__pycache__", ".venv"}` (~5 lines)
  - Files: `src/scanner.py`
  - Deps: none
  - Verify: import scanner; assert `DEFAULT_EXCLUDED_DIRS == {".git", "node_modules", "__pycache__", ".venv"}`

- [x] 1.2 Add `_resolve_exclusions(exclude_dirs, include_excluded) → set[str] | None` helper to `src/scanner.py` (~12 lines)
  - Files: `src/scanner.py`
  - Deps: 1.1
  - Verify: unit test all 4 combinations (None+False, list+False, None+True, list+True)

- [x] 1.3 Add `walk_directory(root, exclude_dirs, max_depth) → Iterator[Path]` to `src/scanner.py` using `os.walk` with pruning (~40 lines)
  - Files: `src/scanner.py`
  - Deps: 1.1
  - Verify: create tmp dir with `.git/sub/file.txt`, `src/file.txt`; assert `.git` subtree not yielded; assert symlinks skipped

- [x] 1.4 Refactor `search_files()` in `src/scanner.py` to call `walk_directory` instead of `rglob("*")` (~10 lines changed)
  - Files: `src/scanner.py`
  - Deps: 1.3
  - Verify: existing `test_search_files` tests still pass

- [x] 1.5 Add `exclude_dirs` parameter to `scan_tree()` via `_scan_node()` with default `None` (~15 lines)
  - Files: `src/scanner.py`
  - Deps: 1.1
  - Verify: existing `test_scan_tree` tests pass; new test: `scan_tree(path, exclude_dirs=["build"])` omits build subtree

- [x] 1.6 Update `scan_directory()` and `search_by_type()` in `src/tools.py` to accept `exclude_dirs` and `include_excluded` params, pass through to scanner (~20 lines)
  - Files: `src/tools.py`
  - Deps: 1.2, 1.4, 1.5
  - Verify: `scan_directory(path, include_excluded=True)` returns `.git`; `scan_directory(path)` omits it

- [x] 1.7 Add exclusion tests to `tests/test_scanner.py` — `TestWalkDirectory`, `TestResolveExclusions`, exclusion integration for scan_tree/search_files (~45 lines)
  - Files: `tests/test_scanner.py`
  - Deps: 1.1–1.6
  - Verify: `pytest tests/test_scanner.py -k "walk or exclude"` passes

**Phase 1 total: ~147 lines**

## Phase 2: find_duplicates + find_patterns

New scanner functions + MCP wrappers. Depends on Phase 1 walk helper.

- [x] 2.1 Add `find_duplicates(path, exclude_dirs, hash_algo, min_size) → list[dict]` to `src/scanner.py` (~55 lines)
  - Files: `src/scanner.py`
  - Deps: 1.3
  - Verify: create dir with 2 identical files + 1 unique; assert one group returned; assert unique file absent

- [x] 2.2 Add `find_patterns(path, exclude_dirs, strategy, min_group_size) → list[dict]` to `src/scanner.py` (~75 lines)
  - Files: `src/scanner.py`
  - Deps: 1.3
  - Verify: create dir with `file_001.txt`..`file_005.txt`; assert sequence group returned; test prefix/suffix/date detection

- [x] 2.3 Add `find_duplicates()` and `find_patterns()` MCP wrappers to `src/tools.py` (~30 lines)
  - Files: `src/tools.py`
  - Deps: 2.1, 2.2
  - Verify: call wrapper with tmp dir; assert result dict has expected keys

- [x] 2.4 Register `find_duplicates` and `find_patterns` on MCP server in `src/main.py` (~5 lines)
  - Files: `src/main.py`
  - Deps: 2.3
  - Verify: server starts; tools appear in tool list

- [x] 2.5 Add `TestFindDuplicates` tests to `tests/test_scanner.py` — happy path, no duplicates, min_size, hash_algo, unreadable files, symlinks (~50 lines)
  - Files: `tests/test_scanner.py`
  - Deps: 2.1
  - Verify: `pytest tests/test_scanner.py -k "duplicate"` passes

- [x] 2.6 Add `TestFindPatterns` tests to `tests/test_scanner.py` — each strategy, min_group_size, auto mode, nonexistent path (~45 lines)
  - Files: `tests/test_scanner.py`
  - Deps: 2.2
  - Verify: `pytest tests/test_scanner.py -k "pattern"` passes

**Phase 2 total: ~260 lines**

## Phase 3: CLI Mode

Standalone `graph` command. Depends on scanner functions from Phases 1–2.

- [x] 3.1 Create `src/cli.py` with `argparse` — `main()`, subcommand parser, `--format json|tree`, `--no-exclude` flag (~100 lines)
  - Files: `src/cli.py`
  - Deps: 1.6, 2.3
  - Verify: `python -m src.cli --help` prints subcommands; no args exits non-zero

- [x] 3.2 Add `[project.scripts] graph = "src.cli:main"` and `[project.optional-dependencies]` to `pyproject.toml` (~10 lines)
  - Files: `pyproject.toml`
  - Deps: 3.1
  - Verify: `pip install -e .` creates `graph` command; `graph --help` works

- [x] 3.3 Create `tests/test_cli.py` — test each subcommand with `--format json` and `--format tree`, test `--no-exclude`, test error paths (~40 lines)
  - Files: `tests/test_cli.py`
  - Deps: 3.1, 3.2
  - Verify: `pytest tests/test_cli.py` passes

**Phase 3 total: ~150 lines**

## Phase 4: CI + Documentation

GitHub Actions and doc updates. Independent of code changes.

- [x] 4.1 Create `.github/workflows/ci.yml` — push/PR triggers, Python 3.12 matrix, pip install, pytest, optional ruff, dependency caching (~35 lines)
  - Files: `.github/workflows/ci.yml`
  - Deps: 3.2
  - Verify: push to branch; workflow runs and passes

- [x] 4.2 Update README or inline docs to reflect new CLI commands and exclusion behavior (~15 lines)
  - Files: `README.md` or equivalent
  - Deps: 3.1
  - Verify: docs mention `graph scan`, `graph find-duplicates`, default exclusions

**Phase 4 total: ~50 lines**

## Key Learnings

1. The walk helper refactor is the critical path — all other phases depend on it.
2. `scan_tree` keeps its own `_scan_node` recursion rather than using `walk_directory`, per design decision.
3. The threat matrix is N/A — no shell, subprocess, or VCS boundaries in this change.
