# Design: MVP Directory Scanner MCP Server

## Technical Approach

Build a Python 3.12 MCP server using FastMCP that exposes three tools — `scan_directory`, `search_by_type`, `get_file_metadata`. Each tool requires a `path` parameter and returns JSON. The scanner uses `pathlib.Path` for traversal with generator-based iteration to control memory. Errors are caught per-entry and surfaced as warnings without crashing the scan.

## Architecture Decisions

### Decision: Project structure

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Flat `main.py` | Simple but no separation | Rejected |
| `src/` layout with `scanner.py`, `tools.py`, `main.py` | Clear module boundaries, testable | **Chosen** |
| `src/` with domain subpackages | Over-engineered for 3 files | Rejected |

**Rationale**: Matches proposal structure. Separates traversal logic (`scanner.py`) from MCP wiring (`tools.py`, `main.py`), enabling unit tests without FastMCP.

### Decision: Directory traversal strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Recursive generator (`yield`) | Lazy evaluation, low memory | Rejected — MCP tool responses need complete results |
| Recursive function returning dicts | Simple, complete, testable | **Chosen** |
| `os.walk` with depth limit | Built-in but awkward max_depth | Rejected |
| `pathlib.Path.rglob` | Elegant but hard to stop at depth | Rejected |

**Rationale**: Recursive dict construction is the simplest approach that produces the required JSON tree. Depth limiting via a `current_depth` parameter is trivial. Generator deferred to v2 if memory becomes an issue.

### Decision: Error handling

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Raise on first error | Simplest, but partial results lost | Rejected |
| Catch per-entry, collect warnings | Partial results + full visibility | **Chosen** |
| Skip errors silently | Hides problems from agent | Rejected |

**Rationale**: Spec requires partial results with warnings on permission errors. Per-entry try/except with a warnings list is the direct implementation.

### Decision: Symlink handling

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Follow symlinks (default pathlib) | Risk of infinite loops, escapes scanned dir | Rejected |
| Record symlink, skip recursion | Safe, spec-compliant | **Chosed** |
| Configurable flag | Extra complexity | Deferred to v2 |

**Rationale**: Spec says "record symlink, do not recurse." Using `Path.is_symlink()` check before recursion is the minimal safe path.

## Data Flow

    Agent ──→ MCP Server (main.py) ──→ Tool Router (tools.py)
                                          │
                                          ├─→ scanner.scan_directory(path, max_depth)
                                          ├─→ scanner.search_by_type(path, file_type)
                                          └─→ scanner.get_file_metadata(path)
                                                │
                                                └─→ pathlib.Path + os.stat
                                                      │
                                                      └─→ JSON response + warnings[]

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Create | Project metadata, fastmcp + pytest deps |
| `src/__init__.py` | Create | Package marker |
| `src/main.py` | Create | FastMCP server entry, registers tools |
| `src/tools.py` | Create | Tool definitions with param validation |
| `src/scanner.py` | Create | Core traversal: scan_tree, search_files, file_info |
| `tests/__init__.py` | Create | Package marker |
| `tests/test_scanner.py` | Create | Unit tests for scanner logic |
| `.gitignore` | Modify | Add `__pycache__/`, `.venv/`, `dist/`, `*.egg-info/` |

## Interfaces / Contracts

```python
# src/scanner.py — core interfaces (not MCP-exposed)
def scan_tree(path: Path, max_depth: int | None = None) -> dict:
    """Returns {"name", "type": "directory", "children": [...]} or file node."""

def search_files(path: Path, file_type: str) -> list[dict]:
    """Returns flat list of {"name", "path", "size"} for matching extensions."""

def file_info(path: Path) -> dict:
    """Returns {"name", "size", "modified", "created", "permissions", "is_symlink"}."""
```

Each function accepts a validated `Path` and raises `FileNotFoundError` or `PermissionError` — the tool layer catches and converts to JSON error responses with warnings.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `scan_tree` depth limiting, tree structure | pytest + tmp_path fixture, assert JSON shape |
| Unit | `search_files` filtering, empty results | tmp_path with mixed file types |
| Unit | `file_info` metadata fields | tmp_path with known file |
| Unit | Permission error → partial results + warning | chmod 000 on subdir, assert warning in output |
| Unit | Symlink recording, no recursion | Create symlink to outside dir, assert not followed |
| Unit | Unicode filenames | Create file with Unicode name, assert exact match |
| Unit | Missing path → FileNotFoundError | Call with nonexistent Path |
| Unit | Directory passed to `file_info` → error | Pass dir Path, assert error message |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. The scanner uses only `pathlib.Path` and `os.stat` — no shell invocation or process spawning.

## Migration / Rollout

No migration required. This is a greenfield project with no existing data or production consumers.

## Open Questions

- [ ] FastMCP async vs sync tool registration — does FastMCP require `async def` or accept sync? (Confirm in Step 2 of apply phase.)
- [ ] Should `scan_directory` return file type categories (image/document/video) or raw extensions? Spec says "common types like jpg, png, docx" — lean toward raw extension for simplicity.
- [ ] Max depth default — should there be a sensible default (e.g., 10) or always require explicit `max_depth`?
