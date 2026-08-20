# Proposal: MVP Directory Scanner MCP Server

## Intent

Build the initial MCP server that exposes three directory-scanning tools for agents to inspect and reorganize file systems. This is the project's first deliverable — no source code exists yet.

## Scope

### In Scope
- Python 3.12 project scaffolding (`pyproject.toml`, `src/` layout)
- FastMCP server entry point with tool registration
- Three core tools: `scan_directory`, `search_by_type`, `get_file_metadata`
- JSON output format (tree for scan, flat list for search)
- Edge cases: permission errors, symlink handling, Unicode filenames, max depth
- Basic pytest setup and unit tests for scanner logic

### Out of Scope
- Enhanced tools (duplicates, statistics, empty folders) — deferred to v2
- Smart reorganization suggestions — deferred to v3
- Cross-platform path normalization beyond `pathlib.Path`
- Content-based file type detection (magic bytes)

## Capabilities

### New Capabilities
- `directory-scanning`: Core tool set for scanning directories, filtering by type, and retrieving file metadata

### Modified Capabilities
None — first change in the project.

## Approach

Start with multiple specialized tools (not a single mode-parameter tool) for clarity and testability. Use `pathlib.Path` throughout. Implement async scanning where possible. Wrap `PermissionError` and `OSError` to return partial results with warnings.

**Project structure:**
```
pyproject.toml
src/
  __init__.py
  main.py          # FastMCP server entry
  tools.py          # Tool definitions
  scanner.py        # Core scanning logic
tests/
  test_scanner.py
```

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | New | Project metadata, FastMCP dependency |
| `src/main.py` | New | MCP server entry point |
| `src/tools.py` | New | Tool definitions (scan_directory, search_by_type, get_file_metadata) |
| `src/scanner.py` | New | Directory traversal, metadata extraction |
| `tests/test_scanner.py` | New | Unit tests for scanner logic |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Large directories exhaust memory | Medium | Generator-based traversal, limit results |
| Permission errors crash scan | High | Catch `PermissionError`, return partial with warning |
| FastMCP API changes | Low | Pin version in pyproject.toml |

## Rollback Plan

Delete the change folder and `src/` directory. No production data at risk — this is a new project.

## Dependencies

- `fastmcp` (latest stable)
- Python 3.12+
- `pytest` (dev dependency)

## Success Criteria

- [ ] `scan_directory` returns correct JSON tree for test directories
- [ ] `search_by_type` filters files by extension correctly
- [ ] `get_file_metadata` returns size, dates, permissions
- [ ] Permission errors handled gracefully (no crashes)
- [ ] All tests pass via `pytest`
- [ ] Server starts and registers tools with MCP protocol
