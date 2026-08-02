# Testing and Compatibility Specification

## Purpose

Define test-level ownership, shared contract fixtures, deterministic e2e staging, and client rollout behavior.

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

### Requirement: Agent-driven VM capacity contracts are finite and non-executing

The issue-discovery harness MUST validate exactly the finite VM-only,
one-physical-GPU capacity stages below. A scenario MUST declare orchestrator,
buyer, seller, host, listing, request, and physical-GPU counts; current buyer
and seller quickstart paths; role ownership; arrival semantics; expected
success and scarcity counts; retry prohibition; lifecycle assertions; and
zero-residue cleanup. The public scenario contract describes an external run; it
MUST NOT launch an agent or perform a market, wallet, cloud, host,
provisioning, GitHub, VM, or GPU action.

Every row declares `provisioning=real-kvm-ansible` and whole-device G1
assignment as its external execution topology, not as evidence that
preparation ran those systems. The finite progression expands buyers before
adding sellers.

| Stage | O | B | S | H | L | R | G | Ownership and expected outcome |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Q0 host capability | 1 | 0 | 0 | 1 | 0 | 0 | 1 | host-owned preflight contract; no request |
| Reference B1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | controller-driven reference; one success |
| Q1 B1/S1/G1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | substantive agents; one success |
| Q2 B2/S1/G1 | 1 | 2 | 1 | 1 | 1 | 2 | 1 | one success and one expected scarcity |
| Q3 B4/S1/G1 | 1 | 4 | 1 | 1 | 1 | 4 | 1 | one success and three expected scarcity |
| Q4 B8/S1/G1 | 1 | 8 | 1 | 1 | 1 | 8 | 1 | one success and seven expected scarcity |
| Q5 serialized reuse | 1 | 1 | 1 | 1 | 1 | 2 | 1 | two successes separated by teardown |
| Q6 B2/S2/G1 | 1 | 2 | 2 | 1 | 2 | 2 | 1 | one success and one expected scarcity |
| Q7 B4/S2/G1 | 1 | 4 | 2 | 1 | 2 | 4 | 1 | one success and three expected scarcity |
| Q8 B4/S4/G1 | 1 | 4 | 4 | 1 | 4 | 4 | 1 | one success and three expected scarcity |

#### Scenario: Concurrent buyers share one release barrier

- **WHEN** Q2, Q3, Q4, Q6, Q7, or Q8 is validated
- **THEN** every buyer owns one frozen demand, all demands use one common release barrier, retries are zero, and one physical-GPU fence applies across every seller view

#### Scenario: One buyer reuses released capacity

- **WHEN** Q5 is validated
- **THEN** the same persistent buyer owns two serialized requests and the second request cannot be released until terminal teardown and zero-residue cleanup for the first request are represented

#### Scenario: Unsupported capacity shape is supplied

- **WHEN** a scenario selects a non-VM deal, more than one physical GPU, G2, retries, an unknown stage, or adaptive/unbounded progression
- **THEN** validation fails before a runner adapter can be invoked

### Requirement: Substantive role ownership is explicit

Reference B1 MUST be labeled controller-driven product/environment reference
evidence rather than agent-capacity evidence. Beginning at Q1, each seller
MUST own its quickstart-defined identity, service readiness, and assigned
listing; each buyer MUST own preparation and invocation of its exact frozen
demand in one retained session; and the host role MUST own the declared
external provisioning lifecycle. The controller MUST be limited to authority checks,
barriers, bounded observation, retry prohibition, cancellation, evidence, and
cleanup.

#### Scenario: A substantive buyer reaches the barrier

- **WHEN** the buyer reports that its exact demand is prepared
- **THEN** required receipts show that the same buyer session waits for release and invokes that demand itself

#### Scenario: A seller participates in a multi-seller row

- **WHEN** Q6, Q7, or Q8 is represented
- **THEN** every seller has a distinct identity, service, and assigned frozen listing while all listings remain subject to one global physical-GPU fence

### Requirement: Capacity results use current lifecycle and scarcity semantics

A market-request result MUST correlate opaque `capacity_reservation_id` and
`fulfillment_id` values through fulfillment status, a versioned result, and
fulfillment-driven teardown. Executor reference and target checks MUST be
represented only as sanitized correlation assertions. Only HTTP 409 with
`error=offer_unfulfillable` and `reason=no_matching_inventory`, while the
scenario's expected-scarcity budget remains, MAY count as expected scarcity.

Every result MUST contain a typed cleanup receipt. A non-completed termination
MUST also contain a bounded cancellation attempt. Cleanup succeeds only when
it was attempted, completed successfully, and proves zero residue.

#### Scenario: Fulfillment succeeds and returns to baseline

- **WHEN** reservation and fulfillment assertions correlate through terminal result and fulfillment-driven teardown and cleanup proves zero residue
- **THEN** evaluation records success without exporting raw reservation, fulfillment, executor, provider, wallet, host, or cloud values

#### Scenario: Expected contention loses admission

- **WHEN** a request returns the exact structured 409 tuple while the scenario's expected-scarcity budget remains
- **THEN** evaluation counts expected scarcity and issue planning explicitly suppresses it

