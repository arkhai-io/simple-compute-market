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

## VM Capacity Preparation

Capacity preparation reuses this harness rather than creating another issue
tracker. Public scenario semantics live under `config/capacity/` and validate
against `schemas/capacity-scenario.schema.json`:

```bash
./scripts/issue-discovery capacity scenario-validate \
  tools/issue-discovery/config/capacity/b2-g1-contention.json
```

The scenarios are VM-only, require real KVM/Ansible and whole-device GPU
passthrough, disable request retries, and distinguish one-GPU contention from
two-GPU simultaneous fulfillment. Buyer scaling remains first; the two
`b2-s2-*` scenarios then repeat contention and fulfillment with two independent
seller roles and one listing per seller. `seller_distribution` freezes the
listing count owned by each seller. Replace a listing fingerprint only after
the private topology is frozen.

The private orchestrator emits sanitized findings conforming to
`schemas/capacity-finding.schema.json`. Ingesting one creates or refreshes the
normal issue candidate packet and appends an immutable lifecycle event:

```bash
./scripts/issue-discovery capacity finding-ingest <run-dir> <finding.json>
./scripts/issue-discovery issue list <run-dir>
./scripts/issue-discovery issue show <run-dir> <fingerprint>
./scripts/issue-discovery issue create <run-dir> <fingerprint> --dry-run
```

For a sanitized `private-infra` finding, keep `--repo-root` pointed at SCM so
schema and redaction policy remain public and auditable, but name the exact
private checkout used for branch and GitHub authority:

```bash
./scripts/issue-discovery issue create <run-dir> <fingerprint> \
  --destination-repo-root /absolute/path/to/compute-market-internal-infra \
  --dry-run
```

Publication verifies both the authorized working branch and the destination
checkout's `origin` slug. A correct branch name in the wrong repository fails
closed.

The capacity defect fingerprint is stable: the harness preserves the sanitized
producer-supplied value instead of adding a branch or scenario suffix. Duplicate
matching is still occurrence-scoped. The harness searches only the authorized
destination repository, then requires the issue body to contain the exact
working-branch and scenario marker. Live publication fails unless the checkout
is on that working branch. An exact open issue receives a new occurrence; an
exact closed issue is reopened; another repository, branch, or scenario does
not deduplicate the finding.

Fix automation is proposal-only until a validated fix exists. The proposal
must use an issue-specific child head and the authorized working branch as base:

```bash
./scripts/issue-discovery issue propose-fix <run-dir> <fingerprint> \
  --head-branch fix/<fingerprint>
./scripts/issue-discovery issue transition <run-dir> <fingerprint> \
  --state fixed_unverified --detail "Fix merged to the working branch"
./scripts/issue-discovery issue transition <run-dir> <fingerprint> \
  --state verified --detail "Passed in a new qualification series"
```

The packet never authorizes a PR to `dev` or `main` and never auto-merges.
The lifecycle refuses to move from `fixed_unverified` directly to `closed`;
verification in a new series is required first.

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
