# Settlement Servicing Specification

## Purpose

Define the implemented mechanism-neutral settlement-plan carrier, persisted claim servicing, and signed heartbeat evidence.
## Requirements
### Requirement: Negotiation-to-plan handoff
Negotiation MUST produce deterministic Terms and the settlement path MUST
register every accepted obligation as a mechanism-neutral Settlement Plan
before a fulfillment side effect begins. A seller MAY adopt a separately
verified pre-materialized obligation without invoking materialization again.

#### Scenario: Pre-materialized escrow is accepted
- **WHEN** the seller verifies the exact obligation represented by an existing
  mechanism reference
- **THEN** the runtime registers the accepted plan and idempotently adopts that
  reference for the verified obligation index before fulfillment

### Requirement: Mechanism-neutral plan carrier
Core settlement-plan carriers MUST express lifecycle-universal fields and
carry mechanism-specific data in tagged `{mechanism, params}` envelopes.

#### Scenario: New settlement mechanism is added
- **WHEN** a composition registers a client for a new mechanism
- **THEN** the settlement runtime carries its opaque parameters and public-safe
  outcomes without importing the mechanism kit

### Requirement: Durable idempotent servicing
The settlement-runtime worker MUST bind one immutable fulfillment reference,
persist every condition/effect attempt through the canonical operation
journal, retry transient or pending outcomes, and avoid duplicate successful
collection across restarts.

#### Scenario: Collection succeeds before a restart
- **WHEN** the worker resumes the same obligation
- **THEN** it observes the durable terminal state and does not collect twice

#### Scenario: Condition remains pending across restart
- **WHEN** a client returns pending with updated opaque mechanism state
- **THEN** the repository persists that state before backoff and supplies it to
  the next authoritative status or condition check

### Requirement: Signed heartbeat evidence
The buyer MAY emit signed deal heartbeats while service is healthy; the seller
MUST authenticate and persist accepted heartbeats as deal-scoped evidence.

#### Scenario: Heartbeat identity mismatches the deal
- **WHEN** a heartbeat signature is not from the deal's buyer
- **THEN** the seller rejects it without updating settlement evidence

### Requirement: Mechanism clients own mechanism vocabulary
Alkahest-specific plan, status, arbiter, collection, and reclaim encoding MUST
live in the Alkahest kit behind the shared conditional-escrow client port.

#### Scenario: Runtime evaluates an Alkahest obligation
- **WHEN** it needs mechanism-specific status, readiness, collection, or
  reclaim behavior
- **THEN** it dispatches through the registered Alkahest client with the stable
  operation reference and prior durable mechanism state

### Requirement: Durable independent obligation lifecycle
Settlement servicing MUST derive stable repository identity for every ordered
plan obligation and MUST persist materialization, condition evaluation,
collection, reclaim, attempt, uncertain-acknowledgement, and receipt state
independently. Equivalent retries MUST reuse one operation identity; changed
reuse MUST fail closed. Collection and reclaim MUST reserve one mutually
exclusive compare-and-swap winner before mechanism I/O.

#### Scenario: Plan contains obligations in both directions
- **WHEN** an accepted plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized by its payer and collected by its claimant without interpreting list position as direction

#### Scenario: One obligation fails after a sibling completes
- **WHEN** a plan operation requires retry or manual repair after another obligation reached a terminal effect
- **THEN** the completed sibling remains terminal and operator status identifies the affected obligation without replaying the completed effect

#### Scenario: Acknowledgement is uncertain across restart
- **WHEN** a mechanism mutation may have succeeded before its acknowledgement was lost
- **THEN** the operation journal records uncertainty and retry uses the same obligation and operation identity

#### Scenario: Collection races reclaim
- **WHEN** claimant collection and payer reclaim concurrently target one obligation
- **THEN** exactly one reservation may invoke the mechanism and the other observes a busy or terminal outcome

### Requirement: Deterministic interval and penalty-bond policy
The Alkahest settlement policy MUST be able to split an accepted positive total
across deterministic time intervals and create an explicit seller-funded,
buyer-claimable penalty bond. Interval amounts MUST be positive, proportional
to interval duration, allocate integer remainder to earliest intervals, and
sum exactly to the accepted total. Derived obligations MUST preserve the
accepted mechanism demand bytes and payer/claimant direction.

#### Scenario: Duration has a short final interval
- **WHEN** a duration is not evenly divisible by the interval size
- **THEN** the final boundary uses the remaining duration and all interval amounts still conserve the accepted total exactly

#### Scenario: Total is too small for positive intervals
- **WHEN** splitting would create a zero-value obligation
- **THEN** policy rejects the schedule before materialization

#### Scenario: Seller penalty bond is accepted
- **WHEN** accepted policy requires a penalty bond
- **THEN** the resulting obligation names the seller as payer, the buyer as claimant, and is serviced independently from buyer-funded payment obligations

### Requirement: Aggregate and per-obligation status
Operator-facing settlement status MUST derive the plan aggregate from every
authoritative obligation row and MUST include each obligation's lifecycle
state. Aggregate status MUST be `complete` only when every obligation has a
successful collection or reclaim, `manual_required` when any obligation needs
repair, `partial` when only some obligations are terminal, and `active`
otherwise.

#### Scenario: Mixed terminal and active obligations
- **WHEN** one obligation is collected while a sibling remains pending
- **THEN** aggregate status is partial and both independent states are visible