#### Scenario: Another conflict is observed

- **WHEN** either the HTTP status, error, reason, or expected scarcity count differs
- **THEN** evaluation retains a classified defect rather than suppressing it

#### Scenario: Cleanup is not proven

- **WHEN** the market action otherwise succeeds but a typed cleanup receipt records not-attempted, failed, or non-zero-residue cleanup
- **THEN** evaluation retains a cleanup-failure finding and withholds ordinary publication eligibility

### Requirement: Public findings are sanitized and semantically stable

A capacity finding MUST contain only sanitized public repository, branch, and
SHA metadata; scenario identity; bounded run metadata; correlation assertions;
cleanup state; and bounded evidence. Its fingerprint MUST derive from the
canonical scenario hash, classification, failure code and location, and
normalized stable evidence summary. It MUST exclude occurrence time, run ID,
private refs or paths, credentials, accounts, wallets, network and host
identities, opaque runtime identifiers, and raw logs.

#### Scenario: A defect recurs in another run

- **WHEN** two findings have the same sanitized semantic defect identity but different public occurrences
- **THEN** they have the same fingerprint and distinct occurrence markers

#### Scenario: Public evidence contains a private-shaped value

- **WHEN** a public finding, public branch or run field, cancellation/cleanup receipt, or proposed issue/fix text contains a credential, private path or ref, raw network/host identity, wallet value, or raw-log shape
- **THEN** validation fails before public serialization and without echoing the rejected value

### Requirement: Issue and draft-fix decisions are deterministic and non-mutating

Capacity issue planning MUST derive all findings from the validated result and
MUST choose deterministic no-action, create, no-op, update, reopen, withhold,
or suppression decisions from stable scope and occurrence markers. Publication
MUST require cleanup-proven eligibility. A harness-owned fix proposal MUST use
the exact `fix/<finding-fingerprint>` head and the applicable non-default
working branch as its proposed base, remain draft and never auto-merge, and
fall back to a candidate packet because the public preparation interface has
no mutation authority.

#### Scenario: A matching issue contains no current occurrence

- **WHEN** a matching stable scope exists and the sanitized occurrence is new
- **THEN** an open issue receives an update plan and a closed issue receives a reopen-and-update plan

#### Scenario: A matching occurrence is already recorded

- **WHEN** the issue snapshot already contains both the stable scope and occurrence markers
- **THEN** issue planning returns no-op rather than duplicating the occurrence

#### Scenario: A guarded harness fix is proposed

- **WHEN** a cleanup-eligible harness defect matches an allowlisted fix proposal
- **THEN** the output is a deterministic, non-executed candidate packet with the exact fix head and working-branch base

### Requirement: Capacity preparation interfaces are portable and fail closed

The public issue-discovery CLI MUST expose exactly `validate`, `hash`,
`evaluate`, `finding`, `issue-plan`, `cancel`, and `cleanup` capacity commands;
it MUST NOT expose a capacity run or execute command. Context-bearing commands
MUST accept explicit public repository, non-default branch, 40-character SHA,
run ID, bounded timeout, and repeatable adapter selections. Adapters MUST be
limited to the market, wallet, cloud, host, provisioning, and GitHub-mutation
kinds in `mock`, `fake`, or `dry-run` mode.

Once argument parsing dispatches a capacity command, it MUST emit one stable
JSON envelope. Exit status 0 denotes a successful validation or plan, 1
denotes retained findings or negative lifecycle evidence, 2 denotes
unavailable/invalid input, context, or contract, and 3 denotes invalid adapter
selection. Cancellation and cleanup idempotency and external receipt
validation MUST bind the public ref, scenario hash, run, termination, and
normalized adapter map. These commands MAY validate an externally produced
receipt but MUST NOT perform the represented operation.

#### Scenario: A live adapter is selected

- **WHEN** any adapter kind is assigned `live` or another unsupported mode
- **THEN** the command returns the adapter-selection error before reading scenario/result files or invoking a process, network client, or GitHub operation

#### Scenario: A lifecycle receipt is replayed under another context

- **WHEN** a cancellation or cleanup receipt differs in public ref, scenario, run, termination, adapter map, operation, or idempotency key
- **THEN** validation rejects the receipt as context-mismatched

## Evidence

- Layer ownership: package unit/integration suites and role-level e2e scenarios.
- Cross-language API-credit protocol behavior: `middleware/conformance/session.json` and the Python, TypeScript, and Rust conformance runners.
- Explicit staged dependencies: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`, scenario `require_state` calls, and `e2e-tests/tests/e2e/roles/README.md`.
- Finite VM/G1 contracts and public result/finding behavior: `tools/issue-discovery/config/capacity/`, `tools/issue-discovery/schemas/`, and `tools/issue-discovery/tests/test_capacity.py`.
- Portable non-live commands and lifecycle/issue planning: `tools/issue-discovery/tests/test_cli.py`, `tools/issue-discovery/tests/test_runner.py`, and `tools/issue-discovery/tests/test_issues.py`.

Additive/optional client coexistence during a staged rollout is not established as a general baseline contract; registry rollout work remains proposed in `migrate-registry-to-postgres`.
