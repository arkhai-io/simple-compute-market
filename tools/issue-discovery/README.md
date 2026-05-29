# Issue Discovery Tool

This package implements the repository-level issue-discovery harness. It is
not meant to be invoked directly from this directory during normal use; the
stable entrypoint from the repo root is:

```bash
./scripts/issue-discovery --help
```

The tool is YAML-driven. It is intended to run existing validation commands,
collect artifacts, and generate issue-ready summaries without silently fixing
runtime state.

It complements the existing test infrastructure rather than replacing it. Unit,
integration, smoke, and e2e tests still own behavioral correctness. This harness
orchestrates those tests as part of a larger local or clean-host workflow,
records the surrounding environment, makes any workaround explicit, and produces
issue candidates when the workflow fails.

## How It Fits Together

- `scripts/issue-discovery` runs this package through `uv` and passes the repo
  root explicitly.
- `config/` contains phase definitions, profiles, explicit workarounds,
  collectors, redaction rules, and clean-room sequences.
- `schemas/` validates the YAML config shape.
- `src/issue_discovery/` contains the CLI, runner, artifact, redaction,
  clean-room, and issue candidate code.
- `tests/` covers config loading, runner behavior, redaction, candidate
  generation, issue filing guards, bootstrap integration, and clean-room
  rendering.

## Docs

- `../README.md` explains the repo tooling namespace and the available
  issue-discovery modes.
- `../../docs/development/ISSUE_DISCOVERY.md` is the operator workflow for strict runs,
  continuations, profiles, clean-room runs, artifacts, and issue filing.
- `../../docs/development/VALIDATION_RUNBOOK.md` is the manual validation runbook for local
  mock, clean Ubuntu/Multipass, and GCP/KVM proof paths.

## Development

Run tests from this package directory:

```bash
uv run pytest
```

Generated outputs belong under `.scm-local/` at the repo root and should not be
committed.
