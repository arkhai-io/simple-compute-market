## ADDED Requirements

### Requirement: Evidence labels match the exercised boundary
Every evidence artifact MUST use the exact orthogonal fields
`execution_boundary` (`readiness`, `mock`, `real-reference`,
`real-qualification`, or `real-measured`) and `actor_trigger` (`none`,
`controller-driven`, or `agent-triggered`) whose acceptance boundaries were
actually exercised. Process readiness before controller-owned emission MUST
NOT be agent-triggered; mock provisioning MUST NOT be labeled real system
capacity; and a deterministic reference lifecycle MUST NOT be counted as
agent-capacity evidence. Qualification and measured boundaries MUST be
reserved for their respective admitted real paths.
`capacity-result` accepts only real-reference/controller-driven,
real-qualification/agent-triggered, and real-measured/agent-triggered.
Readiness uses probe/role receipts; mock uses `capacity-mock-capture`.
Controller emission after actor exit invalidates an agent qualification or
measurement and does not become the deterministic reference.

#### Scenario: Readiness-before-emission is labeled accurately
- **WHEN** role processes exit after preparing or approving requests and a controller emits those requests later
- **THEN** the attempted agent row is ineligible as a qualification/measured capacity result while its preparation and controller-driven negative evidence remain accurately classified

#### Scenario: Mock path stays preparatory
- **WHEN** buyer and seller agents complete their role path against mock provisioning
- **THEN** the mock-capture is `execution_boundary=mock` and `actor_trigger=agent-triggered` and cannot satisfy real KVM/GPU qualification or capacity measurement

#### Scenario: Deterministic reference remains a control
- **WHEN** a deterministic driver completes the real B1 VM lifecycle before agent-driven qualification
- **THEN** the result is `execution_boundary=real-reference` and `actor_trigger=controller-driven` and is excluded from agent-capacity frontiers

#### Scenario: Real evidence keeps qualification and measurement distinct
- **WHEN** a real qualification row or an admitted measured row completes
- **THEN** the result uses `real-qualification` or `real-measured` with `actor_trigger=agent-triggered` and cannot be relabeled across the pre-Q0 boundary

### Requirement: Capacity contracts preserve a portable executor seam
Local Codex execution and a future cloud or Tekton executor MUST consume the
same repository-relative public commands, pinned scenario/profile inputs, and
portable result schemas. The public contract MUST NOT depend on an
executor-local path, credential source, cloud project, process supervisor, or
Tekton object. Private infrastructure MUST own executor selection, credentials,
cancellation, watchdogs, native evidence, and teardown while producing the same
portable artifacts.

Every executor MUST enforce the same one-GPU topology fence: all seller plans
and terminal seller receipts carry the sole H1 plan's typed
`topology_authority_binding`; the concurrency policy rejects a missing or
disjoint seller binding before release; frozen seller actions inherit the
authority through exact plan-hash/policy lineage; and the result topology
authority still matches H1. The binding is an opaque portable proof of one
globally fenced seller view, not a portable host or GPU identifier.

That binding MUST remain stable across campaign composition: all buyer results
assembled into a buyer-frontier receipt share it; the receipt repeats it;
measured reuse A matches the receipt; reuse B preserves A in measured and
qualification modes; and every measured seller result matches the frontier,
reuse B, and its prior seller result. Local and cloud runners MUST reject the
same topology splice at the same validation boundary.

The CLI/runner MAY accept executor-local paths as invocation-time plumbing to
load the evaluation policy, role/action contexts, buyer-frontier receipt,
reuse predecessor/baseline, and ordered prior seller results. Those paths are
not portable authority: validation MUST reconstruct typed artifacts, verify
their pinned IDs/hashes and lineage, and serialize only the portable
references. Moving identical context bytes to different local paths MUST NOT
change any canonical digest or validation result, and no context-manifest path
MAY enter a capacity result or frontier receipt.

The result context manifest MUST contain exactly `capacity_result`,
`oracle_authority`, `reference_policy`, `observer_plan`, `actor_set`,
`concurrency_policy`, `role_plans`, `role_receipts`, `frozen_actions`,
`payloads`, and `action_results`. Reference context requires reference policy
and exact actionless O1/H1 plan/receipt evidence and forbids actor/action
context. Agent context requires actor set, concurrency policy, and complete
role/action evidence and null reference-only paths. Buyer-frontier authority
MUST be null for qualification reuse; it is required with ordered buyer-result
contexts for measured reuse and seller progression. Validate/hash commands MUST exist for
evaluation policy, reference policy, result, reuse, and buyer frontier.

#### Scenario: Local and cloud executors validate the same artifact
- **WHEN** a local Codex runner and a future cloud or Tekton runner present the same pinned public scenario, profile-stage, role/action receipts, and result
- **THEN** the public commands calculate the same identities and validation outcome

#### Scenario: Executor detail enters a portable artifact
- **WHEN** a public capacity artifact contains a local path, credential location, cloud project, Tekton task name, or private host identity
- **THEN** validation rejects it instead of coupling the contract to that executor

#### Scenario: Local context paths remain invocation plumbing
- **WHEN** two executors load the same validated policy, role, frontier, reuse, and seller-context bytes from different local paths
- **THEN** the runner derives the same portable IDs/hashes and outcome while omitting every local path from the result authority

#### Scenario: Executors reject a disjoint seller topology identically
- **WHEN** one seller plan differs from the sole H1 topology authority, a seller receipt differs from its plan, or the result differs from H1
- **THEN** local Codex and future cloud/Tekton execution reject at the same pre-release, receipt, or result boundary respectively

#### Scenario: Executors reject a campaign topology splice identically
- **WHEN** buyer-frontier results disagree, the receipt changes their topology, reuse A/B changes it, or a seller result differs from the frontier, reuse B, or prior seller result
- **THEN** local Codex and future cloud/Tekton execution both reject the chain instead of combining separately valid one-GPU views
