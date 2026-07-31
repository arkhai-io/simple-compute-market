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

## VM Capacity Contracts

Capacity preparation reuses this harness. Public authority is divided into:

- `config/capacity/scenarios/`: mode-neutral schema-v2 VM/G1 shapes;
- `config/capacity/profiles/g1-v2.json`: the exact qualification and measured
  progression;
- `config/capacity/profile-stages/b1-s1-g1-mock.json`: the standalone
  preparation-only mock;
- closed schemas for role/action evidence, independent outcomes, reuse,
  frontiers, and finding-v2 occurrences.

Every current scenario is VM-only, requires real KVM/Ansible whole-device GPU
passthrough, and disables request retries. G1 means one independently
assignable physical GPU even when multiple sellers advertise distinct
listings. The current profile rejects G2 and runs buyer qualification before
the two-seller row.

All authority-bearing lookups use an exact Git commit. Discover and then pin
the public semantics:

```bash
SCM_REF="$(git rev-parse HEAD)"
PROFILE=tools/issue-discovery/config/capacity/profiles/g1-v2.json

./scripts/issue-discovery capacity profile-sha256 \
  "$PROFILE" --scm-ref "$SCM_REF"
./scripts/issue-discovery capacity profile-validate \
  "$PROFILE" --scm-ref "$SCM_REF" \
  --expected-sha256 <profile-canonical-sha256> \
  --expected-raw-sha256 <profile-raw-sha256>

./scripts/issue-discovery capacity profile-stage-sha256 \
  b2-s1-g1-qualification --scm-ref "$SCM_REF"
```

Profile and stage operations emit one deterministic JSON object containing the
complete validated public semantics, pinned ref/path, and applicable
canonical/raw digests. Stage output includes its resolved scenario or null.
Private infrastructure consumes this CLI boundary instead of importing this
package or reproducing its policy.

The capacity command family also validates and canonical-hashes scenarios,
evaluation/reference policies, role plans/receipts, oracle authority,
concurrency policy, frozen actions/results, actor sets, mock capture, capacity
results, serialized reuse, buyer frontiers, and findings:

```bash
./scripts/issue-discovery capacity --help
./scripts/issue-discovery capacity <subcommand> --help
```

`execution_boundary` and `actor_trigger` are independent. A readiness probe,
mock rehearsal, deterministic real reference, agent-triggered qualification,
and agent-triggered measured row cannot be relabeled as one another. Public
`action-capture` is mock-only. Private infrastructure authenticates real Codex
processes, credentials, runtime mappings, native evidence, and live mutations.

## Immutable Capacity Findings

A finding-v2 producer supplies an occurrence ID and one fully reconstructable
validated capacity result. SCM derives the stable
`capacity-<sha256>` fingerprint from closed defect semantics; it does not trust
a producer fingerprint or add run/ref/evidence data to defect identity.

Validation binds exact scenario/profile/result authority, durable request
correlations, branch and first-parent reconciliation authority, complete
cleanup, one explicit evidence root, and bounded raw evidence bytes. Public and
private classifications map only to their designated repository and working
branch. Representation-aware privacy checks reject prohibited private field
names and portable patterns, credential signatures, path escape, symlinks,
mutation, JSON/YAML/CommonMark/Unicode encoding evasions, and harness-managed
evidence. Private infrastructure separately rejects its runtime exact private
values before export; public SCM does not claim that environment-specific
denylist.

The ingest command requires the exact context needed to reconstruct the result:

```bash
./scripts/issue-discovery capacity finding-ingest \
  <run-dir> <finding.json> <result-context.json> \
  --evaluation-policy <evaluation-policy.json> \
  --expected-scm-ref <40-character-scm-ref> \
  --destination-repo-root <exact-destination-worktree>
```

Use `finding-ingest --help` for predecessor, reuse, frontier, and ordered
seller-progression dependencies. Ingest uses `<run-dir>` as the explicit
evidence root and immutable owner-only occurrence store. It writes 0700
directories and 0600 files through descriptor-rooted authority, serializes
compliant writers with two locks, keeps create-once source/index/body records
and append-only ledgers, recovers only authenticated crash residue, and
generates a local candidate from one final immutable replay snapshot.

This path is preparation-only. It does not call GitHub or perform market,
wallet, cloud, VM, KVM, Ansible, GPU, or cleanup actions. `issue list` and
`issue show` can inspect a capacity-v2 candidate, but legacy `issue create`,
`issue transition`, and `issue propose-fix` reject it before writes or
subprocesses. Credentialed issue/update/reopen and fix-PR behavior belongs to
the separate guarded-publication capability.

Schema-v1 capacity artifacts remain attributable only through the exact
historical Git commit that defined them. Current validators do not reinterpret
v1 as v2.

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
