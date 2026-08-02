## 1. Governance and compatibility entry gate

- [x] 1.1 Read `AGENTS.md`, `docs/development/ARCHITECTURE.md`,
  `openspec/README.md`, current `test-compatibility` documents, current
  quickstarts, and relevant active/archived changes.
- [x] 1.2 Audit the raw 20-path historical envelope against current `dev` and
  classify every path without merging or cherry-picking the old branch.
- [x] 1.3 Audit current reservation, fulfillment, result, executor, teardown,
  and typed-scarcity behavior and classify harness versus private-runner work.
- [x] 1.4 Audit workflow triggers, dependencies, toolchain assumptions, and the
  locked issue-discovery baseline; approve no dependency upgrade.
- [x] 1.5 Freeze this proposal, design, and delta specification before public
  behavior implementation.
- [x] 1.6 Validate this OpenSpec change strictly and commit it independently.

## 2. VM/G1 scenario contract

- [x] 2.1 Add `capacity-scenario.schema.json` with VM/G1 invariants, explicit
  O/B/S/H/L/R/G counts, ownership and arrival modes, quickstart references,
  expected outcomes, retry prohibition, and cleanup requirements.
- [x] 2.2 Add exact fixtures for Q0, Reference B1, and Q1-Q8; keep historical
  G2 fixtures absent.
- [x] 2.3 Implement pure validation and deterministic canonical scenario
  hashing in `capacity.py`.
- [x] 2.4 Test the exact finite table, Q5 serialized reuse, common barriers,
  substantive ownership from Q1 onward, global G1 fencing, and rejection of
  G2/non-VM/adaptive rows.

## 3. Current lifecycle and finding contract

- [x] 3.1 Add `capacity-finding.schema.json` and a sanitized example using only
  public branch/SHA/scenario/run metadata and correlation assertions.
- [x] 3.2 Evaluate opaque reservation/fulfillment correlation, status/result,
  executor assertion, teardown, cancellation, cleanup, and exact expected
  scarcity without embedding product/provider internals.
- [x] 3.3 Implement stable sanitized fingerprinting that excludes occurrence
  metadata, private identity, credentials, paths, and raw logs.
- [x] 3.4 Test success, exact scarcity suppression, other-409 classification,
  product/harness/environment classification, cleanup failure retention, and
  negative privacy scans.

## 4. Issue and guarded fix-candidate planning

- [x] 4.1 Implement deterministic create, no-op, update, and reopen issue
  packets using stable scope and occurrence markers.
- [x] 4.2 Gate publication planning on cleanup and suppress expected scarcity.
- [x] 4.3 Implement harness-owned draft-fix proposal validation with exact
  `fix/<fingerprint>` head, replacement-branch base, candidate fallback, and
  never-auto-merge semantics.
- [x] 4.4 Test every decision with fake repositories or dry-run GitHub calls;
  no authenticated mutation test is permitted.

## 5. Portable CLI and runner behavior

- [x] 5.1 Add deterministic validate, hash, evaluate, finding, issue-plan,
  cancel, and cleanup JSON/exit-code surfaces without a capacity execution
  command.
- [x] 5.2 Represent public repository/branch/SHA, scenario, run, timeout,
  adapter, cancellation, and cleanup inputs explicitly.
- [x] 5.3 Reject live market, wallet, cloud, host, provisioning, and GitHub
  mutation adapters before subprocess or network invocation.
- [x] 5.4 Correct only current repository paths/prerequisites in `local.yaml`
  and `test_bootstrap.py`; preserve ordinary issue-discovery phases.
- [x] 5.5 Test CLI help, valid and invalid inputs, stable JSON, dry-run output,
  cancellation, cleanup, and fail-closed behavior.

## 6. Permanent documentation promotion

- [x] 6.1 Promote verified observable behavior to
  `openspec/specs/test-compatibility/spec.md`.
- [x] 6.2 Promote the public/private boundary, evidence model, stable identity,
  and future on-demand seam to
  `openspec/specs/test-compatibility/architecture.md`.
