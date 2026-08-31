## ADDED Requirements

### Requirement: Durable independent obligation lifecycle

Settlement servicing MUST assign stable identity to every plan obligation and durably process materialization, condition checking, collection, and reclaim independently for both payer directions. Retries and restart MUST resume from recorded state without duplicating mechanism effects, and aggregate plan status MUST preserve partial outcomes.

#### Scenario: Plan contains several obligations

- **WHEN** an accepted plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized and serviced under its own identity rather than selecting only the first obligation

#### Scenario: One obligation fails

- **WHEN** one obligation fails or requires manual repair after siblings complete
- **THEN** completed sibling state remains durable and aggregate status identifies the failed obligation without replaying completed effects

#### Scenario: Servicing restarts

- **WHEN** a worker restarts after uncertain mechanism acknowledgment
- **THEN** stable idempotency and persisted attempt/receipt state converge without duplicate materialization, collection, or reclaim

### Requirement: Interval escrow and penalty-bond policies

The settlement policy layer MUST be able to generate deterministic interval escrows and explicit seller-funded penalty bonds as independently serviced obligations. Generated values MUST conserve the accepted totals and preserve payer/claimant direction.

#### Scenario: Total is divided into intervals

- **WHEN** policy materializes an accepted total across a deterministic interval schedule
- **THEN** interval amounts plus deterministic remainder equal the accepted total exactly

#### Scenario: Seller penalty bond is required

- **WHEN** accepted terms include a seller-funded penalty bond
- **THEN** the plan identifies the seller as payer, the eligible counterparty as claimant, and services the bond independently from buyer payment escrows
