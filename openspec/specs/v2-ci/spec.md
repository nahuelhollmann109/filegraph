# CI Pipeline Specification

## Purpose

Defines the GitHub Actions workflow that runs tests and linting for every push and pull request, guarding regressions on supported Python versions.

## Requirements

### Requirement: Workflow triggers

The repository MUST contain `.github/workflows/ci.yml` that runs on `push` to the default branch and on all `pull_request` events.

#### Scenario: Push to main

- GIVEN a commit is pushed to the default branch
- WHEN GitHub evaluates workflow triggers
- THEN the CI workflow runs

#### Scenario: Pull request

- GIVEN a pull request is opened or updated
- WHEN GitHub evaluates workflow triggers
- THEN the CI workflow runs against the PR head

### Requirement: Python matrix

The workflow MUST run the test job on Python 3.12 and SHOULD run it on 3.13. The matrix MUST use `actions/setup-python` and SHOULD pin action versions to a tag or SHA.

#### Scenario: Matrix covers supported versions

- GIVEN the workflow defines a version matrix
- WHEN CI runs
- THEN each listed Python version executes the same test job

### Requirement: Test command

The workflow MUST install the package with `pip install -e ".[dev]"` and MUST run `pytest`. The job MUST fail when any test fails.

#### Scenario: Passing suite

- GIVEN all tests pass
- WHEN the workflow runs `pytest`
- THEN the job completes successfully

#### Scenario: Failing test

- GIVEN a test fails
- WHEN the workflow runs `pytest`
- THEN the job fails and blocks the branch status

### Requirement: Linting

The workflow SHOULD run `ruff check` after tests. If ruff is not installed or configured, the lint step MUST be skipped rather than fail the job.

#### Scenario: Lint runs when configured

- GIVEN ruff is present in dev dependencies
- WHEN the workflow runs
- THEN `ruff check` executes and fails the job on violations

#### Scenario: Lint skipped when unconfigured

- GIVEN ruff is not installed
- WHEN the workflow runs
- THEN the lint step is skipped without failing the job

### Requirement: Dependency caching

The workflow SHOULD cache pip dependencies to speed up repeated runs.

#### Scenario: Cache hit

- GIVEN dependencies were cached in a previous run
- WHEN the workflow installs dependencies
- THEN cached wheels are reused instead of re-downloaded
