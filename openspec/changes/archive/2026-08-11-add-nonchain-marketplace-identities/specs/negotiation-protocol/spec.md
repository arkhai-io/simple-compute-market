## ADDED Requirements

### Requirement: Principal-bound negotiation history

Every negotiation MUST persist the buyer and seller as canonical scheme-tagged principals, authenticate each state-changing round with the shared body-bound request contract, and bind accepted Terms to those exact parties. Buyer-address body fields and identifier-only comparisons MUST NOT establish identity or ownership.

#### Scenario: Buyer changes its principal mid-thread

- **WHEN** a continuation request is validly signed by a principal other than the thread's authorized buyer and no completed rotation binds it
- **THEN** the seller rejects the round without changing message history, terminal state, or Terms

#### Scenario: Ed25519 parties agree hosted terms

- **WHEN** Ed25519 buyer and seller principals complete deterministic rounds selecting `fiat.stripe.v1`
- **THEN** both derive the same Terms, settlement plan, and exact party principals without requiring EVM addresses

### Requirement: Negotiation identity migration is deterministic

Existing address-shaped negotiation parties, messages, and accepted Terms MUST migrate to canonical `eip191` principals while preserving negotiation, message, listing, option, and settlement-plan identities. An unsafe or incomplete population MUST abort the migration rather than infer a different party.

#### Scenario: Nonterminal thread is upgraded

- **WHEN** a valid address-owned negotiation is migrated before its next round
- **THEN** the same `eip191` buyer can continue the same thread under the new signature version without replaying prior policy decisions
