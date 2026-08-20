# Pattern Analysis Specification

## Purpose

Exposes a `find_patterns` MCP tool that detects recurring filename patterns — prefixes, suffixes, numeric sequences, and dates — so agents can spot groups of related files.

## Requirements

### Requirement: find_patterns returns pattern groups

`find_patterns` MUST accept a required `path` parameter and MUST return a list of detected pattern groups. Each group MUST include the pattern `type`, a `pattern` description, and the matching file names.

#### Scenario: Happy path

- GIVEN a directory containing `report_001.pdf` through `report_005.pdf`
- WHEN `find_patterns` runs
- THEN a sequence group containing those files is returned

#### Scenario: No patterns

- GIVEN a directory with unrelated file names
- WHEN `find_patterns` runs
- THEN the result is an empty list

#### Scenario: Nonexistent path

- GIVEN a `path` that does not exist
- WHEN `find_patterns` runs
- THEN an error is returned and no scan runs

### Requirement: Detection strategies

The system MUST be able to detect four pattern types: `prefix` (shared leading text), `suffix` (shared trailing text), `sequence` (numeric increments such as `file_001`…`file_010`), and `date` (date-like tokens such as `2024-01-15`). An optional `strategy` parameter MUST accept `auto` (default), `prefix`, `suffix`, `sequence`, or `date`.

#### Scenario: Explicit strategy restricts detection

- GIVEN a caller passes `strategy="sequence"` and files sharing only a prefix
- WHEN `find_patterns` runs
- THEN no sequence group is returned and other types are not considered

#### Scenario: Auto selects best strategy

- GIVEN files matching both a prefix and a sequence pattern
- WHEN `find_patterns` runs with the default strategy
- THEN the system returns the most specific pattern group(s) without duplication

#### Scenario: Invalid strategy rejected

- GIVEN a caller passes `strategy="hash"`
- WHEN the tool validates the request
- THEN an error is returned

### Requirement: min_group_size parameter

`find_patterns` MUST accept an optional `min_group_size` integer parameter (default `3`). Pattern groups with fewer matching files than `min_group_size` MUST NOT be reported.

#### Scenario: Small group suppressed

- GIVEN a prefix shared by only two files and `min_group_size=3`
- WHEN `find_patterns` runs
- THEN that prefix group is omitted

#### Scenario: Threshold raised

- GIVEN a sequence of four files and `min_group_size=5`
- WHEN `find_patterns` runs
- THEN no sequence group is returned
