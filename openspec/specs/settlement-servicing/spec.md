# Settlement Servicing Specification

## Purpose

Define the implemented mechanism-neutral settlement-plan carrier, persisted claim servicing, and signed heartbeat evidence.

## Requirements

### Requirement: Negotiation-to-plan handoff
Negotiation MUST produce deterministic Terms and the current settlement path MUST carry the materialized obligations as a mechanism-neutral Settlement Plan. Long-running claim collection runs separately from the synchronous settlement request.

#### Scenario: Settlement creates a later claim
- **WHEN** an Alkahest obligation is materialized but is not yet collectible
- **THEN** the storefront persists a claim for the separate claims engine rather than waiting for collection in the settlement request

### Requirement: Mechanism-neutral plan carrier
Core settlement plan and claim carriers MUST express lifecycle-universal fields and carry mechanism-specific data in tagged `{mechanism, params}` envelopes.

#### Scenario: New settlement mechanism is added
- **WHEN** a kit registers codecs for a new mechanism
- **THEN** core persistence and engine control flow can carry its opaque parameters without importing that kit

### Requirement: Durable idempotent claims
The seller claims engine MUST persist each obligation claim, retry transient failures, and avoid duplicate successful collection across restarts.

#### Scenario: Collection succeeds before a restart
- **WHEN** the engine resumes the same claim
- **THEN** it observes the durable terminal state and does not collect twice

### Requirement: Signed heartbeat evidence
The buyer MAY emit signed deal heartbeats while service is healthy; the seller MUST authenticate and persist accepted heartbeats as deal-scoped evidence.

#### Scenario: Heartbeat identity mismatches the deal
- **WHEN** a heartbeat signature is not from the deal's buyer
- **THEN** the seller rejects it without updating claim evidence

### Requirement: Mechanism codecs own chain vocabulary
Alkahest-specific plan, claim, and arbiter encoding MUST live in the Alkahest kit rather than core carriers or engines.

#### Scenario: Claims engine evaluates an Alkahest obligation
- **WHEN** it needs mechanism-specific readiness or collection behavior
- **THEN** it dispatches through the registered Alkahest codec

## Evidence

- Plan envelopes and lifecycle-universal fields: `core/src/market_core/schemas.py` and `kit/alkahest/tests/unit/test_plans.py`.
- Persisted restartable claims and idempotent submission: `core/storefront/tests/unit/test_settlement_lifecycle.py`.
- Signed heartbeat authentication and persistence: `core/storefront/tests/unit/test_heartbeats.py`.
- Alkahest mechanism dispatch and claim hooks: `kit/alkahest/tests/unit/test_claims.py` and `test_claim_hooks.py`.

The code does not currently expose one generic `service(Plan) -> Receipt` contract or engine-driven materialization/reclaim for arbitrary plan shapes. Those are proposed lifecycle work and are not part of this baseline.
