# Negotiation Protocol Specification

## Purpose

Define the buyer-driven signed round protocol, deterministic terms derivation, policy hooks, and persisted negotiation state.

## Requirements

### Requirement: Buyer-driven synchronous rounds
Negotiation MUST use signed HTTP request/response rounds initiated by the buyer; the seller MUST return its next message inline and MUST NOT require a symmetric push channel.

#### Scenario: Buyer continues a negotiation
- **WHEN** the buyer submits the signed current history to the seller
- **THEN** the seller verifies it, persists the round, and returns the next decision synchronously

### Requirement: Deterministic agreed terms
Both participants MUST derive the same agreed Terms from the same canonical message history before settlement.

#### Scenario: Seller accepts a proposal
- **WHEN** a round terminates in acceptance
- **THEN** the seller echoes the canonical confirmed message so buyer and seller histories reduce to identical Terms

### Requirement: Injectable policy decision
The protocol engine MUST delegate schema-specific per-turn decisions to an injected round policy while retaining transport, authentication, history persistence, stage events, and terminal-state handling in the role shell.

#### Scenario: Policy passes control
- **WHEN** a negotiation middleware returns no decision
- **THEN** the next middleware receives the context; the first returned decision terminates the chain

### Requirement: Protocol state persistence
The seller MUST persist negotiation threads, messages, terminal state, and agreed terms needed to authenticate continuation and inspect negotiation outcomes.

#### Scenario: Process restarts between rounds
- **WHEN** a buyer continues a nonterminal persisted thread after restart
- **THEN** the seller validates continuation against the stored transcript rather than accepting an unrelated history

<!-- Provenance: ARCHITECTURE.md “What the core owns”, storefront negotiation sections; evidence: core/storefront sync negotiation implementation and focused negotiation tests -->
