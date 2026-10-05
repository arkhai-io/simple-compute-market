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

The credits service MUST own API-key hashes, balances, grants and consumption records. A new key MUST be derived through issuance, store only a hash of its bearer secret and bind the canonical owner. A grant MUST be unique by deterministic fulfillment identity derived uniformly from negotiation ID; exact issuance retries MUST NOT grant or reserve quota twice. An unused new-key retry MAY rotate its secret; a retry after use MUST NOT reveal one.

#### Scenario: Issuance is retried

- **WHEN** the same deterministic fulfillment identity and immutable authorization are issued more than once
- **THEN** balance and quota change only once while any replacement secret follows the unused-key rule

### Requirement: Finite quota commitment
Issued credits MUST commit finite authoritative quota through an open-ended reservation whose lease end is absent. Consuming credits MUST reduce the key balance without returning units to sellable quota. Capacity becomes sellable again only when the authoritative quota resource is explicitly increased or otherwise released by an owning operation.

#### Scenario: Buyer consumes purchased credits
- **WHEN** requests consume units from an issued key
- **THEN** the key balance decreases while the committed quota remains unavailable for another sale

### Requirement: Verified settlement fulfillment

The storefront MUST authorize issuance only after its selected settlement stage produces verified SettlementEvidence. Pending progress MUST authorize no grant. Successful delivery MUST persist fulfillment identity and private buyer credentials; public results MUST omit bearer secrets. If a stage's downstream attestation fails after issuance, that stage MUST attempt compensating balance adjustment and revoke a key newly created by the failed operation.

#### Scenario: Settlement evidence is invalid

- **WHEN** accepted escrow or payment evidence fails its stage's verification
- **THEN** the storefront authorizes no issuance and creates no credit grant

#### Scenario: New-key issuance succeeds

- **WHEN** verified settlement produces a successful issuance job
- **THEN** the storefront persists credentials for buyer retrieval and exposes a secret-free public fulfillment result

#### Scenario: Attestation fails after issuance

- **WHEN** the selected Alkahest stage fails its post-issuance on-chain fulfillment
- **THEN** its continuation attempts balance compensation and new-key revocation without making common issuance compare mechanism IDs

### Requirement: Online bearer consumption
An API gate MUST parse bearer credentials as `<key_id>.<secret>`, verify them through the credits service, and consume a configured fixed amount for each admitted request. Missing or invalid credentials MUST return unauthenticated status, revoked credentials MUST return forbidden status, and exhausted credentials MUST return payment-required status with purchase guidance. Service-side consumption MUST be idempotent per key when an idempotency key is supplied. Optional middleware caching or batching MUST remain subordinate to the credits service as balance authority.

#### Scenario: Key balance is exhausted
- **WHEN** admitted requests consume the final available units and another request arrives
- **THEN** the next request is rejected as payment required without creating a negative authoritative balance

#### Scenario: Consumption request is retried
- **WHEN** a middleware repeats consumption for one key with the same idempotency key
- **THEN** the credits service charges the balance at most once

### Requirement: Payment grants are principal-bound and exact once

The accepted Agreement MUST bind service, positive quantity, key mode and optional key ID, canonical parties, amount, asset and selected policy. The storefront's stage MUST verify authoritative settlement evidence before creating an immutable issuance authorization. The credits authority MUST key grants by negotiation-derived fulfillment identity and reject changed reuse against its request digest without recognizing settlement mechanisms. Key ownership, balance and quota remain authority-owned.

#### Scenario: Issuance acknowledgement is lost

- **WHEN** the authority commits a grant but the storefront did not record its response
- **THEN** retry retrieves or resumes the same grant without creating another key or increasing balance again

#### Scenario: Existing key belongs to another principal

- **WHEN** a top-up targets a key owned by a different canonical principal
- **THEN** the authority rejects issuance without changing quota or balance

### Requirement: Payment progress and credentials remain separate

The storefront MUST re-drive nonterminal issuance using accepted negotiation, verified evidence and deterministic grant identity. Public progress MUST omit bearer secrets; credentials MUST use authenticated private results. Pending or unverified settlement MUST authorize no issuance. Progress and re-drive MUST read evidence and domain state rather than compare mechanism IDs or treat an escrow-shaped row as authorization.

#### Scenario: Buyer retries provisioning state

- **WHEN** seller state is nonterminal after verified settlement
- **THEN** settlement resumes or retrieves the same issuance instead of returning pending forever

### Requirement: API-credit role tables own settlement dispatch

The API-credit buyer and seller MUST each compose one supported-mechanism table. Buy, accepted-run settlement, seller acceptance hooks and seller settlement MUST use the corresponding entry. Mechanism-specific option, mandate, expiry and post-issuance behavior MUST stay inside entries rather than controllers, negotiation orchestration or common credit issuance.

#### Scenario: Both payment and Alkahest are supported

- **WHEN** accepted API-credit Agreements select either supported mechanism
- **THEN** the same role declaration selects its stage and common issuance receives verified evidence without a mechanism switch

### Requirement: Credits service consumes issuance authorization only

The credits service MUST receive the storefront's existing authenticated immutable issuance command, not raw settlement evidence, a mechanism ID or an escrow reference. The command MUST bind negotiation-derived fulfillment identity, canonical owner, service, quota resource, quantity, key target and request digest. The service MUST validate identity/digest and repeat authoritative quota and key checks before granting.

#### Scenario: A new settlement mechanism authorizes the same purchase

- **WHEN** its storefront stage produces verified evidence and constructs a valid authorized issuance command
- **THEN** the credits service commits the grant without importing that mechanism, parsing its evidence or updating a mechanism allowlist

#### Scenario: Authorization is changed on replay

- **WHEN** an existing fulfillment identity is reused with changed owner, service, resource, quantity or key target
- **THEN** the authority rejects the conflict before key, balance or quota mutation

#### Scenario: Operational quota hold changes

- **WHEN** an expired negotiation hold is replaced while the immutable authorization intent is unchanged
- **THEN** issuance rechecks authoritative capacity and retains the same grant identity and intent digest

### Requirement: API-credit settlement evidence has independent persistence

The storefront MUST persist accepted-Agreement-bound SettlementEvidence and negotiation-scoped issuance progress independently of escrow rows, signed issuance evidence and private credentials. Mechanism, Agreement digest and an established reference MUST be conflict-protected; verified status and source/delivery payload MUST NOT be downgraded or replaced. Incompatible evidence/grant schemas MUST require explicit database reset; startup MUST NOT adopt old grants or translate old issuance payloads.

#### Scenario: Pending evidence exists

- **WHEN** a pending settlement record exists without verified authoritative source evidence
- **THEN** it authorizes no grant and its progress remains retryable without creating a payment escrow

#### Scenario: A verified grant is published as issuance evidence

- **WHEN** delivery produces signed issuance evidence for an Alkahest condition
- **THEN** it is stored separately from the pre-issuance settlement gate and contains no bearer secret

#### Scenario: A fresh credits schema is created

- **WHEN** the introducing storefront and service migrations bootstrap empty databases
- **THEN** evidence/progress and negotiation-derived grant identities exist without copying legacy escrow/grant populations

#### Scenario: Verified receipt recovery survives unavailable polling

- **WHEN** a payment grant acknowledgement is lost after verified evidence was persisted and payment polling is unavailable
- **THEN** the stage revalidates the stored signed receipt and resumes the same issuance without replacing verified evidence with pending state

#### Scenario: Prepared Alkahest delivery is issued

- **WHEN** preparation has verified the authoritative escrow and saved matching delivery facts
- **THEN** delivery consumes those facts without a second preparation inside terminal failure handling

