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
./scripts/issue-discovery capacity scenario-sha256 \
  tools/issue-discovery/config/capacity/b2-g1-contention.json
```

The scenarios are VM-only, require real KVM/Ansible and whole-device GPU
passthrough, disable request retries, and distinguish one-GPU contention from
two-GPU simultaneous fulfillment. Buyer scaling remains first; the two
`b2-s2-*` scenarios then repeat contention and fulfillment with two independent
seller roles and one listing per seller. `seller_distribution` freezes the
listing count owned by each seller.

These public files own only the portable test contract: VM/provisioning/GPU
mode, buyer and seller role counts, request load, seller distribution, and the
success/scarcity oracle. They intentionally do not contain a runtime listing
fingerprint or listing IDs. The private controller owns those deployment facts,
binds them to the selected public shape, and records the public file's pinned SCM
ref, path, and canonical scenario SHA-256. `scenario-sha256` validates the file
first and writes only the lowercase 64-character digest to stdout. The digest is
SHA-256 over UTF-8 canonical JSON with recursively sorted object keys and compact
separators plus one trailing newline, so formatting and object-key order do not
change scenario identity.

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

Publication verifies the exact `github.com/arkhai-io/<repository>` origin, authorized
working branch, observed commit SHA, and clean worktree. Every `gh issue`
create/list/comment/reopen command also receives an explicit `--repo`; a fork,
`GH_REPO` override, default branch (`dev`/`main`), detached/wrong branch,
advanced commit, or dirty worktree fails closed before GitHub mutation.

The capacity defect fingerprint is stable: the harness preserves the sanitized
producer-supplied value instead of adding a branch or scenario suffix. Duplicate
matching is still occurrence-scoped. Candidate and lifecycle records carry the
exact repository, working branch, observed SHA, scenario id/fingerprint, run,
and stage. Issue bodies carry a stable machine-readable repository/branch/
scenario scope marker plus an exact per-occurrence SHA/run/stage marker. The
harness uses only the stable scope marker for duplicate matching, so a new run
of the same defect updates the exact open issue or reopens the exact closed
issue; another repository, branch, or scenario does not deduplicate it.

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

The packet repeats the exact destination repository, observed SHA, scenario,
and run. Its base is derived only from the authorized working branch; neither
head nor base may be `dev` or `main`. The packet never auto-merges.
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
