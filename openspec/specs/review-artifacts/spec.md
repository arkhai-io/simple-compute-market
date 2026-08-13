# Review Artifacts Specification

## Purpose

Define the repository contract for portable, scoped dependency artifacts used to reproduce Python review and validation environments without requiring network access or a successful test run on the producing host.

## Requirements

### Requirement: Review dependency packaging is independent of test success
The review-wheelhouse workflow MUST resolve and package the selected projects' locked development dependencies without running their test suites. A failing test suite MUST NOT prevent creation of the dependency artifact.

#### Scenario: A selected project has a failing test
- **WHEN** a contributor invokes `make review-wheelhouse` for that project
- **THEN** dependency collection and archive creation proceed without invoking the project's test targets

### Requirement: Review scope is explicit
The workflow MUST package one or more repository-relative Python projects selected through `REVIEW_PROJECTS`, and MUST reject an empty selection or a selected project that lacks both `pyproject.toml` and `uv.lock`.

#### Scenario: Multiple affected projects are selected
- **WHEN** `REVIEW_PROJECTS` names several valid project directories
- **THEN** the archive records each selected path and includes a normalized manifest and lockfile copy for each one

### Requirement: Repository wheels are rebuilt from a clean distribution directory
The `review-wheelhouse` make target MUST run the repository's clean distribution build before dependency collection so the bundle contains current repository-owned wheels without accumulated historical versions.

#### Scenario: Stale wheels exist in `.dist`
- **WHEN** the review artifact is built
- **THEN** `.dist` is cleaned and rebuilt before its contents are copied into the artifact

### Requirement: One explicit Python interpreter ABI
A review artifact MUST target one explicit Python version selected by `REVIEW_PYTHON`. Dependency collection and helper Python execution MUST use that version, and the archive MUST record it for consumers.

#### Scenario: CPython 3.13 is selected
- **WHEN** `REVIEW_PYTHON=3.13` is supplied
- **THEN** compiled third-party artifacts and recreated environments target CPython 3.13 rather than the producer host's incidental default interpreter

### Requirement: Source checkout metadata remains unchanged
The workflow MUST NOT modify source `pyproject.toml` or `uv.lock` files. Any removal or rewriting of local source overrides MUST occur only in copied manifests and lockfiles inside the review artifact.

#### Scenario: A project uses repository-local editable dependencies
- **WHEN** its review metadata is packaged
- **THEN** the checkout retains its original editable source declarations while the copied metadata is normalized for portable wheel-backed resolution

### Requirement: Copied dependency metadata is portable
Copied lockfiles and manifests MUST NOT retain absolute `.dist` paths or repository-local editable/directory references for dependency packages. Repository-owned dependency records MUST resolve to matching wheels in the bundled wheelhouse using archive-relative paths. The selected project itself MAY remain represented as the local project because offline environment recreation does not install it.

#### Scenario: A compute service lockfile references a sibling adapter directory
- **WHEN** the lockfile copy is normalized
- **THEN** the sibling adapter package resolves from its exact bundled wheel and no path outside the extracted archive is required

### Requirement: Dependency cache is populated from clean environments
For every selected project, dependency collection MUST use an isolated temporary environment rather than an existing project `.venv`, so already-installed packages cannot hide missing cache artifacts.

#### Scenario: The producer already has a populated project environment
- **WHEN** the review artifact is built
- **THEN** all locked development dependencies required for clean recreation are still collected into the bundled cache

### Requirement: Offline recreation installs dependencies only
The archive instructions MUST recreate a selected project's dependency environment with `UV_OFFLINE=1`, the bundled cache, the recorded Python version, `--frozen`, the development dependency group, and `--no-install-project`. The project source and tests are supplied by the matching repository checkout rather than duplicated into the dependency artifact.

#### Scenario: A reviewer extracts the artifact beside a matching checkout
- **WHEN** the reviewer follows the documented offline command
- **THEN** the selected project's dependencies are installed without network access or an attempt to build the manifest-only project copy

### Requirement: Archive format preserves cache link structure
The review artifact MUST use a tar-based archive format that preserves the uv cache's link structure sufficiently to avoid storing equivalent package contents as independent ZIP copies.

#### Scenario: uv indexes a cached wheel through linked cache entries
- **WHEN** the review artifact is archived and extracted
- **THEN** the package contents are not duplicated merely because the archive format discarded the cache's links

### Requirement: Artifact contents are self-describing
The archive MUST contain the repository wheelhouse, the external uv cache, normalized project metadata, the selected-project list, and instructions identifying the Python version and offline recreation command.

#### Scenario: A reviewer receives only the artifact
- **WHEN** they inspect its root contents
- **THEN** they can determine which projects and interpreter it supports and how to pair it with the matching source checkout

## Evidence

- Packaging entry point: root `Makefile` target `review-wheelhouse`.
- Portable bundle implementation: `scripts/package-review-wheelhouse.sh`.
- Repository wheel build contract: root `dist-clean` and `dist` targets.
