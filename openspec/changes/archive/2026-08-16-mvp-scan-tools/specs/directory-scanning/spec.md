# Directory Scanning Specification

## Purpose

Exposes three MCP tools — `scan_directory`, `search_by_type`, `get_file_metadata` — for agents to inspect and reorganize a file system. Every tool MUST require a `path` parameter and each scan MUST target ONLY the specified directory path.

## Requirements

### Requirement: Required path parameter

Every tool MUST require a non-empty `path` parameter. The system MUST reject an invocation without a valid `path` and MUST NOT scan any location other than the specified directory.

#### Scenario: Missing path rejected

- GIVEN a client invokes a tool without a `path` parameter
- WHEN the tool validates the request
- THEN the system returns a validation error
- AND performs no scan

#### Scenario: Nonexistent path rejected

- GIVEN a `path` that does not exist on disk
- WHEN the tool resolves the path
- THEN the system returns an error indicating the path was not found

### Requirement: scan_directory returns a JSON tree

`scan_directory` MUST accept `path` and optional `max_depth`, and MUST return the folder/file hierarchy as a JSON tree (folders, subfolders, and files at file level — common types like jpg, png, docx; not code-level). It MUST NOT traverse beyond the specified directory root.

#### Scenario: Happy path

- GIVEN a directory with subfolders and files
- WHEN a client calls `scan_directory` with that path
- THEN the system returns a JSON tree of the hierarchy rooted at the specified path

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

`search_by_type` MUST accept `path` and a file type filter, and MUST return a flat list of matching files under the specified directory. It MUST NOT search outside the given path.

#### Scenario: Happy path

- GIVEN a directory with jpg and png files
- WHEN a client calls `search_by_type` with path and type `jpg`
- THEN the system returns only the jpg files as a flat list

#### Scenario: No matches

- GIVEN a directory with no files of the requested type
- WHEN `search_by_type` is called
- THEN the system returns an empty list

### Requirement: get_file_metadata returns file details

`get_file_metadata` MUST accept a `path` to a file and MUST return size, dates, and permissions for that file.

#### Scenario: Happy path

- GIVEN an existing readable file
- WHEN a client calls `get_file_metadata` with its path
- THEN the system returns size, modification dates, and permissions

#### Scenario: Path is a directory

- GIVEN a `path` pointing to a directory instead of a file
- WHEN `get_file_metadata` resolves the path
- THEN the system returns an error explaining a file path is required

### Requirement: Unicode filenames supported

All tools MUST handle Unicode filenames without data loss or crashes.

#### Scenario: Unicode filenames in results

- GIVEN a directory containing files with Unicode names
- WHEN any tool returns results for that directory
- THEN the returned names match the on-disk names exactly