- [x] 6.3 Update `docs/development/ISSUE_DISCOVERY.md` and
  `tools/issue-discovery/README.md` with current commands, exact claim limits,
  mocked GitHub behavior, and the no-live boundary.
- [x] 6.4 Update the design-promotion record if implementation proves a
  material decision not already mapped; do not add production references to
  this change directory.

## 7. Public completion checks

- [x] 7.1 Run strict OpenSpec validation and the complete locked
  issue-discovery suite.
- [x] 7.2 Run schema/example, CLI, mocked issue/fix, privacy, path-manifest,
  G2/non-VM rejection, and excluded-subsystem scans.
- [x] 7.3 Confirm no product, E2E, workflow, dependency, lockfile, cloud-runner,
  qualification, or publication-v2 path changed.
- [x] 7.4 Record exact commands/results and the existing CI limitation that
  `tools/issue-discovery` is excluded from the default Tests workflow.
- [x] 7.5 Pin the clean pushed public SHA for private compatibility testing;
  do not open a pull request or run a capacity stage.

## Design Promotion Record

| Accepted decision | Permanent location | Status |
| --- | --- | --- |
| finite VM/G1 matrix, role ownership, lifecycle, scarcity, cleanup, and findings | `openspec/specs/test-compatibility/spec.md#requirement-agent-driven-vm-capacity-contracts-are-finite-and-non-executing` | promoted and verified |
| public/private boundary, evidence layering, stable identity, and runner seam | `openspec/specs/test-compatibility/architecture.md#agent-driven-capacity-preparation-boundary` | promoted and verified |
| commands, result claims, GitHub dry-run, and no-live boundary | `docs/development/ISSUE_DISCOVERY.md#capacity-preparation-interfaces`; `tools/issue-discovery/README.md#capacity-preparation-api` | promoted and verified |

## Public Validation Record

All commands below were run against the replacement branch based on the
recorded `origin/dev` authority. The guarded-pushed commit containing this
record is the public compatibility pin; its exact SHA and push receipt belong
in the private operator handoff so that public documentation does not acquire
private orchestration identifiers.

- `npx --yes @fission-ai/openspec@1.7.0 validate
  reconcile-agent-driven-vm-harness --strict` reported that the active change
  is valid.
- `npx --yes @fission-ai/openspec@1.7.0 validate test-compatibility
  --type spec --strict` reported that the permanent specification is valid.
- From `tools/issue-discovery`, `uv --no-config run pytest -q` passed all 273
  locked tests.
- Focused schema/example and VM/G1 rejection nodes passed 6 tests; the focused
  `finding_privacy_scan` selection passed 45 tests; the `capacity` selections
  in `test_cli.py`, `test_runner.py`, and `test_issues.py` passed 6, 47, and 25
  tests respectively.
- Running `./scripts/issue-discovery capacity validate` over every
  `tools/issue-discovery/config/capacity/*.json` fixture validated exactly 10
  scenarios. Running `capacity finding` over the tracked
  sanitized example returned stable JSON with `status: ok` and exit 0.
- `git diff --name-only origin/dev...HEAD` produced exactly the 33 approved
  public paths: the manifest comparison found zero missing and zero extra
  paths. `git diff --check` passed.
- A `jq` assertion over every capacity fixture confirmed `deal_type == "vm"`,
  `gpu_assignment == "whole-device-passthrough"`, and exactly one physical
  GPU. No G2 fixture exists.
- The changed-path exclusion scan found no product, `e2e-tests`, workflow,
  dependency, lockfile, cloud-runner, Tekton, `g1-v2`, finding-v2,
  qualification-framework, or publication-v2 path. The approved Reference B1
  fixture is a finite scenario, not a qualification profile or registry.
- `.github/workflows/tests.yml` remains unchanged and explicitly documents
  that `tools/issue-discovery` is excluded from the default Tests workflow
  because its bootstrap tests inspect the host system.

No capacity stage, agent session, live adapter, GitHub mutation, cloud or host
probe, wallet action, provisioning action, VM, or GPU workload was run while
producing this record. No pull request was opened.
