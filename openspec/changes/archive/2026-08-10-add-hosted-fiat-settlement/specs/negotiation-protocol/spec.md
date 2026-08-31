## ADDED Requirements

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
