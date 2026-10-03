# Negotiation Protocol Specification

## Purpose

Define the buyer-driven signed round protocol, deterministic terms derivation, policy hooks, and persisted negotiation state.

## Requirements

### Requirement: Acceptance persists opaque settlement data

Seller acceptance MUST return exact `agreement_bytes` and any mechanism-owned `settlement_data` in the negotiation response and `NegotiationOutcome`. The runtime MUST persist them together in `negotiation_threads` at the acceptance chokepoint. Core MUST carry settlement data opaquely; domain settlement MUST load the accepted mandate by negotiation ID rather than rebuild it from history or current configuration.

#### Scenario: Payment acceptance is resumed

- **WHEN** a buyer or seller resumes an accepted `arkhai.payments.v1` negotiation
- **THEN** it uses the same Agreement bytes and seller-derived mandate stored in `settlement_data`

### Requirement: Buyer-driven synchronous rounds
Negotiation MUST use signed HTTP request/response rounds initiated by the buyer; the seller MUST return its next message inline and MUST NOT require a symmetric push channel.

#### Scenario: Buyer continues a negotiation
- **WHEN** the buyer submits the signed current history to the seller
- **THEN** the seller verifies it, persists the round, and returns the next decision synchronously

### Requirement: Deterministic agreed terms

On acceptance, negotiation MUST produce exactly one Agreement object containing only the accepted deal terms and the identifiers needed to bind them: `negotiation_id`, `listing_id`, `listing_hash`, canonical `buyer` and `seller` principals, the selected settlement `{option_id, mechanism, asset, rates, params}`, opaque buyer `settlement_params`, `amount`, `asset`, `duration_seconds`, explicit `start_utc`, domain-owned `provision_terms`, and `accepted_at`. The seller MUST resolve any requested relative start, including “now”, to `start_utc` at acceptance. The acceptance response MUST preserve the Agreement as exact bytes; both participants MUST retain those bytes and MUST NOT rebuild the Agreement from transcript or accepted terms. Core MUST NOT define a universal Agreement hash; a settlement mechanism defines any hash it requires.

#### Scenario: Seller accepts a proposal

- **WHEN** a round terminates in acceptance
- **THEN** the seller returns one Agreement containing only accepted terms, an exact selected settlement option, and an explicit start time rather than requiring buyer and seller to reduce the message history independently

#### Scenario: Both participants retain the accepted Agreement

- **WHEN** the buyer receives the accept response
- **THEN** buyer and seller retain the exact Agreement bytes from that response and neither reconstructs or reserializes a replacement before settlement

### Requirement: Injectable policy decision
The protocol engine MUST delegate schema-specific per-turn decisions to an injected round policy while retaining transport, authentication, history persistence, stage events, and terminal-state handling in the role shell.

#### Scenario: Policy passes control
- **WHEN** a negotiation middleware returns no decision
- **THEN** the next middleware receives the context; the first returned decision terminates the chain

### Requirement: Protocol state persistence
The seller MUST persist negotiation threads, messages, terminal state, and agreed terms needed to authenticate continuation and inspect negotiation outcomes.

#### Scenario: Buyer continues an existing thread
- **WHEN** a buyer submits a continuation for a persisted nonterminal negotiation
- **THEN** the seller loads the stored thread, appends the next protocol-visible messages, and updates terminal/agreed state as appropriate

### Requirement: Versioned domain provision envelope
Shared buyer and storefront clients MUST carry provision intent in a versioned domain envelope containing domain kind and domain-defined payload, without compute-specific parameters in the shared wire.

#### Scenario: VM buyer opens negotiation
- **WHEN** a VM buyer constructs initial provision intent
- **THEN** the shared client transmits the VM domain kind and VM-owned payload through the generic envelope

#### Scenario: API-credit buyer opens negotiation
- **WHEN** an API-credit buyer constructs initial provision intent
- **THEN** the same shared client transmits the API-credit domain kind and API-credit-owned payload without VM fields

#### Scenario: Envelope kind does not match storefront domain
- **WHEN** a storefront receives provision terms for a different domain kind or unsupported payload version
- **THEN** it rejects the round before policy or settlement processing with an actionable compatibility error

### Requirement: Obsolete provision wire rejection
The shared client and storefront MUST reject the obsolete flat compute-shaped provision-terms form rather than silently coercing it.

