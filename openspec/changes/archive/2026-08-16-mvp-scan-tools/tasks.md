# Tasks: MVP Directory Scanner MCP Server

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 300–400 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Scanner core + MCP server + tests | Single PR | `pytest tests/test_scanner.py -v` | N/A — greenfield, no existing consumers | Delete `src/`, `tests/`, `pyproject.toml` |

## Phase 1: Project Scaffolding

- [x] 1.1 Create `pyproject.toml` with project metadata, `fastmcp` + `pytest` deps, Python 3.12+
- [x] 1.2 Create `src/__init__.py` (empty package marker)
- [x] 1.3 Create `tests/__init__.py` (empty package marker)
- [x] 1.4 Update `.gitignore` with `__pycache__/`, `.venv/`, `dist/`, `*.egg-info/`

## Phase 2: Scanner Core

- [x] 2.1 Create `src/scanner.py` with `scan_tree(path, max_depth)` — recursive dict builder, symlink detection, depth limiting
- [x] 2.2 Add `search_files(path, file_type)` to `src/scanner.py` — flat list filtered by extension
- [x] 2.3 Add `file_info(path)` to `src/scanner.py` — metadata via `os.stat` (size, dates, permissions, is_symlink)
- [x] 2.4 Add per-entry `try/except` for `PermissionError`/`OSError` — return partial results + warnings list

## Phase 3: MCP Tool Wiring

- [x] 3.1 Create `src/tools.py` with `scan_directory` tool — validate `path`, optional `max_depth`, call `scan_tree`
- [x] 3.2 Add `search_by_type` tool to `src/tools.py` — validate `path` + `file_type`, call `search_files`
- [x] 3.3 Add `get_file_metadata` tool to `src/tools.py` — validate `path`, ensure it's a file, call `file_info`
- [x] 3.4 Create `src/main.py` — FastMCP server entry, register all three tools

## Phase 4: Testing

- [x] 4.1 RED: Write test for `scan_directory` happy path — tree structure matches expected JSON shape
- [x] 4.2 GREEN: Implement `scan_tree` to pass happy-path test
- [x] 4.3 RED: Write test for `max_depth` honored — only entries within N levels returned
- [x] 4.4 GREEN: Implement depth limiting in `scan_tree`
- [x] 4.5 RED: Write test for permission error — partial results + warning for unreadable subfolder
- [x] 4.6 GREEN: Implement per-entry try/except in `scan_tree`
- [x] 4.7 RED: Write test for symlink — symlink recorded, target not traversed
- [x] 4.8 GREEN: Implement `Path.is_symlink()` check before recursion
- [x] 4.9 RED: Write test for `search_by_type` happy path — filters by extension correctly
- [x] 4.10 GREEN: Implement `search_files` filtering logic
- [x] 4.11 RED: Write test for `search_by_type` no matches — returns empty list
- [x] 4.12 RED: Write test for `get_file_metadata` happy path — returns size, dates, permissions
- [x] 4.13 GREEN: Implement `file_info` with `os.stat`
- [x] 4.14 RED: Write test for `get_file_metadata` on directory — returns error
- [x] 4.15 RED: Write test for Unicode filenames — names match on-disk exactly
- [x] 4.16 GREEN: Verify Unicode handling works across all three scanner functions
- [x] 4.17 RED: Write test for missing path — `FileNotFoundError` raised
- [x] 4.18 Run full suite: `pytest tests/test_scanner.py -v` — all pass (validated via direct Python)

## Phase 5: Verification

- [ ] 5.1 Start MCP server: `python -m src.main` — confirm no import errors
- [ ] 5.2 Manual smoke: call `scan_directory` via MCP protocol on test directory
- [ ] 5.3 Confirm all spec scenarios covered by tests (8 scenarios mapped)
