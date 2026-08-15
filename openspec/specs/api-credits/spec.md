# API Credits Specification

## Purpose

Define the authority, negotiation, quota, issuance, settlement, and online-consumption contract for prepaid access to a named API service.

## Requirements

### Requirement: Versioned API-credits vocabulary
The API-credits domain MUST validate listings, round-zero provision intent, negotiated terms, and fulfillment results against the `api_credits.v1` domain contract. Provision intent MUST use version `1`, request a positive integer quantity, and select either a new key or an existing key identified by `key_id`.

#### Scenario: Invalid provision intent is received
- **WHEN** provision intent has another kind or version, a quantity below one, or existing-key mode without `key_id`
- **THEN** the domain rejects it before policy or settlement processing

### Requirement: Quota-backed publication
An API-credits listing MUST identify a named service and an authoritative quota resource. Publication from quota MUST require that resource to exist with available capacity. Reconciliation MUST close an open listing when authoritative availability reaches zero and MAY reopen it when availability later becomes positive; an unavailable authority MUST preserve the last complete listing state rather than be interpreted as zero.

#### Scenario: Quota is exhausted and later replenished
- **WHEN** reconciliation observes zero available units for an open listing and later observes at least one available unit
- **THEN** it closes the listing and subsequently republishes it from the new authoritative view

#### Scenario: Quota authority is unavailable
- **WHEN** reconciliation cannot obtain an authoritative availability view
- **THEN** it neither closes nor reopens the listing based solely on that failure

### Requirement: Quantity-scaled pricing
API-credits negotiation MUST interpret an advertised escrow rate as a per-credit-unit rate and compute the scalar reference payment as quantity multiplied by that rate in payment base units. Seller policy MUST evaluate offers against the same quantity-scaled reference amount. A hidden-reserve listing MUST have an operator-configured minimum price before it can accept an offer.

#### Scenario: Buyer requests several credits
- **WHEN** a buyer requests three credits from a listing whose accepted unit rate is 100 base units
- **THEN** buyer and seller policy use 300 base units as the scalar reference payment

### Requirement: Advisory negotiation checks and authoritative issuance
Negotiation-time quota and key checks MUST be advisory guards over captured views. Existing-key negotiation MUST reject known revoked keys, keys owned by another wallet, and unavailable keys while allowing an active unowned key to receive an open top-up. Issuance MUST recheck key status and ownership at the credits service and MUST commit a live quota hold or atomically reserve fresh quota before granting credits.

#### Scenario: Captured quota cannot satisfy the request
- **WHEN** the captured availability is two units and the buyer requests three
- **THEN** negotiation rejects the request without placing a quota hold

#### Scenario: Negotiation view is stale at issuance
- **WHEN** accepted terms reach issuance after their hold expired or key state changed
- **THEN** the credits service repeats authoritative quota and key checks before changing the balance

### Requirement: Idempotent credit issuance
The credits service MUST own API-key hashes, balances, grants, and consumption records. A new key MUST be derived through the issuance operation, store only a hash of its bearer secret, and bind buyer identity when supplied. A credit grant MUST be unique by settlement `escrow_uid`; retrying the same issuance MUST NOT grant credits or reserve quota twice. A retry for an unused newly issued key MAY rotate and return a replacement secret, but a retry after use MUST NOT reveal a bearer secret.

#### Scenario: Issuance is retried
- **WHEN** the same `escrow_uid` is issued more than once
- **THEN** balance and quota change only once while any replacement secret follows the unused-key rule

### Requirement: Finite quota commitment
Issued credits MUST commit finite authoritative quota through an open-ended reservation whose lease end is absent. Consuming credits MUST reduce the key balance without returning units to sellable quota. Capacity becomes sellable again only when the authoritative quota resource is explicitly increased or otherwise released by an owning operation.

#### Scenario: Buyer consumes purchased credits
- **WHEN** requests consume units from an issued key
- **THEN** the key balance decreases while the committed quota remains unavailable for another sale

### Requirement: Verified settlement fulfillment
The API-credits storefront MUST verify accepted settlement evidence before creating an issuance job. A successful job MUST persist the fulfillment reference and buyer credentials, while public fulfillment results MUST omit the bearer secret. If downstream on-chain fulfillment fails after issuance, the storefront MUST attempt compensating balance adjustment and MUST revoke a key newly created by that failed operation.

#### Scenario: Settlement evidence is invalid
- **WHEN** accepted escrow evidence fails verification
- **THEN** the storefront creates neither an issuance settlement row nor a credit grant

#### Scenario: New-key issuance succeeds
- **WHEN** verified settlement produces a successful issuance job
- **THEN** the storefront persists credentials for buyer retrieval and exposes a secret-free public fulfillment result

### Requirement: Online bearer consumption
An API gate MUST parse bearer credentials as `<key_id>.<secret>`, verify them through the credits service, and consume a configured fixed amount for each admitted request. Missing or invalid credentials MUST return unauthenticated status, revoked credentials MUST return forbidden status, and exhausted credentials MUST return payment-required status with purchase guidance. Service-side consumption MUST be idempotent per key when an idempotency key is supplied. Optional middleware caching or batching MUST remain subordinate to the credits service as balance authority.

#### Scenario: Key balance is exhausted
- **WHEN** admitted requests consume the final available units and another request arrives
- **THEN** the next request is rejected as payment required without creating a negative authoritative balance

#### Scenario: Consumption request is retried
- **WHEN** a middleware repeats consumption for one key with the same idempotency key
- **THEN** the credits service charges the balance at most once

### Requirement: Hosted settlement grants are principal-bound and exact once

An accepted hosted API-credit obligation MUST bind the named service, positive
quantity, key mode and optional key ID, canonical buyer and claimant
principals, exact amount and currency, funding profile, expiry, and issuance
condition. The credits authority MUST grant under the deterministic
mechanism-neutral fulfillment identity derived from the obligation, and one
fulfillment identity MUST map to one immutable request digest and one grant.
The marketplace storefront MUST NOT issue before authoritative hosted funding.

#### Scenario: Hosted issuance acknowledgement is lost
- **WHEN** the authority commits a grant but its response is lost
- **THEN** the storefront retrieves that grant by fulfillment identity and does not reserve quota, create a key, or increase balance again

#### Scenario: Existing key belongs to another marketplace principal
- **WHEN** a hosted top-up targets a key owned by a different canonical principal
- **THEN** the credits authority rejects the issuance without changing quota or balance

### Requirement: Hosted issuance evidence is signed, portable, and secret-free

After an exact-once grant commits, the storefront MUST publish a canonical
seller-signed evidence body binding the accepted obligation, fulfillment and
grant identities, service, quantity, key mode/key ID, canonical owner and
claimant, credits-authority attestation, and request/evidence digests. The
configured portable resolver MUST authenticate callers and return that evidence
by digest. Evidence, public settlement state, logs, and hosted payloads MUST NOT
contain the bearer secret, raw API credential, or provider data.

#### Scenario: Evidence resolves for the accepted condition
- **WHEN** the hosted condition evaluator retrieves the signed evidence digest
- **THEN** signature, signer, schema/capability, freshness, condition anchor, owner, service, quantity, key target, and fulfillment identity all match before collection

#### Scenario: Issuance fails before grant commit
- **WHEN** funding is authoritative but the credits authority has no committed grant
- **THEN** no evidence is published, no collection occurs, and eligible reclaim remains available after the accepted deadline
