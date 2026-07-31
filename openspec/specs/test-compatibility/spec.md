# Testing and Compatibility Specification

## Purpose

Define test-level ownership, shared contract fixtures, deterministic e2e
staging, capacity-evidence authority, portable executor compatibility, and
client rollout behavior.

## Requirements

### Requirement: Layered behavioral verification
Unit, integration, smoke, and end-to-end tests MUST each defend the narrowest observable contract appropriate to their level and MUST NOT rely on e2e alone for component behavior.

#### Scenario: Service API behavior changes
- **WHEN** a route contract changes
- **THEN** focused unit/integration coverage pins the route behavior and e2e verifies only the cross-service flow

### Requirement: Shared contract fixtures
Cross-language or cross-package implementations of the same protocol MUST consume canonical fixtures that encode observable requests, responses, and state transitions.

#### Scenario: API-credit middleware port changes
- **WHEN** Python, TypeScript, or Rust middleware behavior is updated
- **THEN** each implementation reproduces the shared conformance session

### Requirement: Dependency-aware e2e stages
The end-to-end stage that violates an observable contract MUST fail; downstream stages MUST explicitly declare consumed prior state and skip with the exact missing state field rather than failing for an unrelated symptom.

#### Scenario: Required deal state is absent
- **WHEN** a downstream stage lacks a prerequisite produced by an earlier stage
- **THEN** the skip reason names the missing `DealState` field

### Requirement: Exact e2e state dependencies
Every staged e2e state field MUST use one exact producer/consumer name, and every field introduced for downstream behavior MUST have at least one explicit `require_state` consumer.

#### Scenario: Test author adds staged state
- **WHEN** a test adds a field to `DealState`
- **THEN** a downstream stage consumes that exact attribute name and coverage verifies the transition

### Requirement: Evidence labels match the exercised boundary
Every boundary-classifying capacity profile stage, actor set, oracle authority,
capacity result, and mock capture MUST use the exact orthogonal fields
`execution_boundary` (`readiness`, `mock`, `real-reference`,
`real-qualification`, or `real-measured`) and `actor_trigger` (`none`,
`controller-driven`, or `agent-triggered`) whose acceptance boundaries were
actually exercised. A role, action, policy, frontier, or finding artifact whose
closed schema does not carry those fields MUST inherit any boundary/trigger
meaning only through its validated pinned profile-stage, result, or registry
lineage and MUST NOT add or override the classification. The admitted
combinations and evidence meaning are exact:

| `execution_boundary` | `actor_trigger` | Portable evidence meaning |
| --- | --- | --- |
| `readiness` | `none` | No-request probe or role readiness only |
| `mock` | `agent-triggered` | Capture-only agent action composition with no real-resource authority |
| `real-reference` | `controller-driven` | Deterministic real lifecycle control, excluded from agent-capacity evidence |
| `real-qualification` | `agent-triggered` | Substantive real agent qualification, with no measured frontier |
| `real-measured` | `agent-triggered` | Substantive real agent measurement, subject to independent frontier eligibility |

A `capacity-result` MUST use only `real-reference`/`controller-driven`,
`real-qualification`/`agent-triggered`, or
`real-measured`/`agent-triggered`. Readiness MUST use probe or role receipts,
and mock execution MUST use a capture artifact rather than a capacity result.
Readiness before controller-owned emission MUST NOT be labeled agent-triggered;
mock provisioning MUST NOT be labeled real system capacity; and a deterministic
reference lifecycle MUST NOT count as agent-capacity evidence. Qualification
and measured boundaries MUST remain distinct across the pre-Q0 boundary.

Agent provenance MUST require substantive receipts and barrier liveness for
every counted role. Each action-owning buyer or seller MUST remain alive
through release and invoke its pinned one-shot wrapper; the actionless
independent observer and host operator MUST remain live through their declared
observation or cleanup barriers. A controller MAY freeze exact action bytes
and coordinate barriers, but controller emission after the actor exits
invalidates the attempted agent-driven row and MUST NOT be relabeled as
readiness, mock, reference, or partial capacity evidence. Structurally
authoritative negative observations MAY retain agent provenance, but generator
rejection, queueing, throttling, overlap failure, or skew failure MUST make the
row ineligible for a capacity frontier. In that case
`agent_capacity_evidence` MUST remain true for a valid qualification or
measured row while
`eligible_for_capacity_frontier` MUST be false; the two fields MUST NOT be
conflated.

