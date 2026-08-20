# Proposal: v2-features — Core Enhancements, CLI Mode, and CI

## Intent

The MCP server has three working tools but lacks practical features needed for real-world use: it scans everything (including `.git`, `node_modules`), has no duplicate detection, and only works through the MCP protocol. This change adds default exclusions, duplicate detection, pattern search, a standalone CLI, and CI — making the project usable both as an MCP tool and as a general-purpose CLI utility.

## Scope

### In Scope

- **Default directory exclusions**: `scan_directory` and `search_by_type` ignore `.git`, `node_modules`, `__pycache__`, `.venv` by default. Add `include_excluded: bool = False` override flag. Refactor to shared walk helper (current `rglob("*")` cannot prune).
- **find_duplicates**: New MCP tool — two-pass strategy (size prefilter, then hash). Accepts `path`, optional `hash_algo` (md5/sha256, default sha256), `min_size` filter.
- **find_patterns**: New MCP tool — detect filename patterns (prefixes, suffixes, sequences like `file_001`..`file_010`, date patterns).
- **CLI mode**: Standalone `graph` command via `pyproject.toml [project.scripts]`. Subcommands: `graph scan`, `graph find-duplicates`, `graph search`. Same logic, no MCP dependency.
- **GitHub Actions CI**: Test workflow on push/PR. Lint + pytest.

### Out of Scope
- Smart reorganization suggestions (v3)
- Content-based file type detection (magic bytes)
- Cross-platform path normalization beyond `pathlib`
- MCP protocol extensions (sampling, notifications)
- Performance benchmarks or profiling infrastructure

## Capabilities

### New Capabilities
- `duplicate-detection`: Finding duplicate files by content hash with size-based prefiltering
- `pattern-analysis`: Detecting filename patterns (prefixes, suffixes, sequences, dates)
- `cli-interface`: Standalone CLI commands that reuse scanner logic without MCP

### Modified Capabilities
- `directory-scanning`: Add default exclusions (`exclude_dirs` list), shared walk helper replacing `rglob("*")`, new `include_excluded` parameter on `scan_directory` and `search_by_type`

## Approach

**Phase 1 — Shared walk + exclusions (blocks everything else)**:
Extract a `walk_directory(root, exclude_dirs, max_depth)` helper in `scanner.py`. All traversal tools call this instead of `rglob`. Default `EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv"}`.

**Phase 2 — find_duplicates + find_patterns**:
New tools in `tools.py`, new logic in `scanner.py`. Duplicates: group files by size (pass 1), hash only groups with 2+ entries (pass 2). Patterns: regex-based classification of filenames.

**Phase 3 — CLI**:
Add `src/cli.py` with `click` or `argparse`. Entry point in `pyproject.toml`. Reuse `scanner.py` functions directly — no MCP import needed.

**Phase 4 — CI**:
`.github/workflows/test.yml` with `ubuntu-latest`, Python 3.12, `pip install -e ".[dev]"`, `pytest`, optional `ruff check`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/scanner.py` | Modified | Extract walk helper, add `EXCLUDE_DIRS`, add duplicate/pattern logic |
| `src/tools.py` | Modified | New tool definitions for `find_duplicates`, `find_patterns`; update existing tools to pass exclusion params |
| `src/main.py` | Modified | Register new tools on MCP server |
| `src/cli.py` | New | CLI entry point with subcommands |
| `pyproject.toml` | Modified | Add `[project.scripts]`, `click`/`ruff` deps, `[project.optional-dependencies]` |
| `.github/workflows/test.yml` | New | CI pipeline |
| `tests/test_scanner.py` | Modified | Tests for exclusions, duplicates, patterns |
| `tests/test_cli.py` | New | CLI integration tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Walk refactor breaks existing scan behavior | Medium | Run existing tests before and after; add exclusion-specific tests |
| Large directories slow duplicate hashing | Medium | `min_size` filter, early exit on small file sets, async hashing optional |
| CLI adds dependency (click) | Low | Use stdlib `argparse` instead if dependency is a concern |
| CI flaky on first run | Low | Pin action versions, cache pip deps |

## Rollback Plan

Revert to the archived `mvp-scan-tools` state: delete `src/cli.py`, `.github/`, remove `find_duplicates`/`find_patterns` from `tools.py` and `scanner.py`, revert `EXCLUDE_DIRS` and walk helper. Existing tests validate nothing broke in the base.

## Dependencies

- `fastmcp` (existing)
- Python 3.12+
- `click` or `argparse` (stdlib) for CLI
- `ruff` (dev, optional) for linting
- `pytest` (dev, existing)

## Success Criteria

- [ ] `scan_directory` skips `.git`, `node_modules`, `__pycache__`, `.venv` by default
- [ ] `scan_directory(include_excluded=True)` returns full tree including excluded dirs
- [ ] `find_duplicates` returns groups of files with identical content hash
- [ ] `find_patterns` classifies filenames into prefix/suffix/sequence/date groups
- [ ] `graph scan <path>` CLI command produces same output as MCP tool
- [ ] `graph find-duplicates <path>` works standalone
- [ ] CI runs on push/PR and passes
- [ ] All existing tests continue to pass
