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

### Requirement: Legacy provision wire removal
After every in-repository producer and consumer migrates, the shared client and storefront MUST reject the obsolete flat compute-shaped provision-terms form rather than silently coercing it.

#### Scenario: Legacy client calls updated storefront
- **WHEN** a client submits flat legacy provision fields without a supported domain envelope
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
- **THEN** model dumps and signed negotiation bodies are byte-for-byte equal to the pre-change legacy representation

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

## Evidence

- Synchronous new/continue HTTP behavior and persisted amounts: `domains/vms/storefront/tests/integration/test_negotiate_controller.py`.
- Thread message ordering and terminal detection: `domains/vms/storefront/tests/unit/test_negotiation_thread.py`.
- History reconstruction and policy-chain primitives: `core/storefront/tests/unit/test_negotiation_sync.py`.
- Agreed-term commit behavior: `domains/vms/storefront/tests/services/test_negotiation_service.py`.

The stronger claim that a restart preserves every in-flight continuation path is not independently covered by the cited tests and is therefore not stated as a baseline scenario.
