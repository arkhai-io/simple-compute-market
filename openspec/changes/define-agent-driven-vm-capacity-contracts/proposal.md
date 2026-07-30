## Why

The reconciled issue-discovery harness still models listings as physical
capacity, admits unqualified two-GPU scenarios, and can label a deterministic
driver run as agent-driven after its Codex processes have already exited. It
also accepts findings whose producer supplies the defect fingerprint and whose
evidence is not bound to the durable VM fulfillment path now present on
`dev`; those gaps prevent the harness from making trustworthy one-GPU
qualification or capacity claims.

## What Changes

- **BREAKING:** introduce schema-v2 capacity scenarios that separate offered
  listings from independently assignable GPUs, admit only VM/KVM/Ansible
  whole-GPU provisioning with retry-zero requests, and reject the historical
  G2 campaign shapes until separate two-GPU authority exists.
- Keep scenario shapes mode-neutral: mock, reference, qualification, and
  measured authority lives in pinned profile-stage/result records, so the same
  B1/S1/G1 bytes can be reused without relabeling the boundary exercised.
- Define the exact one-GPU qualification profile: B1/S1/G1, B2/S1/G1,
  serialized reuse A and B, then B2/S2/G1. The observer probe remains a private
  no-request stage rather than a fabricated public request scenario.
- Define a separately labeled retry-zero measured G1 progression for Q0,
  buyer B2/B4/B8, measured reuse, seller S2/B2 and S2/B4, and conditional
  S4/B4; portable validity does not grant private pre-Q0 admission.
- Define portable buyer, seller, host-operator, observer, frozen-action,
  result, and evidence contracts that distinguish substantive agents from
  readiness probes and keep private runtime identities and credentials outside
  public artifacts.
- Require seller processes to own service start and exact listing publication
  and buyer processes to own purchase and guest verification, with every actor
  alive through its barrier and invoking hash-pinned one-shot wrappers.
- Require exact declared actor cardinality, concurrent process overlap, bounded
  invocation skew, and no local queue/throttle before a concurrent stage can
  count as agent-generated load.
- Define independent VM success, final atomic-capacity-refusal, teardown,
  reuse, and double-allocation oracles around current durable identities,
  especially `fulfillment_id`, without mistaking the nonterminal
  `capacity_hold_unavailable` event for a result or restoring buyer-visible
  physical placement fields.
- Introduce finding v2 with exact working/upstream authority, reconciliation
  context, immutable `finding_id`, scenario/profile/result hashes, structured
  durable correlations, evidence path/hash objects, public redaction, and an
  SCM-derived stable defect fingerprint.
- Require every stage to bind complete terminal evidence, zero residue, and its
  exact restored baseline before another stage can start.
- Record orthogonal exact execution-boundary and actor-trigger authority
  according to what actually ran, and report offered
  buyer count separately from request-processing, simultaneous-fulfillment,
  provisioning queue/service, correctness, and load-generator frontiers.
- Preserve historical schema-v1 artifacts only through their pinned historical
  SCM refs; do not weaken schema-v2 validation with an in-place compatibility
  shim.

## Capabilities

### New Capabilities

- `capacity-testing`: Portable VM capacity scenarios, substantive role and
  frozen-action receipts, independent fulfillment oracles, execution/trigger
  evidence authority, and sanitized immutable findings.

### Modified Capabilities

- `test-compatibility`: Exact `execution_boundary` and `actor_trigger` values
  must match readiness, mock, real reference, qualification, or measured
  behavior and who actually emitted the action.

## Dependencies and Related Changes

- Depends on the reconciled `feat/issue-discovery-harness` product tree at
  `7b114f199440ea94c4dc192385a5cf83d6dd0420`, which is exact
  `dev@0f0126574222ffd09ab148ebc26aecb5d88ed0ea` outside the reviewed portable
  harness roots.
- The separate `guard-issue-fix-publication` change will consume the final
  finding-v2 contract. Credentialed GitHub mutation, outcome reconciliation,
  and draft-PR opening are outside this change.
- Private infrastructure will implement Codex execution, credentials, cloud and
  host topology, unredacted evidence, generation fencing, and cleanup only
  after the final public contract SHA is pushed.

## Non-Goals

- Do not implement cloud execution, Tekton, a scheduled workflow, or a
  default-branch CI trigger.
- Do not provision a real VM, detach or assign a GPU, deploy GKE, fund a wallet,
  publish a listing, emit a live purchase, or file a live issue or PR while
  implementing this portable contract.
- Do not restore removed provisioning services, direct legacy clients,
  `provisioning_job_id` as a universal identity, or buyer-visible
  `resource_id`/`vm_host`.
- Do not claim that listing count, offered buyer count, readiness overlap, mock
  success, or a deterministic reference run is system capacity.
- Do not admit a G2 profile without a later independently reviewed contract
  proving two safely assignable whole GPUs.

## Impact

- Public issue-discovery scenario, role/action/result/finding schemas and
  fixtures under `tools/issue-discovery`.
- Scenario and finding validation, canonical hashing, fingerprint derivation,
  oracle evaluation, CLI behavior, and focused/full package tests.
- Operational documentation in `docs/development/ISSUE_DISCOVERY.md` and
  `tools/issue-discovery/README.md` after the behavior is implemented.
- No wire, database, marketplace, provisioning, deployment, or package
  dependency change outside the public testing tool. Schema-v2 campaign
  artifacts are intentionally incompatible with v1 at the current ref.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Portable capacity-test authority, scenario semantics, substantive role
  receipts, frozen agent-triggered actions, durable VM oracles, evidence
  classes, and finding-v2 invariants belong in
  `openspec/specs/capacity-testing/spec.md` with rationale in its companion
  `architecture.md`.
- Evidence-label compatibility belongs in
  `openspec/specs/test-compatibility/spec.md` and its companion architecture.
- The public/private test-authority split and testing vocabulary belong under
  `docs/development/ARCHITECTURE.md#testing-strategy`.
- The new capability is added to `openspec/specs/README.md`; operational usage
  is updated only after implementation is true.
