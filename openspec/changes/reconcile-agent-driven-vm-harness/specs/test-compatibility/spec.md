## ADDED Requirements

### Requirement: Finite agent-driven VM capacity scenarios

The issue-discovery harness MUST validate one finite VM-only, one-physical-GPU
scenario contract for Q0, controller-driven Reference B1, and agent-driven
Q1-Q8. Each scenario MUST declare exact orchestrator, buyer, seller, host,
listing, request, and physical-GPU counts, current buyer and seller quickstart
references, action ownership, arrival semantics, expected successes and typed
scarcity, retry prohibition, and cleanup invariants. G2, non-VM, and adaptive
frontier inputs MUST be rejected.

#### Scenario: Buyer contention row is validated

- **WHEN** a Q2, Q3, or Q4 fixture declares one seller listing, one physical
  GPU, multiple substantive buyer demands, and one common release barrier
- **THEN** the harness validates exactly one expected success and one expected
  scarcity result for every remaining request

#### Scenario: Seller contention row is validated

- **WHEN** a Q6, Q7, or Q8 fixture declares multiple distinct seller services
  and listings over one physical GPU
- **THEN** the harness requires one global physical-GPU fence and validates
  exactly one expected success with typed scarcity for remaining concurrent
  requests

#### Scenario: Serialized reuse is validated

- **WHEN** Q5 declares two requests from one persistent buyer and one listing
- **THEN** the harness requires two successes separated by terminal teardown
  and zero-residue cleanup before the second request is released

#### Scenario: Unsupported capacity shape is supplied

- **WHEN** a scenario selects a non-VM deal, more than one physical GPU, G2,
  retries, or an unbounded/adaptive stage
- **THEN** validation fails before any runner or adapter can be invoked

### Requirement: Substantive agent ownership is explicit

The public harness MUST express role intent and required receipts without
launching agents or containing private execution data. Reference B1 MUST be
identified as controller-driven reference evidence. Beginning at Q1, each
seller MUST own its quickstart-defined identity, service, and assigned listing
actions; each buyer MUST own preparation and invocation of its frozen demand;
and the host role MUST own the future provisioning lifecycle. The controller
MUST be limited to authority checks, barriers, observation, retry prohibition,
cancellation, evidence, and cleanup.

#### Scenario: Agent-driven request reaches a release barrier

- **WHEN** a substantive buyer reports its frozen demand ready
- **THEN** the same buyer role/session remains responsible for invoking that
  exact demand after the controller releases the barrier

#### Scenario: Controller reference is evaluated

- **WHEN** Reference B1 uses controller request emission
- **THEN** its result is labeled product/environment reference evidence and is
  not counted as agent-capacity evidence

### Requirement: Current fulfillment lifecycle is evaluated portably

The harness MUST correlate opaque `capacity_reservation_id` and
`fulfillment_id` values through fulfillment status, versioned result, and
fulfillment-driven teardown. It MUST represent private executor reference and
target checks only as sanitized correlation assertions. Only HTTP 409 with
structured `error=offer_unfulfillable` and
`reason=no_matching_inventory` MAY satisfy expected scarcity.

#### Scenario: Fulfillment succeeds and cleans up

- **WHEN** required receipts correlate the reservation and fulfillment through
  terminal result and teardown and the zero-residue cleanup invariant passes
- **THEN** evaluation returns typed success without exporting raw executor or
  provider data

#### Scenario: Expected inventory scarcity occurs

- **WHEN** a request expected to lose contention returns the exact structured
  409 scarcity tuple
- **THEN** evaluation records expected scarcity and produces no finding

#### Scenario: Another conflict occurs

- **WHEN** a response is 409 but its structured error or reason differs
- **THEN** evaluation does not suppress it as expected scarcity

### Requirement: Sanitized findings have stable semantic identity

A finding MUST contain only sanitized public repository/branch/SHA, scenario
hash, run metadata, correlation assertions, cleanup state, and bounded evidence.
Its fingerprint MUST derive from canonical sanitized defect identity and MUST
exclude timestamps, run identifiers, temporary or private paths, private refs,
account/project/host identity, credentials, and raw logs.

#### Scenario: A defect recurs in another run

- **WHEN** two occurrences have the same sanitized semantic defect identity
  but different run IDs, timestamps, or private evidence locations
- **THEN** they receive the same fingerprint and retain separate sanitized
  occurrence metadata

#### Scenario: Cleanup fails after market success

- **WHEN** the market action succeeds but cleanup cannot prove zero residue
- **THEN** evaluation emits a cleanup-failure finding and withholds ordinary
  publication eligibility

### Requirement: Issue and draft-fix decisions are deterministic and mockable

The harness MUST plan create, no-op, update, or reopen behavior from stable
issue markers. Expected scarcity MUST be suppressed before issue planning, and
cleanup eligibility MUST gate publication. A harness-owned fix proposal MUST
use exact `fix/<finding-fingerprint>` naming, target the applicable replacement
branch, remain draft and never auto-merge, and fall back to a candidate packet
when mutation authority is absent. Preparation validation MUST use only mocks
or dry runs.

#### Scenario: Closed issue receives another occurrence

- **WHEN** a matching fingerprint marker exists only on a closed issue
- **THEN** the plan reopens and updates that issue rather than creating a
  duplicate

#### Scenario: Safe harness fix has no mutation authority

- **WHEN** an eligible harness-owned finding has an allowlisted fix proposal
  but authenticated mutation is unavailable
- **THEN** the harness returns a candidate packet with the deterministic head
  and replacement base and creates no branch or pull request

### Requirement: Preparation interfaces fail closed and remain portable

The public CLI MUST accept explicit public repository, branch, SHA, scenario,
run, timeout, and adapter inputs and MUST return stable machine-readable
results and exit codes for validation, evaluation, cancellation, cleanup, and
dry-run planning. Selecting a live market, wallet, cloud, host, provisioning,
or GitHub mutation adapter in preparation mode MUST fail before subprocess or
network execution. Cancellation and cleanup MUST be attempted on every timeout,
partial failure, role failure, and controller failure path.

#### Scenario: Live adapter is selected during preparation

- **WHEN** a preparation command receives any live mutation adapter
- **THEN** it rejects the request before invoking an external command or
  network client

#### Scenario: Runner is interrupted

- **WHEN** a timeout, cancellation, partial launch, role failure, or controller
  failure terminates a mocked run
- **THEN** its result records bounded cancellation and idempotent cleanup
  attempts with their typed outcomes
