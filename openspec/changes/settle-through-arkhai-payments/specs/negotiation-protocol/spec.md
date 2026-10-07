## REMOVED Requirements

### Requirement: Additive hosted settlement choice

**Reason**: The hosted Stripe choice beside legacy Alkahest escrows is superseded by mechanism-neutral settlement options and one accepted Agreement.

**Migration**: Publish Alkahest escrow terms inside its option parameters and use the accepted Agreement as the input to the selected settlement stage.

### Requirement: Exact fiat minor-unit settlement

**Reason**: The requirement derives a `fiat.stripe.v1` obligation and Checkout amount, both of which are removed.

**Migration**: `arkhai.payments.v1` derives its `once` part from the agreed amount and asset in the Agreement.

## MODIFIED Requirements

### Requirement: Deterministic agreed terms

On acceptance, negotiation MUST produce exactly one Agreement object containing only the accepted deal terms and the identifiers needed to bind them: `negotiation_id`, `listing_id`, `listing_hash`, canonical `buyer` and `seller` principals, the selected settlement `{option_id, mechanism, params}`, `amount`, `asset`, `duration_seconds`, explicit `start_utc`, domain-owned `provision_terms`, and `accepted_at`. The seller MUST resolve any requested relative start, including “now”, to `start_utc` at acceptance. The acceptance response MUST preserve the Agreement as exact bytes; both participants MUST retain those bytes and MUST NOT rebuild the Agreement from transcript or accepted terms. Core MUST NOT define a universal Agreement hash; a settlement mechanism defines any hash it requires.

#### Scenario: Seller accepts a proposal

- **WHEN** a round terminates in acceptance
- **THEN** the seller returns one Agreement containing only accepted terms, an exact selected settlement option, and an explicit start time rather than requiring buyer and seller to reduce the message history independently

#### Scenario: Both participants retain the accepted Agreement

- **WHEN** the buyer receives the accept response
- **THEN** buyer and seller retain the exact Agreement bytes from that response and neither reconstructs or reserializes a replacement before settlement

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