#### Scenario: Flat provision request is submitted
- **WHEN** a client submits flat provision fields without a supported domain envelope
- **THEN** the storefront returns a version/shape error and does not begin or continue negotiation

### Requirement: Additive settlement option carriers

Listings and proposals MAY carry ordered `SettlementOption` envelopes containing stable option ID, mechanism, asset, rates, and opaque mechanism parameters. Accepted terms MUST pin the exact advertised option through `SettlementSelection`. Buyer-supplied mechanism inputs such as `payer_account` remain in the selection's opaque `params` and the Agreement's `settlement_params`; they MUST NOT replace seller-owned option parameters. Legacy Alkahest-only acceptance MAY omit a selection. These fields MUST be optional, MUST omit absent or empty values, and MUST NOT reinterpret or replace mechanism-owned values in `params` with universal escrow fields.

#### Scenario: Legacy Alkahest negotiation is serialized

- **WHEN** a listing has no settlement options or selection and represents an Alkahest-only negotiation
- **THEN** model dumps and signed negotiation bodies remain byte-for-byte equal to the canonical Alkahest-only representation without copying escrow fields into a shared option carrier

#### Scenario: Arkhai payment option is advertised

- **WHEN** a listing supports charge-first settlement through `arkhai.payments.v1`
- **THEN** its option is carried in `settlement_options` without rewriting legacy Alkahest escrow fields

### Requirement: Deterministic option identity

A settlement option ID MUST be lowercase SHA-256 over sorted compact canonical JSON of its immutable mechanism, asset, rates, and parameters. Seller acceptance MUST exact-match the selected option against the stored listing option and MUST derive all mechanism-owned values from that stored option rather than buyer-supplied duplicates.

#### Scenario: Buyer changes condition after discovery

- **WHEN** the buyer changes an Alkahest condition in option parameters so the option ID or body no longer matches the stored listing option
- **THEN** seller acceptance fails without creating an accepted Agreement

### Requirement: Uint256-safe negotiation values

Negotiated scalar payment amounts in proposals, rates, accepted obligations, and persisted agreed state MUST remain non-negative integers without precision loss. Canonical JSON wire representations MUST encode uint256-domain values as decimal-digit strings, and persistence MUST round-trip values larger than JSON's safe-integer range and SQLite's signed 64-bit range without rounding or truncation.

#### Scenario: Negotiation uses an 18-decimal token amount

- **WHEN** a proposal contains an amount greater than SQLite's signed 64-bit maximum as a decimal-digit wire value
- **THEN** the seller authenticates and evaluates that exact integer, persists it losslessly, and returns accepted or counterproposal artifacts with the same precision

#### Scenario: Proposal amount is not an unsigned decimal integer

- **WHEN** an amount is negative, fractional, boolean, or otherwise not a non-negative decimal integer
- **THEN** the negotiation rejects it instead of rounding, truncating, or interpreting it through a floating-point value

### Requirement: Principal-bound negotiation history

Every negotiation MUST persist durable ownership by the exact canonical scheme-tagged buyer and seller principals established at opening. Every protocol-visible message MUST preserve its authenticated author's complete principal and role. Each state-changing buyer or administrator request MUST use the shared version 2 body-bound request contract, and seller responses MUST authenticate the seller principal. Accepted Agreements MUST preserve the exact buyer and seller parties from the canonical thread. Address claims in bodies, identifier-only comparisons, provider identifiers, and unsigned query values MUST NOT establish identity, authorship, or ownership.

#### Scenario: Buyer changes its principal mid-thread

- **WHEN** a continuation request is validly signed by a principal other than the thread's authorized buyer and no completed rotation binds it
- **THEN** the seller rejects the round without changing message history, terminal state, or Agreement

#### Scenario: Signed negotiation body is changed

- **WHEN** any identity-bearing or decision-bearing field differs from the body covered by the request proof
- **THEN** the seller rejects the request before policy evaluation or negotiation state mutation

#### Scenario: Administrator advances a negotiation

- **WHEN** an authenticated administrator advances or force-accepts an existing thread
- **THEN** the resulting message records that administrator's exact principal with the administrator role while the thread and any accepted Agreement retain their original buyer and seller principals

#### Scenario: Ed25519 parties agree payment terms

- **WHEN** Ed25519 buyer and seller principals complete deterministic rounds selecting `arkhai.payments.v1`
- **THEN** the Agreement preserves both exact party principals and the settlement selection without requiring EVM addresses

