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

### Requirement: Additive hosted settlement choice
Listings MAY advertise deterministic `SettlementOption` envelopes beside
legacy Alkahest escrows. Accepted terms MUST pin one exact `SettlementSelection`
and immutable settlement plan without replacing or reinterpreting legacy
escrow fields or signed wire bodies when the additive fields are absent.

#### Scenario: Seller accepts hosted settlement
- **WHEN** the buyer selects an advertised `fiat.stripe.v1` option
- **THEN** the seller exact-matches its canonical option ID, persists the
  accepted plan, and derives one buyer-funded, seller-claimed obligation from
  seller-owned listing and agreement state

### Requirement: Additive settlement option carriers

Listings and proposals MAY carry ordered `SettlementOption` envelopes containing stable option ID, mechanism, asset, rates, and opaque mechanism parameters. Accepted terms MAY carry one `SettlementSelection` containing mechanism, exact option ID, and expiration. These fields MUST be optional, MUST omit absent or empty values, and MUST NOT reinterpret or replace existing Alkahest escrow fields.

#### Scenario: Legacy Alkahest negotiation is serialized
- **WHEN** no settlement options or selection are supplied
- **THEN** model dumps and signed negotiation bodies are byte-for-byte equal to the canonical Alkahest-only representation

#### Scenario: Hosted option is advertised
- **WHEN** a listing supports hosted fiat settlement
- **THEN** the option is carried beside legacy accepted escrows without mutating their values or order

### Requirement: Deterministic option identity

A hosted option ID MUST be lowercase SHA-256 over sorted compact canonical JSON of its immutable mechanism, asset, rates, and parameters. Seller acceptance MUST exact-match the selected option against the stored listing option and MUST derive account, currency, amount, expiry, and condition from that stored option rather than buyer-supplied duplicates.

#### Scenario: Buyer changes condition after discovery
- **WHEN** the selected option ID or body does not exactly match a currently stored listing option
- **THEN** seller acceptance fails without creating an accepted settlement plan

### Requirement: Exact fiat minor-unit settlement

A fiat selection MUST produce one buyer-funded, seller-claimed `SettlementObligation(mechanism="fiat.stripe.v1")` whose integer amount is the accepted price in minor units and whose asset is a lowercase ISO 4217 currency. Zero, negative, fractional, rounded, or inconsistent amounts MUST be rejected before acceptance.

#### Scenario: Accepted price is below one minor unit
- **WHEN** the negotiated rate conversion yields zero minor units
- **THEN** seller acceptance rejects the settlement rather than rounding it up or creating Checkout

#### Scenario: Fiat option is accepted
- **WHEN** exact option matching and current duration/expiry pricing succeed
- **THEN** the accepted plan contains one buyer-funded, seller-claimed hosted obligation with the exact integer amount and typed condition


### Requirement: Uint256-safe negotiation values

Negotiated scalar payment amounts in proposals, rates, accepted obligations, and persisted agreed state MUST remain non-negative integers without precision loss. Canonical JSON wire representations MUST encode uint256-domain values as decimal-digit strings, and persistence MUST round-trip values larger than JSON's safe-integer range and SQLite's signed 64-bit range without rounding or truncation.

#### Scenario: Negotiation uses an 18-decimal token amount

- **WHEN** a proposal contains an amount greater than SQLite's signed 64-bit maximum as a decimal-digit wire value
- **THEN** the seller authenticates and evaluates that exact integer, persists it losslessly, and returns accepted or counterproposal artifacts with the same precision

#### Scenario: Proposal amount is not an unsigned decimal integer

- **WHEN** an amount is negative, fractional, boolean, or otherwise not a non-negative decimal integer
- **THEN** the negotiation rejects it instead of rounding, truncating, or interpreting it through a floating-point value

### Requirement: Principal-bound negotiation history

Every negotiation MUST persist durable ownership by the exact canonical scheme-tagged buyer and seller principals established at opening. Every protocol-visible message MUST preserve its authenticated author's complete principal and role. Each state-changing buyer or administrator request MUST use the shared version 2 body-bound request contract, and seller responses MUST authenticate the seller principal. Accepted Terms and settlement plans MUST preserve the exact buyer and seller parties from the canonical thread. Address claims in bodies, identifier-only comparisons, provider identifiers, and unsigned query values MUST NOT establish identity, authorship, or ownership.

#### Scenario: Buyer changes its principal mid-thread

- **WHEN** a continuation request is validly signed by a principal other than the thread's authorized buyer and no completed rotation binds it
- **THEN** the seller rejects the round without changing message history, terminal state, or Terms

#### Scenario: Signed negotiation body is changed

- **WHEN** any identity-bearing or decision-bearing field differs from the body covered by the request proof
- **THEN** the seller rejects the request before policy evaluation or negotiation state mutation

#### Scenario: Administrator advances a negotiation

- **WHEN** an authenticated administrator advances or force-accepts an existing thread
- **THEN** the resulting message records that administrator's exact principal with the administrator role while the thread and any accepted Terms retain their original buyer and seller principals

#### Scenario: Ed25519 parties agree hosted terms

- **WHEN** Ed25519 buyer and seller principals complete deterministic rounds selecting `fiat.stripe.v1`
- **THEN** both derive the same Terms, settlement plan, and exact party principals without requiring EVM addresses

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

## Evidence

- Synchronous new/continue HTTP behavior and lossless uint256-domain persistence: `domains/vms/storefront/tests/integration/test_negotiate_controller.py`.
- Thread message ordering, terminal detection, exact message authorship, and uint256-domain storage: `domains/vms/storefront/tests/unit/test_negotiation_thread.py`.
- History reconstruction and policy-chain primitives: `core/storefront/tests/unit/test_negotiation_sync.py`.
- Agreed-term commit and authenticated administrator authorship: `domains/vms/storefront/tests/services/test_negotiation_service.py` and `domains/vms/storefront/tests/integration/test_negotiations_api.py`.
- Transactional principal migration and fail-closed recovery ownership: `core/storefront/tests/unit/test_identity_migrations.py` and `core/buyer/tests/unit/test_identity_recovery.py`.
- Immutable listing-to-thread inheritance, cross-domain rejection, exact contract resolution, and restart binding: `domains/vms/storefront/tests/unit/test_domain_thread_bindings.py`, `test_sync_negotiation_domain.py`, and `core/storefront/tests/unit/test_domain_registry.py`.

The complete live VM/bare-metal restart proof is owned by the multi-domain system lane and remains gated on the production bare-metal contribution.
