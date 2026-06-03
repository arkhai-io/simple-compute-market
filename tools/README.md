# Repository Tools

This directory contains repo-owned developer and validation tools that are
larger than a shell wrapper but are not part of the market runtime services.

The main purpose of this namespace is to keep operational tooling versioned
with the code it validates. These tools encode repeatable workflows such as
local issue discovery, clean-machine validation, artifact collection, and issue
packet generation, so contributors can reproduce failures without relying on a
private runbook or an ad hoc shell history.

This tooling does not replace the existing unit, integration, smoke, or e2e
tests. Those tests answer whether a specific code path behaves correctly under
the environment they were given. The tools here answer a broader operational
question: what happens when a contributor or clean host tries to build, start,
validate, diagnose, and file issues for the whole repo workflow? They orchestrate
the existing tests, preserve environment and command evidence, make workarounds
explicit, and turn failures into reviewable issue packets.

At a high level, tools in this directory are invoked through thin wrappers in
`scripts/`. The wrapper establishes the repository root and runtime environment,
then hands off to the implementation package under `tools/`. Tool packages own
their configs, schemas, tests, and internal modules. User-facing workflow docs
live in `docs/`, while generated outputs stay under ignored `.scm-local/`
directories.

Use the stable entrypoints in `scripts/` from the repository root. Files under
`tools/` are implementation packages, configs, schemas, and tests for those
entrypoints.

## Current Tools

### `issue-discovery/`

YAML-driven harness for finding local and clean-machine failures, collecting
artifacts, and preparing issue candidates without silently fixing runtime state.

Stable entrypoint:

```bash
./scripts/issue-discovery --help
```

Modes:

- `strict` runs the configured validation path without applying hidden fixes.
  It is the baseline answer to "what fails on this repo as-is?"
- `continue --with <workaround>` resumes after an explicit named workaround
  from `config/workarounds.yaml`. Use it to move past a known blocker while
  preserving evidence that later results depend on that workaround.
- `profile <name>` runs a narrower diagnostic profile from
  `config/profiles.yaml`, such as a targeted reproduction for a known failure
  class.
- `clean-room plan|script <sequence>` renders a YAML-defined clean-machine
  sequence from `config/clean-room/`. The Multipass wrapper uses this to run
  strict mode first, then explicit continuations, inside a disposable VM.
- `issue list|show|create` inspects generated issue candidates and can create a
  GitHub issue after redaction and duplicate checks.

Primary docs:

- `docs/development/ISSUE_DISCOVERY.md` - operator workflow for strict runs,
  continuations, clean-room runs, artifacts, and issue filing.
- `docs/development/VALIDATION_RUNBOOK.md` - manual validation runbook covering local mock,
  clean Ubuntu/Multipass, and GCP/KVM proof paths.
- `tools/issue-discovery/README.md` - package-level note for the Python tool.

Related wrappers:

- `scripts/issue-discovery` - repo-root wrapper that runs the Python CLI.
- `scripts/bootstrap-clean-host-ubuntu.sh` - prepares a fresh Ubuntu host and
  runs the configured validation command or clean-room sequence.
- `scripts/clean-room/multipass-run.sh` - creates a disposable Multipass VM,
  transfers the current branch, runs the clean-host bootstrap, fetches
  artifacts, and tears down the VM by default.

## Issue Discovery Layout

- `src/issue_discovery/` - CLI, phase runner, artifact collection, redaction,
  clean-room sequence rendering, and issue candidate logic.
- `config/phases/` - YAML phase definitions for local strict runs, targeted
  reproductions, and bootstrap checks.
- `config/clean-room/` - ordered clean-room sequences that compose strict and
  continuation runs.
- `config/profiles.yaml` - named profiles that select phase files and
  environment.
- `config/workarounds.yaml` - explicit continuation workarounds and their
  resume points.
- `config/collectors.yaml` - artifact collectors run after failures or at
  configured points.
- `config/redactions.yaml` - redaction rules applied before issue packets are
  shown or filed.
- `schemas/` - JSON schemas for the YAML config files.
- `tests/` - unit tests for config loading, runner behavior, artifacts,
  redaction, issue candidate generation, bootstrap integration, and clean-room
  rendering.

Generated run output belongs under `.scm-local/` and must not be committed.
Typical locations are:

- `.scm-local/issue-discovery/runs/<run-id>/`
- `.scm-local/clean-room-runs/<vm-name>/`
- `.scm-local/clean-room/`

## Development

Run the issue-discovery test suite from its package directory:

```bash
cd tools/issue-discovery
uv run pytest
```

Run the CLI from the repo root through the wrapper:

```bash
./scripts/issue-discovery --dry-run strict
./scripts/issue-discovery issue list .scm-local/issue-discovery/runs/<run-id>
./scripts/issue-discovery clean-room plan local-vm
```

When changing tool behavior, update tests first or alongside the change. Keep
tool commits separate from generated artifacts and unrelated service lockfiles.

## Adding More Tools

Prefer this structure for new repo-owned tools:

```text
tools/<tool-name>/
  README.md
  pyproject.toml
  src/<package_name>/
  tests/
```

Add a thin wrapper under `scripts/` when the tool is intended to be run from the
repo root. Put user-facing workflow docs under `docs/`, and keep implementation
details in the tool package README.
