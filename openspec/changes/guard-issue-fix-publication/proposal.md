## Why

The reconciled harness can render and sometimes file branch-scoped issues, but
its current publication path can bypass filing readiness, duplicate an
occurrence comment, lose the truth after a partial reopen/comment failure, and
advance lifecycle state when it has created only a proposal packet. It has no
validated action or receipt for opening an authorized draft fix PR, so the
campaign cannot safely prove the full issue-to-fix loop required after cleanup.

## What Changes

- Define frozen portable publication actions that bind the sanitized finding,
  stable fingerprint, immutable `finding_id`, canonical destination, exact
  allowed working/upstream branches and SHAs, scenario scope, reconciliation
  epoch, rendered body hash, and private authorization digest; draft actions
  separately bind PR base/head authority, and finding v1 is a hard historical
  cutoff.
- Preserve the authority split: SCM owns deterministic action selection,
  rendering, schemas, and pre/post validation; private infrastructure owns
  GitHub credentials, distributed generation fencing, cleanup/baseline
  authority, branch push, and credentialed mutation.
- Require branch-scoped issue publication to use `ready_to_file` findings,
  complete pagination across open/closed issues and comments, versioned JSON
  markers, exact clean checkout/ref/ancestry checks, and default branch denial.
  The guarded live path has no force override.
- Make create/update/reopen/no-op behavior idempotent for one exact occurrence,
  and reconcile ambiguous partial outcomes read-only before a retry.
- Define mutation-intent, success, no-op, and `outcome_unknown` receipts with
  an exact owner/mode/type-checked, atomically durable per-step operation
  journal and before/after observations, so interruption is inferred as
  unknown and a comment/reopen partial failure cannot be reported as success or
  blindly retried.
- Keep proposal-only fix packets as a valid fallback and add a separately
  authorized draft-PR action for a reviewed `fix/<fingerprint>[-suffix]` child
  branch already pushed to an exact remote SHA and targeting only the
  applicable working branch; public SCM never creates or pushes that ref.
- Correct lifecycle semantics: proposal packet means `fix_proposed`; actual
  work/branch creation means `fix_in_progress`; draft opening is recorded
  separately; no action auto-closes an issue.
- Require dry-run to execute the same schema, authority, readiness, redaction,
  remote-ref/GitHub observation, deduplication, and action-selection checks as
  live mode, stopping only before external mutation; offline rendering is
  separately labeled preview-only.

## Capabilities

### New Capabilities

- `finding-publication`: Portable, recoverable, branch-scoped issue and draft
  fix-PR publication actions, receipts, lifecycle semantics, and validation.

### Modified Capabilities

None.

## Dependencies and Related Changes

- Implementation is blocked on the final finding-v2 and SCM-owned fingerprint
  contract from `define-agent-driven-vm-capacity-contracts`; planning can
  proceed in parallel, but code must consume the verified final v2 shape.
- Private `compute-market-internal-infra` supplies the current GitHub identity,
  campaign generation, cleanup/baseline proof, single-writer branch mutation,
  and credentialed API calls at one exact public SCM commit.
- An upstream developer fix remains external to campaign credentials and
  returns only through a separately elected inbound merge into the working
  branch.

## Non-Goals

- Do not file a live canary issue or open a live draft PR while implementing
  the public validators; live proof belongs to later qualification.
- Do not store GitHub credentials, campaign-generation secrets, private
  evidence, cloud/host identity, or executor-local paths in public actions or
  receipts.
- Do not let issue/PR publication delay or authorize cleanup.
- Do not open a product-code PR from the harness branch to `dev`, an integration
  PR from the private branch to `main`, or any automatic promotion PR.
- Do not auto-merge a PR, auto-close an issue, use `Fixes`/`Closes`, or create a
  fix branch from an unreviewed diff.
- Do not make SCM's public validation sufficient live authority; credentialed
  mutation remains private and generation-fenced.

## Impact

- New public publication action/receipt/lifecycle schemas and fixtures under
  `tools/issue-discovery`.
- Deterministic issue and draft-PR action selection, occurrence markers,
  complete search, redaction, lifecycle transitions, and post-mutation
  reconciliation in the issue-discovery package.
- Fake-GitHub and local bare-remote tests for branch/base/ref authority,
  create/update/reopen/no-op behavior, partial failures, proposal fallback, and
  draft-only PR behavior.
- No marketplace wire, database, deployment, package dependency, scheduled
  workflow, or default-branch CI change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Frozen publication authority, public/private mutation ownership,
  occurrence-idempotent issue behavior, recoverable receipts, guarded draft PR
  actions, truthful lifecycle, and dry-run parity belong in
  `openspec/specs/finding-publication/spec.md` with threat model and recovery
  rationale in its companion `architecture.md`.
- The capability is added to `openspec/specs/README.md`.
- The repository-wide public-policy/private-execution relationship is linked
  from `docs/development/ARCHITECTURE.md#testing-strategy` without duplicating
  the detailed publication contract.
- Exact operational commands and limitations are promoted to
  `docs/development/ISSUE_DISCOVERY.md` and
  `tools/issue-discovery/README.md` only after implementation is true.
