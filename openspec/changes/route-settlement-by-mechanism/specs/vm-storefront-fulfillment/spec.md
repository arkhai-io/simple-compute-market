## MODIFIED Requirements

### Requirement: Versioned fulfillment context

Before the first recoverable physical mutation, the VM storefront MUST persist a versioned `vm.storefront.fulfillment-context` envelope linked to its negotiation and verified SettlementEvidence. It MUST record the exact normalized fulfillment request, generated target, listing/order references, lease timing and opaque settlement reference without credentials. Payment context MUST NOT be stored as an escrow row. Unknown kinds or versions MUST remain operator-visible and MUST NOT be guessed or silently rewritten.

#### Scenario: Generated VM target is preserved exactly

- **WHEN** the storefront constructs fulfillment context for an accepted VM deal
- **THEN** it generates a non-empty VM target once
- **AND** records that exact target in the versioned fulfillment request
- **AND** sends the same target to physical fulfillment
- **AND** uses the same target when registering the VM lease

#### Scenario: Unsupported context remains visible

- **WHEN** recovery loads an unknown fulfillment-context kind or schema version
- **THEN** it leaves delivery pending and operator-visible
- **AND** does not guess, rewrite or replay the unknown payload

### Requirement: Full settlement convergence ownership

The VM storefront MUST own capacity reservation, physical fulfillment, credential delivery, required lease registration and listing/delivery progress. The selected settlement stage MUST own mechanism-specific attestation, readiness and claim binding; the claims engine retains submission/collection, not physical recovery. Early lease-termination client plumbing remains available without requiring a buyer-facing flow. Common delivery MUST consume evidence and MUST NOT compare mechanism IDs. The VM storefront MUST hold and commit site capacity under the deal's negotiation (`deal_ref.negotiation_id`) whatever the settlement mechanism, so a deal's site reservation is found by its negotiation and carries no settlement reference.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an operator or test looks up the site reservation of a VM deal settled through Alkahest
- **THEN** it finds the reservation by the negotiation its hold names, not by the escrow

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** common delivery records credentials, refreshes capacity, registers the VM lease and updates listing/delivery progress
- **AND** the selected Alkahest continuation reconciles on-chain fulfillment, escrow readiness and settlement claims when applicable
- **AND** every step is safe to revisit after interruption

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces an active VM
- **THEN** common delivery returns the same domain result without creating an escrow claim or choosing a no-chain path by mechanism ID

### Requirement: Foreground and restart convergence

Foreground settlement and restart recovery MUST use the same durable negotiation-scoped evidence, exact delivery context and replay-safe phase boundaries. Unfinished delivery MUST be discoverable by the periodic startup worker, including payment work with no escrow row. Foreground and recovery MUST coordinate with a durable expiring claim; process-local locks MUST NOT be the correctness boundary.

#### Scenario: Concurrent convergence is excluded durably

- **WHEN** a foreground task or worker holds an unexpired processing claim for a delivery
- **THEN** another process does not concurrently converge that delivery
- **AND** an expired claim can be acquired after the previous owner stops making progress

### Requirement: Physical fulfillment resumption

When durable fulfillment identity exists, recovery MUST query that fulfillment directly and MUST NOT schedule or begin a replacement. Nonterminal provider state remains pending; active results MUST be fetched and recorded; provider failure MUST use the existing failure policy. Without fulfillment identity, recovery MUST reuse the persisted exact request and idempotent reservation/scheduling/begin contracts. Settlement evidence MUST be revalidated by its selected stage before protected effects.

#### Scenario: Recovery before fulfillment acceptance

- **WHEN** an unfinished delivery has persisted context but no fulfillment ID
- **THEN** recovery reuses the exact stored request and target
- **AND** reconciles reservation, scheduling and begin-fulfillment through their idempotent contracts

#### Scenario: Recovery after fulfillment acceptance

- **WHEN** an unfinished delivery has a durable fulfillment ID
- **THEN** recovery polls that fulfillment directly
- **AND** does not schedule a replacement resource or begin a second fulfillment

## ADDED Requirements

### Requirement: VM role tables gate evidence-based delivery

VM buyer and seller roles MUST declare their supported settlement stages once and dispatch accepted Agreements through those tables. Each stage MUST verify its authoritative source and supply validated delivery facts in SettlementEvidence. Planners MUST read those facts, not decode payment receipts, compare IDs or require Alkahest token policy for every mechanism.

#### Scenario: Lease encoding differs between stages

- **WHEN** Alkahest and payment stages authorize equivalent VM capacity
- **THEN** each stage supplies its required lease/condition encoding and the shared planner builds the physical request without a mechanism switch

### Requirement: VM evidence and delivery progress are not payment escrows

VM settlement evidence and payment delivery checkpoints/claims MUST be domain-owned negotiation-scoped records, not `escrows` rows with absent or sentinel chain fields. Incompatible evidence/delivery schemas MUST require explicit database reset rather than legacy-row copying or compatibility fallback. Real Alkahest escrow and obligation state MAY remain in their existing owners.

#### Scenario: Payment delivery is pending

- **WHEN** a verified payment is waiting for physical fulfillment
- **THEN** its evidence, immutable context, phase progress and convergence claim are recoverable without any payment escrow row

#### Scenario: Evidence is reused for another accepted state

- **WHEN** the same negotiation evidence is written with a different mechanism, Agreement digest or established settlement reference
- **THEN** the repository rejects the conflicting write before protected delivery

#### Scenario: A fresh VM schema boots

- **WHEN** its introducing migrations bootstrap a new database and rerun
- **THEN** evidence/delivery tables exist idempotently without a copy-then-drop migration

#### Scenario: Verified VM evidence is malformed

- **WHEN** a write proposes verified evidence without a SHA-256 Agreement digest, authoritative source, or supported validated `vm.delivery-facts` version 1 payload
- **THEN** storage refuses before freezing an authoritative record or creating delivery progress
