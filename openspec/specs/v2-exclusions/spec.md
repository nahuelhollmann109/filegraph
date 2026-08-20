# Directory Exclusions Specification

## Purpose

Defines default directory exclusions for all traversal tools so scans stay fast and useful in real-world projects. The system MUST exclude `.git`, `node_modules`, `__pycache__`, and `.venv` by default, with explicit per-call overrides.

## ADDED Requirements

### Requirement: DEFAULT_EXCLUDED_DIRS constant

The system MUST define a module-level `DEFAULT_EXCLUDED_DIRS` constant whose value SHALL be `{".git", "node_modules", "__pycache__", ".venv"}`. Every traversal tool MUST exclude these directory names by default.

#### Scenario: Default set defined

- GIVEN the scanner module is imported
- WHEN `DEFAULT_EXCLUDED_DIRS` is read
- THEN it contains exactly `.git`, `node_modules`, `__pycache__`, `.venv`

#### Scenario: Excluded directory skipped by default

- GIVEN a directory containing a `node_modules` subfolder with files
- WHEN `scan_directory` runs without exclusion arguments
- THEN the returned tree contains no `node_modules` entry
- AND no files inside it are reported

### Requirement: exclude_dirs parameter

`scan_directory` and `search_by_type` MUST accept an optional `exclude_dirs: list[str] | None` parameter. When `None`, the system MUST use `DEFAULT_EXCLUDED_DIRS`. When a list is provided, the system MUST exclude exactly those names, replacing the defaults. Excluded names MUST match directory names at any depth.

#### Scenario: Custom exclusions replace defaults

- GIVEN a caller passes `exclude_dirs=["build"]`
- WHEN either tool traverses the directory
- THEN `build` directories are excluded
- AND `.git` is no longer excluded by that call

#### Scenario: Empty list disables exclusions

- GIVEN a caller passes `exclude_dirs=[]`
- WHEN `scan_directory` runs
- THEN the full hierarchy including `.git` and `node_modules` is returned

#### Scenario: Nested excluded directory pruned

- GIVEN an excluded directory name appears at a nested level
- WHEN traversal reaches it
- THEN the subtree is omitted from results

### Requirement: include_excluded override

Both tools MUST accept `include_excluded: bool = False`. When `True`, the system MUST NOT apply `DEFAULT_EXCLUDED_DIRS` unless an explicit `exclude_dirs` list is also provided.

#### Scenario: Override includes default dirs

- GIVEN a caller passes `include_excluded=True` with no `exclude_dirs`
- WHEN `scan_directory` runs
- THEN `.git` and `node_modules` appear in results

#### Scenario: Explicit list beats override

- GIVEN a caller passes `include_excluded=True` AND `exclude_dirs=[".git"]`
- WHEN `scan_directory` runs
- THEN only `.git` is excluded

### Requirement: Shared walk helper

All traversal MUST use a shared `walk_directory(root, exclude_dirs, max_depth)` helper instead of `rglob("*")`. The helper MUST prune excluded directories without descending into them.

#### Scenario: Excluded directory not descended

- GIVEN a top-level excluded directory containing many files
- WHEN traversal runs
- THEN the helper does not stat or list files inside it

#### Scenario: Helper used by all tools

- GIVEN `scan_directory` and `search_by_type` both traverse a directory with exclusions
- WHEN results are compared
- THEN both omit the same excluded directories
