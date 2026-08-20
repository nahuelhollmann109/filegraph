# Duplicate Detection Specification

## Purpose

Exposes a `find_duplicates` MCP tool that locates groups of files with identical content by hashing. A two-pass strategy (size prefilter, then content hash) MUST keep the scan cheap on large directories.

## Requirements

### Requirement: find_duplicates returns duplicate groups

`find_duplicates` MUST accept a required `path` parameter and MUST return a list of duplicate groups. Each group MUST contain `hash` (the digest), `size` (bytes), and `files` (list of absolute paths with identical content). Files with unique content MUST NOT appear in any group.

#### Scenario: Happy path

- GIVEN a directory with two identical files and one unique file
- WHEN `find_duplicates` runs
- THEN the result contains one group with both identical file paths

#### Scenario: No duplicates

- GIVEN a directory where all files have unique content
- WHEN `find_duplicates` runs
- THEN the result is an empty list

#### Scenario: Nonexistent path

- GIVEN a `path` that does not exist
- WHEN `find_duplicates` runs
- THEN the tool returns an error and performs no scan

### Requirement: Two-pass hashing strategy

The system MUST group candidate files by size first (pass one) and MUST hash only groups containing two or more files (pass two). Files in a size group of one MUST NOT be hashed.

#### Scenario: Size prefilter skips singletons

- GIVEN a directory where most files have unique sizes
- WHEN `find_duplicates` runs
- THEN only same-size groups are content-hashed
- AND no hash is computed for unique-size files

#### Scenario: Same size, different content

- GIVEN two files of equal size with different content
- WHEN `find_duplicates` runs
- THEN both are hashed and NOT reported as duplicates

### Requirement: hash_algo parameter

`find_duplicates` MUST accept an optional `hash_algo` parameter. Supported values MUST be `sha256` (default) and `md5`. The system MUST reject any other value with an error.

#### Scenario: md5 selected

- GIVEN a caller passes `hash_algo="md5"`
- WHEN `find_duplicates` runs
- THEN returned groups use md5 digests

#### Scenario: Invalid algorithm

- GIVEN a caller passes `hash_algo="crc32"`
- WHEN the tool validates the request
- THEN an error is returned and no scan runs

### Requirement: min_size filter

`find_duplicates` MUST accept an optional `min_size` integer parameter (default `0`). Files smaller than `min_size` bytes MUST be ignored.

#### Scenario: Small files ignored

- GIVEN a caller passes `min_size=1024` and files of 100 bytes
- WHEN `find_duplicates` runs
- THEN the small files are neither considered nor reported

### Requirement: Unreadable files and symlinks

Files that cannot be read or stat'd MUST be skipped without failing the scan, and the system MUST NOT follow symlinks.

#### Scenario: Unreadable file skipped

- GIVEN a directory with a permission-denied file among duplicates
- WHEN `find_duplicates` runs
- THEN the scan completes and the unreadable file is omitted

#### Scenario: Symlink not followed

- GIVEN a symlink pointing to a file outside the scanned directory
- WHEN `find_duplicates` runs
- THEN the symlink's target content is not hashed
