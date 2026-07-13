# Settlement Servicing Specification

## Purpose

Define mechanism-neutral settlement plans and the long-running servicing lifecycle for obligations, claims, and heartbeats.

## Requirements

### Requirement: Negotiation-settlement-servicing phases
The market flow MUST preserve Terms as the deterministic handoff from negotiation to settlement, materialize Terms into a settlement Plan, and service that Plan to a Receipt as a separate long-running phase.

#### Scenario: Settlement requires later collection
- **WHEN** escrows are materialized but an obligation is not yet collectible
- **THEN** servicing persists and schedules the claim independently of the synchronous settlement call

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

<!-- Provenance: ARCHITECTURE.md “Settlement Lifecycle”; evidence: market_core settlement carriers, core_storefront settlement_lifecycle.py and heartbeats.py, kit/alkahest codecs -->