### Requirement: Hosted financial authority lifecycle
`fiat.stripe.v1` MUST use the shared obligation journal and conditional-escrow
port while the separately operated hosted service remains the sole financial
authority. Marketplace rows MUST contain only opaque settlement references,
public lifecycle/action metadata, condition anchors, canonical fulfillment
references, and opaque receipts; they MUST NOT persist provider identifiers,
Checkout URLs, payment data, credentials, or raw evidence payloads.

#### Scenario: Hosted funding becomes authoritative
- **WHEN** the hosted authority reports the accepted obligation funded
- **THEN** the storefront provisions once, binds one immutable condition
  evidence reference, and only then reports the settlement ready and resumes
  check/collect through the shared worker

#### Scenario: Reclaim races fulfillment
- **WHEN** the buyer reclaims at expiry while fulfillment, satisfied
  evaluation, or collection is reserved or complete
- **THEN** the repository CAS rejects reclaim; pending or false evaluation
  alone does not prevent an otherwise eligible reclaim

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, optional buyer action, optional condition anchor, and opaque durable receipt.

#### Scenario: Hosted materialization requires buyer action
- **WHEN** `fiat.stripe.v1` materialization creates a hosted Checkout action
- **THEN** the runtime persists the opaque hosted reference and public action metadata while the action URL remains transient and service-owned

#### Scenario: Alkahest remains selected
- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

### Requirement: Versioned hosted condition input

A hosted obligation MUST carry exactly one immutable condition descriptor with a unique condition ID, a versioned evaluator kind, a configuration-owned resolver ID where applicable, and canonical demand encoded as either `evm-abi` or `application/jcs+json`. Negotiated condition parameters MUST contain immutable policy inputs only and MUST NOT contain credentials, URLs, RPC endpoints, headers, or signing keys.

#### Scenario: Hosted option contains an unconfigured resolver URL
- **WHEN** the adapter validates a condition whose negotiated parameters contain a caller-supplied resolver URL
- **THEN** materialization fails before buyer payment action is created

### Requirement: Hosted adapter validation and state projection

The `fiat.stripe.v1` adapter MUST accept only buyer-funded, seller-claimed obligations with a positive integer minor-unit amount, lowercase ISO 4217 currency, immutable account reference, expiry, and supported typed condition. Provider `false` MUST remain pending, retryable transport or provider uncertainty MUST enter shared retry handling, and hosted `operator_review` MUST project as `manual_required` without inventing a successful outcome.

#### Scenario: Condition is not currently satisfied
- **WHEN** the hosted authority returns an authoritative false evaluation before expiry
- **THEN** the shared worker retains a pending condition and may check again without collecting or marking terminal failure

#### Scenario: Hosted authority requires operator review
- **WHEN** status reports `operator_review`
- **THEN** marketplace state reports manual intervention and does not collect, reclaim, or guess provider outcome

### Requirement: Fulfillment and reclaim exclusion

Hosted servicing MUST use the shared obligation identity, operation journal, work leases, and compare-and-set transitions. At stored expiry, reclaim MAY reserve only when no fulfillment lease or success, submitted collect/provider transfer, or reserved satisfied evaluation exists. Fulfillment success MUST permanently remove reclaim authority and MUST resume check and collect after restart even when expiry subsequently passes.

#### Scenario: Fulfillment succeeds immediately before expiry
- **WHEN** immutable VM fulfillment commits before the reclaim compare-and-set
- **THEN** reclaim is rejected and restart resumes hosted condition check and collection

#### Scenario: Pending condition reaches expiry without fulfillment success
- **WHEN** no fulfillment lease/success, collect reservation, or satisfied evaluation exists at expiry
- **THEN** reclaim may reserve and the shared lifecycle prevents a later collect reservation

### Requirement: Secret-free fulfillment projection

The VM domain MUST encode only the versioned evidence allowed by the accepted condition. EAS mode MUST send a configured resolver ID and fulfillment UID; portable mode MUST send only the allowlisted proof projection. Generic fulfillment results, tenant credentials, SSH material, connection details, arbitrary provider fields, URLs, and headers MUST NOT enter fulfillment references, hosted requests, settlement rows, logs, or generated fixtures.

#### Scenario: VM fulfillment contains connection credentials
- **WHEN** a condition evidence projection is generated from a successful fulfillment result
- **THEN** credentials and connection fields are absent and a canary test rejects any projection that would include them

## Evidence

- Plan envelopes and lifecycle-universal fields:
  `core/src/market_core/schemas.py` and `kit/alkahest/tests/unit/test_plans.py`.
- Stable obligation identity, operation journals, migration/backfill, work
  leases, compare-and-swap transitions, and aggregate status:
  `core/storefront/src/core_storefront/{settlement_lifecycle,settlement_runtime,sqlite_client,sqlite_migrations}.py`.
- Restart, uncertain acknowledgement, payer/claimant direction, partial
  outcomes, and collect/reclaim exclusion:
  `core/storefront/tests/unit/test_settlement_{runtime,obligation_persistence}.py`.
- Exact interval conservation and seller-funded bond policy:
  `kit/alkahest/src/market_alkahest/plans.py` and
  `kit/alkahest/tests/unit/test_plans.py`.
- Signed heartbeat authentication and persistence:
  `core/storefront/tests/unit/test_heartbeats.py`.
- Alkahest mechanism dispatch and claim hooks:
  `kit/alkahest/tests/unit/test_claims.py` and `test_claim_hooks.py`.
