# Issue Discovery Tool

This package implements the repository-level issue-discovery harness. It is
not meant to be invoked directly from this directory during normal use; the
stable entrypoint from the repo root is:

```bash
./scripts/issue-discovery --help
```

The ordinary discovery phase workflows are YAML-driven. Capacity preparation
uses bounded JSON scenarios, results, findings, issue snapshots, proposals, and
receipts. The tool runs existing validation commands, collects artifacts, and
generates issue-ready summaries without silently fixing runtime state.

It complements the existing test infrastructure rather than replacing it. Unit,
integration, smoke, and e2e tests still own behavioral correctness. This harness
orchestrates those tests as part of a larger local or clean-host workflow,
records the surrounding environment, makes any workaround explicit, and produces
issue candidates when the workflow fails.

## How It Fits Together

- `scripts/issue-discovery` runs this package through `uv` and passes the repo
  root explicitly.
- `config/` contains phase definitions, profiles, explicit workarounds,
  collectors, redaction rules, clean-room sequences, and finite capacity
  fixtures.
- `schemas/` validates YAML configuration plus persisted capacity scenario and
  finding JSON documents.
- `src/issue_discovery/` contains the CLI, runner, artifact, redaction,
  clean-room, and issue candidate code.
- `src/issue_discovery/capacity.py` owns finite VM/G1 scenario, sanitized
  result/finding, privacy, hash, and lifecycle validation. Capacity planning in
  `issues.py` and `runner.py` remains deterministic and non-executing.
- `tests/` covers config loading, runner behavior, redaction, candidate
  generation, issue filing guards, capacity contracts/planning, bootstrap
  integration, and clean-room rendering.

## Capacity Preparation API

The capacity API has exactly seven commands:

```text
validate
hash
evaluate
finding
issue-plan
cancel
cleanup
```

There is no capacity `run` or `execute` command. The API validates and plans
the finite VM/G1 capacity contract, whose Q1-Q8 rows assign substantive agent
ownership; Q0 and Reference B1 are not agent-driven load. It does not launch
agents, perform role quickstarts, access market/wallet/cloud/host/provisioning
systems, mutate GitHub, or exercise KVM, Ansible, VMs, or GPUs. A passing
command is contract evidence, not execution or system-capacity evidence.

Scenario and finding documents have persisted JSON schemas. Sanitized capacity
results are an internal CLI boundary validated by `capacity.py`, not a third
persisted schema. The capacity methods write no run artifacts and emit one
stable JSON envelope on stdout after argument dispatch.

`evaluate`, `finding`, `issue-plan`, `cancel`, and `cleanup` require explicit
public repository, canonical non-default branch, 40-character SHA, run ID,
timeout, and at least one adapter. The adapter set is closed:

- kinds: `market`, `wallet`, `cloud`, `host`, `provisioning`, and
  `github-mutation`;
- modes: `mock`, `fake`, and `dry-run` only.

Invalid or live adapter selections fail before input-file or external access.
Exit `0` means a successful validation or planning dispatch, including
suppression or withholding; `1` means findings or negative
cancellation/cleanup evidence; `2` means invalid input/context/contract; and
`3` means invalid adapter selection. Ordinary argument-parser errors also use
exit `2` before a JSON handler is dispatched.

`issue-plan` validates the supplied scenario and result, re-evaluates the
result, and derives all findings. It reads a caller-supplied issue snapshot only
when an eligible finding needs publication planning; optional fix proposal and
fingerprint inputs must be paired. It never invokes `gh` or queries GitHub.
Its decisions and plans cover no-action, create, update, reopen, no-op,
withhold, and suppression; emitted operation packets and guarded draft-fix
argument arrays are inert candidate data.

In global dry-run mode, `cancel` and `cleanup` emit deterministic idempotency
keys. Outside dry-run mode they require and validate a sanitized receipt
produced by an external runner and bound to the exact public ref, scenario,
run, adapters, operation, and termination. They never perform the represented
operation and always report `executed: false`.

See [Issue Discovery](../../docs/development/ISSUE_DISCOVERY.md#capacity-preparation-interfaces)
for complete commands, receipt semantics, privacy rules, and claim limits.

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
uv --no-config run pytest -q
```

The default repository Tests workflow excludes this package, so this locked
suite must be run explicitly for issue-discovery changes.

Generated outputs belong under `.scm-local/` at the repo root and should not be
committed.
