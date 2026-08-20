# Delta for Directory Scanning

## ADDED Requirements

### Requirement: Cache key generation

Tools MUST compute cache keys as the SHA256 digest of a canonical `(tool_name, path, options)` tuple with options serialized deterministically (sorted keyword arguments). Equivalent invocations MUST produce the same key; differing options MUST produce different keys.

#### Scenario: Equivalent options, same key

- GIVEN two invocations with identical path and options in different argument orders
- WHEN cache keys are computed
- THEN the keys are equal

#### Scenario: Different options, different keys

- GIVEN two invocations differing in one option value
- WHEN cache keys are computed
- THEN the keys differ

## MODIFIED Requirements

### Requirement: scan_directory returns a JSON tree

`scan_directory` MUST accept `path` and optional `max_depth`, and MUST return the folder/file hierarchy as a JSON tree (folders, subfolders, and files at file level — common types like jpg, png, docx; not code-level). It MUST NOT traverse beyond the specified directory root. When a fresh cache entry exists for the invocation's key, the tool MUST return the cached JSON tree without re-scanning; on miss or stale entry it MUST scan live, store the result, and return it. The returned shape (`tree` + `warnings`) MUST be identical in both paths.
(Previously: always performed a live scan on every invocation)

#### Scenario: Happy path

- GIVEN a directory with subfolders and files
- WHEN a client calls `scan_directory` with that path
- THEN the system returns a JSON tree of the hierarchy rooted at the specified path

#### Scenario: Cache hit returns instant result

- GIVEN a fresh cached result for the invocation key
- WHEN `scan_directory` is called with the same arguments
- THEN the cached JSON tree is returned without walking the directory

#### Scenario: Cache miss falls back to live scan

- GIVEN no cache entry exists for the invocation key
- WHEN `scan_directory` is called
- THEN a live scan runs, the result is cached, and the tree is returned

#### Scenario: Stale entry triggers re-scan

- GIVEN a cached entry with a newer file on disk
- WHEN `scan_directory` is called
- THEN a live scan runs and the cache is refreshed

#### Scenario: Max depth honored

- GIVEN a client passes `max_depth: 2`
- WHEN `scan_directory` traverses the tree
- THEN the system returns only entries within two levels

#### Scenario: Permission error returns partial results

- GIVEN a directory with an unreadable subfolder
- WHEN `scan_directory` traverses it
- THEN the system returns the readable portion
- AND includes a warning for the unreadable subfolder

#### Scenario: Symlink not followed

- GIVEN a symlink pointing outside the scanned directory
- WHEN `scan_directory` encounters it
- THEN the system records the symlink itself
- AND does not recurse into its target

### Requirement: search_by_type returns a flat list

`search_by_type` MUST accept `path` and a file type filter, and MUST return a flat list of matching files under the specified directory. It MUST NOT search outside the given path. The tool MUST serve fresh cache hits without scanning and MUST fall back to a live scan (then cache) on miss or staleness.
(Previously: always performed a live scan on every invocation)

#### Scenario: Happy path

- GIVEN a directory with jpg and png files
- WHEN a client calls `search_by_type` with path and type `jpg`
- THEN the system returns only the jpg files as a flat list

#### Scenario: Cache hit served without scanning

- GIVEN a fresh cached result for type jpg at the same path
- WHEN `search_by_type` is called with the same arguments
- THEN the cached flat list is returned

#### Scenario: No matches

- GIVEN a directory with no files of the requested type
- WHEN `search_by_type` is called
- THEN the system returns an empty list

### Requirement: get_file_metadata returns file details

`get_file_metadata` MUST accept a `path` to a file and MUST return size, dates, and permissions for that file. The tool MUST serve cached metadata when the file's current mtime is not newer than `cached_at`, and MUST re-stat and refresh otherwise.
(Previously: always stat'ed the file on every invocation)

#### Scenario: Happy path

- GIVEN an existing readable file
- WHEN a client calls `get_file_metadata` with its path
- THEN the system returns size, modification dates, and permissions

#### Scenario: Cached metadata served

- GIVEN a file whose current mtime is older than cached_at
- WHEN `get_file_metadata` is called
- THEN the cached details are returned without re-stat

#### Scenario: Path is a directory

- GIVEN a `path` pointing to a directory instead of a file
- WHEN `get_file_metadata` resolves the path
- THEN the system returns an error explaining a file path is required

## Acceptance Criteria

- Cache hits return output identical to a live scan
- Miss/stale paths scan live, cache, and return the same shape
- All pre-existing directory-scanning scenarios remain valid
- The cache is never consulted for invalid (missing/not-a-dir) paths