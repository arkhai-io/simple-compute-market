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
- Expose the validated profile registry and profile-stage semantic projections,
  canonical and raw authority digests, pinned paths, and resolved scenario
  through stable CLI/runner entry points so private orchestration can consume
  public policy without importing SCM internals or reimplementing it.
- Define the exact one-GPU qualification profile: B1/S1/G1, B2/S1/G1,
  serialized reuse A and B, then B2/S2/G1. The observer probe remains a private
  no-request stage rather than a fabricated public request scenario.
- Define a separately labeled retry-zero measured G1 progression for Q0,
  buyer B2/B4/B8, a hash-bound buyer-frontier receipt, measured reuse, seller
  S2/B2 and S2/B4, and conditional S4/B4; portable validity does not grant
  private pre-Q0 admission.
- Freeze one pre-Q0 evaluation policy containing the exact registry bytes,
  common clock, SLOs, timeout, and five frontier definitions so outcomes cannot
  be reclassified after observation.
- Freeze a typed controller-reference policy after that evaluation policy and
  before reference release, binding the exact O1/H1 plans, release, campaign
  clock, and request schedule; bind the exact resulting O1/H1 receipts into the
  reference result.
- Define portable buyer, seller, host-operator, observer, frozen-action,
  result, and evidence contracts that distinguish substantive agents from
  readiness probes and keep private runtime identities and credentials outside
  public artifacts.
- Make every seller plan and terminal receipt repeat the sole H1 plan's typed
  `topology_authority_binding`. Reject a disjoint seller authority in the
  concurrency policy before release, carry the shared authority into frozen
  seller actions through exact plan-hash/policy lineage, and require the
  capacity result's topology authority to remain equal to H1.
- Treat that binding as the public opaque proof that all sellers in a one-GPU
  row consult one globally fenced capacity view, without publishing host, GPU,
  allocator, or private fencing identities.
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
- Require exact independent request timing and O1 receipt seals for every
  request outcome and cleanup object, retain typed negative agent observations,
  and preserve independently derived double allocation as actionable fault
  evidence rather than discarding the result.
- Introduce finding v2 with exact destination, working/upstream/inbound
  first-parent authority, reconciliation context, immutable occurrence
  `finding_id`, scenario/profile/result hashes, structured durable
  correlations projected from one fully validated result, and evidence
  `{path, sha256}` objects verified as raw bytes below exact immutable
  `evidence/` within one explicit evidence root.
- Make SCM derive defect identity as `capacity-<lowercase sha256>` over the
  domain prefix `scm.capacity.finding-fingerprint.v1\0` and one closed
  normalized semantic object. Keep occurrence, result, ref, evidence, durable
  identity, prose, cleanup, and readiness fields outside that identity. Reject
  rather than rewrite any value matched by the pinned portable public policy;
  require private infrastructure to reject its exact private values before
  export.
- Make public privacy validation representation-aware: inspect structured JSON
  keys/strings, decoded JSON/YAML scalar spellings, and CommonMark-visible text
  after HTML-entity and backslash-escape projection; traverse composed
  encodings to a bounded fixed point; repeat matching over Unicode NFKC and
  mark-stripped NFKD projections; and reject Unicode default-ignorable,
  `Cf` format/bidirectional, and disallowed `Cc` controls rather than permitting
  invisible evasion.
- Bound one finding to at most 1 MiB of raw UTF-8 bytes per evidence artifact
  and 4 MiB in aggregate, and render agent-controlled summary, stable
  signature, expected, and actual prose only as literal indented CommonMark
  blocks.
- Admit findings only for one of the ten request failure categories or the
  stage-derived `double-allocation` and `unexpected-outcome` categories.
  Expected proven capacity refusal and a frontier stop without an underlying
  fault remain results, not findings.
- End this change at immutable local occurrence storage, an authority-checked
  run-manifest projection, one idempotent locally proven `detected` event in
  the separate lifecycle ledger, and a marker-free human occurrence payload
  with exact SHA-256. Make legacy issue creation (including force), lifecycle
  transition, and fix-proposal surfaces reject finding v2 before subprocess or
  GitHub access.
- Root all private finding reads and writes in one current-user-owned mode-0700
  run-directory descriptor held for the complete ingest/replay critical
  section. Serialize compliant writers on both that directory descriptor and
  the authenticated persistent mode-0600 lock file, revalidate every
  descriptor-relative ancestor and destination, and recover only authenticated
  owner-only temporary peers for exact managed destinations from interrupted
  create-once or replacement publication. Decide legacy versus finding-v2 state
  once under the held root lock; a lock file alone is reusable crash residue,
  while substantive v2 state requires that pre-existing lock for replay.
- Scope those filesystem guarantees to crash recovery, non-malicious drift, and
  concurrent writers that honor both advisory locks. Reject every observed
  identity or content mismatch before success, while explicitly excluding a
  same-effective-user process that bypasses the locks and substitutes a leaf
  inside the unavoidably pathname-based `linkat`, `unlinkat`, or `renameat2` syscall
  window.
- Require every stage to bind complete terminal evidence, zero residue, and its
  exact restored baseline before another stage can start.
- Record orthogonal exact execution-boundary and actor-trigger authority
  according to what actually ran, and report offered
  buyer count separately from request-processing, simultaneous-fulfillment,
  provisioning queue/service, correctness, and load-generator frontiers.
- Fence measured ordering transitively as buyer frontier → reuse A → reuse B →
  seller results, with exact result hashes and final H1/O1
  `progression_ready_at` fences at every edge; derive seller admission only from
  reuse-B H1's pre-frozen plan/receipt, seal it in reuse B, and let downstream
  seller results bind that reuse-B authority without a future-result cycle.
- Carry the same opaque topology authority through every measured buyer result
  and the buyer-frontier receipt, measured reuse A, reuse B, and every seller
  result/prior-result edge. Qualification reuse also preserves topology from A
  to B even though it has no buyer-frontier authority.
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
  finding-v2 contract. It exclusively owns publication scope/occurrence/fix-PR
  markers, final rendered-body authority, GitHub occurrence reconciliation,
  credentialed mutation, post-mutation lifecycle facts, and draft-PR opening.
  None of those authorities are produced by this change.
- Private infrastructure will implement Codex execution, credentials, cloud and
  host topology, unredacted evidence, generation fencing, and cleanup only
  after the final public contract SHA is pushed.

## Non-Goals

- Do not implement cloud execution, Tekton, a scheduled workflow, or a
  default-branch CI trigger.
- Do not provision a real VM, detach or assign a GPU, deploy GKE, fund a wallet,
  publish a listing, emit a live purchase, or file a live issue or PR while
  implementing this portable contract.
- Do not let validation, capture-only mock composition, finding ingest, packet
  replay, or documentation promotion trigger a live market, cloud, host, GPU,
  wallet, GitHub, or cleanup side effect. Those operations remain future
  private campaign/execution work behind the portable contracts.
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
