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

- [ ] 6.1 Promote verified observable behavior to
  `openspec/specs/test-compatibility/spec.md`.
- [ ] 6.2 Promote the public/private boundary, evidence model, stable identity,
  and future on-demand seam to
  `openspec/specs/test-compatibility/architecture.md`.
- [ ] 6.3 Update `docs/development/ISSUE_DISCOVERY.md` and
  `tools/issue-discovery/README.md` with current commands, exact claim limits,
  mocked GitHub behavior, and the no-live boundary.
- [ ] 6.4 Update the design-promotion record if implementation proves a
  material decision not already mapped; do not add production references to
  this change directory.

## 7. Public completion checks

- [ ] 7.1 Run strict OpenSpec validation and the complete locked
  issue-discovery suite.
- [ ] 7.2 Run schema/example, CLI, mocked issue/fix, privacy, path-manifest,
  G2/non-VM rejection, and excluded-subsystem scans.
- [ ] 7.3 Confirm no product, E2E, workflow, dependency, lockfile, cloud-runner,
  qualification, or publication-v2 path changed.
- [ ] 7.4 Record exact commands/results and the existing CI limitation that
  `tools/issue-discovery` is excluded from the default Tests workflow.
- [ ] 7.5 Pin the clean pushed public SHA for private compatibility testing;
  do not open a pull request or run a capacity stage.

## Design Promotion Record

| Accepted decision | Permanent location | Status |
| --- | --- | --- |
| finite VM/G1 matrix, role ownership, lifecycle, scarcity, cleanup, and findings | `openspec/specs/test-compatibility/spec.md` | pending verification |
| public/private boundary, evidence layering, stable identity, and runner seam | `openspec/specs/test-compatibility/architecture.md` | pending verification |
| commands, result claims, GitHub dry-run, and no-live boundary | `docs/development/ISSUE_DISCOVERY.md`; `tools/issue-discovery/README.md` | pending verification |