Product-capacity and progression claims MUST come from independently validated
durable-oracle evidence plus the applicable execution authority: the frozen
reference policy and controller proof for a real reference, or the actor set
for an agent-triggered row. An actor or emitter success flag MUST NOT
substitute. A request-bearing stage MUST NOT advance until its terminal
correlations, teardown, zero-active-residue proof, baseline-equivalence
comparison, independent-observer outcome and cleanup seals, and host-operator
cleanup evidence agree. Any residue, missing seal, or baseline mismatch MUST
fence the next stage even when every actor reports success. Each result's
`progression_ready_at` MUST equal the later of the independent observer's and
host operator's evidence completion times on the common campaign clock, and a
following stage MUST start strictly after it.

#### Scenario: Readiness-before-emission is labeled accurately
- **WHEN** role processes prepare or approve requests but exit before a controller emits them
- **THEN** their role/action preparation may remain non-capacity diagnostic evidence, but no classified capacity row is valid and the attempted agent row is ineligible as qualification or measured evidence

#### Scenario: Mock path stays preparatory
- **WHEN** buyer and seller agents complete their role paths against mock provisioning
- **THEN** the capture is `execution_boundary=mock` and `actor_trigger=agent-triggered` and cannot satisfy real KVM/GPU qualification or capacity measurement

#### Scenario: Deterministic reference remains a control
- **WHEN** a deterministic driver completes the real B1 VM lifecycle before agent-driven qualification
- **THEN** the result is `execution_boundary=real-reference` and `actor_trigger=controller-driven` and is excluded from agent-capacity frontiers

#### Scenario: Real evidence keeps qualification and measurement distinct
- **WHEN** a real qualification row or admitted measured row completes
- **THEN** the result uses `real-qualification` or `real-measured` with `actor_trigger=agent-triggered` and cannot be relabeled across the pre-Q0 boundary

#### Scenario: Actor success conflicts with cleanup evidence
- **WHEN** actors report success but independent terminal, teardown, residue, baseline, observer-seal, or host-operator evidence is incomplete or inconsistent
- **THEN** the stage remains failed, its correctness and cleanup observations fail, and it cannot authorize a following stage or buyer-frontier receipt

### Requirement: Capacity contracts preserve a portable executor seam
Local Codex execution and cloud or Tekton execution MUST consume the same
repository-relative public commands, pinned scenario/profile inputs, frozen
portable role/action inputs, and portable result schemas. An executor that
consumes a public profile registry or profile stage MUST invoke SCM's
Git-pinned semantic validation operation with the exact SCM ref and applicable
expected canonical and raw-byte digests, then consume the returned validated
semantic projection. It MUST NOT import SCM Python modules across the
repository boundary, reread unvalidated worktree bytes, or reimplement public
profile policy.

The public contract owns portable schemas, canonicalization, Git-pinned
scenario and profile semantics, validation, evidence labels, and result
meaning. It MUST NOT depend on an executor-local path, credential source,
cloud project, process supervisor, private host or GPU identity, or Tekton
object. Private infrastructure owns executor selection, live Codex
process/session and release-channel authentication, credentials, project and
resource admission, generation fencing, cancellation, watchdogs, native
evidence, live teardown, and private-to-portable bindings. A portable
actor-invocation binding alone MUST NOT be treated as proof that a live Codex
process owned it.

Every executor MUST enforce the same one-GPU topology fence: all seller plans
and terminal seller receipts carry the sole host-operator plan's typed
`topology_authority_binding`; the concurrency policy rejects a missing or
disjoint seller binding before release; frozen seller actions inherit the
authority through exact plan-hash and policy lineage; and the result topology
authority still matches the host operator. The binding is an opaque portable
proof of one globally fenced seller view, not a portable host or GPU
identifier.

