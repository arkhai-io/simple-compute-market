## ADDED Requirements

### Requirement: Payment grants are principal-bound and exact once

An accepted `arkhai.payments.v1` Agreement MUST bind service, positive quantity, key mode and optional key ID, canonical buyer and seller, amount, asset, and payment policy. The storefront MUST verify the signed receipt against its persisted mandate first. The credits authority MUST accept `arkhai.payments.v1` and `alkahest.v1` issuance, key each grant by deterministic fulfillment ID, and reject changed reuse against its immutable request digest. Keys, balances, and quota stay authority-owned.

#### Scenario: Issuance acknowledgement is lost

- **WHEN** the authority commits a grant but the storefront did not record its response
- **THEN** retry retrieves or resumes the same grant without creating another key or increasing balance again

#### Scenario: Existing key belongs to another principal

- **WHEN** a top-up targets a key owned by a different canonical principal
- **THEN** the authority rejects issuance without changing quota or balance

### Requirement: Payment progress and credentials remain separate

The storefront MUST re-drive nonterminal payment issuance using the accepted negotiation and deterministic transaction/grant identities. Public payment state MUST omit bearer secrets; buyer credentials MUST be delivered through the authenticated private result boundary. A pending transaction or absent matching receipt MUST authorize no issuance.

#### Scenario: Buyer retries provisioning state

- **WHEN** seller state is nonterminal after a verified payment
- **THEN** settlement resumes or retrieves the same issuance instead of returning pending forever

## MODIFIED Requirements

### Requirement: Idempotent credit issuance
The credits service MUST own API-key hashes, balances, grants, and consumption records. A new key MUST be derived through the issuance operation, store only a hash of its bearer secret, and bind buyer identity when supplied. A credit grant MUST be unique by deterministic fulfillment identity derived from its accepted obligation reference (Alkahest `escrow_uid` or payment negotiation ID); retrying the same issuance MUST NOT grant credits or reserve quota twice. A retry for an unused newly issued key MAY rotate and return a replacement secret, but a retry after use MUST NOT reveal a bearer secret.

#### Scenario: Issuance is retried
- **WHEN** the same deterministic fulfillment identity is issued more than once
- **THEN** balance and quota change only once while any replacement secret follows the unused-key rule

### Requirement: Verified settlement fulfillment
The API-credits storefront MUST verify accepted settlement evidence before authorizing credit issuance. A pending payment progress row MAY precede receipt verification but MUST authorize no grant. A successful job MUST persist the fulfillment reference and buyer credentials, while public fulfillment results MUST omit the bearer secret. If downstream on-chain fulfillment fails after issuance, the storefront MUST attempt compensating balance adjustment and MUST revoke a key newly created by that failed operation.

#### Scenario: Settlement evidence is invalid
- **WHEN** accepted escrow evidence fails verification
- **THEN** the storefront authorizes no issuance and creates no credit grant

#### Scenario: New-key issuance succeeds
- **WHEN** verified settlement produces a successful issuance job
- **THEN** the storefront persists credentials for buyer retrieval and exposes a secret-free public fulfillment result

## REMOVED Requirements

### Requirement: Hosted issuance evidence is signed, portable, and secret-free

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.

### Requirement: Hosted settlement grants are principal-bound and exact once

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