### Requirement: Negotiation identity migration and recovery are deterministic

Address-shaped negotiation parties, message authors, and accepted Terms MUST migrate transactionally to canonical `eip191` principals while preserving negotiation, message, listing, option, settlement-plan, and operation identities. Migration MUST validate the complete owned population before committing and MUST leave the prior state intact when any row is malformed, conflicting, incomplete, or ambiguously owned. Recovery of a persisted thread MUST use its recorded buyer and seller principals and MUST authorize a continuation only for the recorded buyer or a replacement principal bound by a completed rotation.

#### Scenario: Nonterminal thread is recovered after migration

- **WHEN** a valid address-owned negotiation is migrated before its next round and the recorded `eip191` buyer resumes it
- **THEN** the seller continues the same thread and canonical history without replaying prior policy decisions or changing accepted party ownership

#### Scenario: Negotiation identity population is unsafe

- **WHEN** migration encounters a malformed principal, conflicting identity representation, incomplete party population, or ambiguous owner
- **THEN** the migration aborts atomically without leaving mixed address and principal authorization state

### Requirement: Negotiation inherits an immutable listing-domain binding

Opening a negotiation MUST transactionally load the authoritative seller listing and common binding, resolve the exact pre-registered contract, validate the versioned provision envelope with that contract, and persist the thread, canonical parties, opening message, initial domain artifact, trusted site, offering mode, domain identity, and contract version before policy runs. Caller-supplied discriminators are assertions only. Continuation, Terms reduction, and acceptance MUST route from the recorded thread binding.

#### Scenario: Opening matches the VM listing

- **WHEN** a buyer opens a supported VM provision envelope against a VM-bound listing
- **THEN** the new thread copies that exact binding and only the selected VM policy receives the normalized message

#### Scenario: Opening names another domain

- **WHEN** a valid bare-metal envelope is submitted against a VM-bound listing, or any requested mode/domain/version conflicts
- **THEN** the storefront rejects the opening before message persistence, policy, capacity, settlement, or fulfillment effects

#### Scenario: Configuration changes during an accepted thread

- **WHEN** the current registration or listing changes after a thread recorded an exact nonterminal or accepted binding
- **THEN** recovery resolves the recorded contract or blocks that record and never redirects it to the new mapping

### Requirement: Scalar negotiation participation is a mechanism declaration

A settlement mechanism's registration MUST declare whether it negotiates a scalar
amount. For a scalar-declaring mechanism, the existing strict behavior applies,
including rejection of a proposal missing the amount. For a mechanism that declines
the scalar, negotiation MUST proceed take-it-or-leave-it over the published option,
the missing-amount rejection MUST NOT apply, and buyer ordering MUST treat its
listings as priceless.

#### Scenario: A non-scalar mechanism reaches acceptance

- **WHEN** a buyer opens negotiation with a settlement selection for a mechanism that
  declares no scalar and no `fields.amount`
- **THEN** the round is not rejected for a missing amount and the negotiation can
  reach acceptance on the published option's terms

#### Scenario: A scalar mechanism keeps the guard

- **WHEN** a buyer opens negotiation under a scalar-declaring mechanism without an
  amount
- **THEN** the proposal is rejected exactly as today

## Evidence

- Synchronous new/continue HTTP behavior and lossless uint256-domain persistence: `domains/vms/storefront/tests/integration/test_negotiate_controller.py`.
- Thread message ordering, terminal detection, exact message authorship, and uint256-domain storage: `domains/vms/storefront/tests/unit/test_negotiation_thread.py`.
- History reconstruction and policy-chain primitives: `core/storefront/tests/unit/test_negotiation_sync.py`.
- Agreed-term commit and authenticated administrator authorship: `domains/vms/storefront/tests/services/test_negotiation_service.py` and `domains/vms/storefront/tests/integration/test_negotiations_api.py`.
- Transactional principal migration and fail-closed recovery ownership: `core/storefront/tests/unit/test_identity_migrations.py` and `core/buyer/tests/unit/test_identity_recovery.py`.
- Immutable listing-to-thread inheritance, cross-domain rejection, exact contract resolution, and restart binding: `domains/vms/storefront/tests/unit/test_domain_thread_bindings.py`, `test_sync_negotiation_domain.py`, and `core/storefront/tests/unit/test_domain_registry.py`.

The complete live VM/bare-metal restart proof is owned by the multi-domain system lane and remains gated on the production bare-metal contribution.