That topology binding MUST remain stable across campaign composition: all
buyer results assembled into a buyer-frontier receipt share it; the receipt
repeats it; measured reuse A matches the receipt; reuse B preserves A in both
measured and qualification modes; and every measured seller result matches the
frontier, reuse B, and its prior seller result. Local and cloud runners MUST
reject the same topology splice at the same validation boundary.

The CLI or runner MAY accept executor-local paths as invocation-time plumbing
to load evaluation policy, role/action contexts, buyer-frontier receipt, reuse
predecessor or baseline, and ordered prior seller results. Those paths MUST
NOT become portable authority: validation MUST reconstruct typed artifacts,
verify their pinned IDs, hashes, and lineage, and serialize only portable
references. Moving identical context bytes to different local paths MUST NOT
change a canonical digest or validation result, and no context-manifest path
MAY enter a capacity result or frontier receipt.

The result context manifest MUST contain exactly `capacity_result`,
`oracle_authority`, `reference_policy`, `observer_plan`, `actor_set`,
`concurrency_policy`, `role_plans`, `role_receipts`, `frozen_actions`,
`payloads`, and `action_results`. Reference context MUST require reference
policy and exact actionless independent-observer and host-operator plan/receipt
evidence while forbidding agent actor/action context. Agent context MUST
require actor set, concurrency policy, complete role/action evidence, and null
reference-only paths. Buyer-frontier authority MUST be null for qualification
reuse; it MUST be present with ordered buyer-result contexts for measured reuse
and seller progression. Validate/hash commands MUST exist for evaluation
policy, reference policy, result, reuse, and buyer frontier.

#### Scenario: Local and cloud executors validate the same artifact
- **WHEN** a local Codex runner and a cloud or Tekton runner present the same pinned public scenario, profile stage, role/action receipts, and result
- **THEN** the public commands calculate the same identities and validation outcome

#### Scenario: Executor detail enters a portable artifact
- **WHEN** a public capacity artifact contains a local path, credential location, cloud project, Tekton task name, or private host identity
- **THEN** validation rejects it instead of coupling the contract to that executor

#### Scenario: Local context paths remain invocation plumbing
- **WHEN** two executors load the same validated policy, role, frontier, reuse, and seller-context bytes from different local paths
- **THEN** the runner derives the same portable IDs, hashes, and outcome while omitting every local path from result authority

#### Scenario: Executors reject a disjoint seller topology identically
- **WHEN** one seller plan differs from the host-operator topology authority, a seller receipt differs from its plan, or the result differs from the host operator
- **THEN** local Codex and cloud or Tekton execution reject at the same pre-release, receipt, or result boundary respectively

#### Scenario: Executors reject a campaign topology splice identically
- **WHEN** buyer-frontier results disagree, the receipt changes their topology, reuse A or B changes it, or a seller result differs from the frontier, reuse B, or prior seller result
- **THEN** local Codex and cloud or Tekton execution both reject the chain instead of combining separately valid one-GPU views

## Evidence

- Layer ownership: package unit/integration suites and role-level e2e scenarios.
- Cross-language API-credit protocol behavior: `middleware/conformance/session.json` and the Python, TypeScript, and Rust conformance runners.
- Explicit staged dependencies: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`, scenario `require_state` calls, and `e2e-tests/tests/e2e/roles/README.md`.
- Capacity boundary/trigger and substantive-role enforcement:
  `tools/issue-discovery/schemas/capacity-profile-stage.schema.json`,
  `tools/issue-discovery/schemas/capacity-result.schema.json`,
  `tools/issue-discovery/schemas/capacity-mock-capture.schema.json`,
  `tools/issue-discovery/src/issue_discovery/capacity_roles.py`, and
  `tools/issue-discovery/tests/test_capacity_roles.py`.
- Pinned semantic projections and executor-neutral result validation:
  `tools/issue-discovery/src/issue_discovery/capacity.py`,
  `tools/issue-discovery/src/issue_discovery/capacity_outcomes.py`,
  `tools/issue-discovery/src/issue_discovery/runner.py`, and
  `tools/issue-discovery/tests/test_capacity_cli_runner_interfaces.py`.

Additive/optional client coexistence during a staged rollout is not established as a general baseline contract; registry rollout work remains proposed in `migrate-registry-to-postgres`.
