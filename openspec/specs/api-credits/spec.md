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
An API-credits listing MUST identify a named service and an authoritative quota resource. Publication from quota MUST require that resource to exist with available capacity, and MUST resolve the backing the resource's pool declares from the credits service's resource-pool projection, which carries each pool's declarations. Listing creation MUST record the listing's immutable durable binding — site, offering mode, quota resource, pool, domain identity and version, and backing — and every capacity effect, reconciliation, and recheck MUST build the listing's binding from that record, never from the published listing. Listing creation MUST resolve the listing's settlement options from the settlement clauses the operator submits, or from the storefront's configured defaults when none are submitted, and a pool whose backing leaves none of them for the domain to publish MUST yield no listing. Reconciliation MUST close an open capacity-backed listing when authoritative availability reaches zero and MAY reopen it when availability later becomes positive, but only while its quota resource is still in its bound pool and that pool declares the listing's bound backing; an unavailable authority MUST preserve the last complete listing state rather than be interpreted as zero. Every reconciliation pass, whatever capacity event triggered it, MUST also close any open listing, backed or not, whose quota resource is no longer in its bound pool, or whose bound pool is unresolvable, disabled, no longer advertises `api_credits`, or declares a backing other than the listing's bound backing; a site whose pools cannot be read MUST close nothing. A pool declaration changed without a capacity event closes its listings on the next reconciliation pass, and the listing-source check refuses them until then. The storefront MUST refuse to start against a database holding a listing with no durable binding, naming that a fresh database is required.

#### Scenario: Quota is exhausted and later replenished
- **WHEN** reconciliation observes zero available units for an open capacity-backed listing and later observes at least one available unit
- **THEN** it closes the listing and subsequently republishes it from the new authoritative view

#### Scenario: Quota authority is unavailable
- **WHEN** reconciliation cannot obtain an authoritative availability view
- **THEN** it neither closes nor reopens the listing based solely on that failure

#### Scenario: An open listing's source changes while quota remains
- **WHEN** a reconciliation pass finds an open listing's quota resource moved to another pool, even one declaring the same backing, or its bound pool declaring another backing, while the resource still has available units
- **THEN** the listing closes, and it is not reopened while that mismatch holds

#### Scenario: A listing is created
- **WHEN** an operator creates a listing for a quota resource in a backed pool
- **THEN** the listing and its durable binding, recording the pool's declared backing, are stored together before registry publication

#### Scenario: Two listings share a quota resource
- **WHEN** an operator creates a second listing over a quota resource that already has an open listing
- **THEN** each listing records its own durable binding, both naming that quota resource as their source

#### Scenario: A listing is created with settlement clauses
- **WHEN** an operator creates a listing and names its settlement clauses
- **THEN** the listing's settlement options are resolved from those clauses rather than the configured defaults

#### Scenario: A database predates listing bindings
- **WHEN** the storefront starts against a database holding a listing with no durable binding
- **THEN** it refuses to start and names the listing and the fresh-database remedy

### Requirement: Quantity-scaled pricing
API-credits negotiation MUST interpret an advertised escrow rate as a per-credit-unit rate and compute the scalar reference payment as quantity multiplied by that rate in payment base units. Seller policy MUST evaluate offers against the same quantity-scaled reference amount. A hidden-reserve listing MUST have an operator-configured minimum price before it can accept an offer.

#### Scenario: Buyer requests several credits
- **WHEN** a buyer requests three credits from a listing whose accepted unit rate is 100 base units
- **THEN** buyer and seller policy use 300 base units as the scalar reference payment

### Requirement: Advisory negotiation checks and authoritative issuance
Negotiation-time quota and key checks MUST be advisory guards over captured views. The quota check MUST compare a requested quantity with captured availability only for a listing whose backing is bounded by availability, and MUST report itself not applicable otherwise. Existing-key negotiation MUST reject known revoked keys, keys owned by another wallet, and unavailable keys while allowing an active unowned key to receive an open top-up. Issuance MUST recheck key status and ownership at the credits service and MUST commit a live quota hold or atomically reserve fresh quota before granting credits.

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

The API-credit buyer and seller MUST each compose one supported-mechanism table. Buy, standalone negotiation (including `--from`), accepted-run settlement, seller acceptance hooks and seller settlement MUST use the corresponding entry. Mechanism-specific option, mandate, expiry and post-issuance behavior MUST stay inside entries rather than controllers, negotiation orchestration or common credit issuance.

#### Scenario: Both payment and Alkahest are supported

- **WHEN** accepted API-credit Agreements select either supported mechanism
- **THEN** the same role declaration selects its stage and common issuance receives verified evidence without a mechanism switch

#### Scenario: Payment-only standalone negotiation

- **WHEN** `market credits negotiate` selects an advertised payment option
- **THEN** its buyer entry supplies the payer account and unscaled payment prices without requiring wallet, chain or token inputs
- **AND** the run retains exact Agreement bytes and settlement data for accepted-run settlement

#### Scenario: Standalone negotiation resumes

- **WHEN** an interrupted round loop resumes after fresh mechanism admission changes
- **THEN** it retains the recorded selection, provision terms and scaled opening/ceiling without reselecting a mechanism or scaling prices again

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

### Requirement: An API-credit listing is rechecked against its source

Before every seller decision in a negotiation round, and before a buyer's or an
administrator's acceptance, the API-credit storefront MUST recheck the listing
against its source: that its quota resource is still declared in the pool its
durable binding records, that the pool is enabled and advertises `api_credits`, and that the pool's backing equals the
listing's bound backing. For a capacity-backed listing it MUST also require at least
one available unit. A source it cannot confirm MUST be refused as retryable. A
buyer's exit MUST NOT be rechecked.

#### Scenario: The pool stops advertising API credits

- **WHEN** a buyer negotiates against a listing whose pool no longer advertises `api_credits`
- **THEN** the seller rejects with a declared-match reason

#### Scenario: The quota resource moves to another pool

- **WHEN** a buyer negotiates against a listing whose quota resource is now declared in a pool other than the one its binding records, even one declaring the same backing
- **THEN** the seller rejects with a declared-match reason

#### Scenario: Quota is exhausted

- **WHEN** a buyer negotiates against a capacity-backed listing whose quota resource has no available unit
- **THEN** the seller rejects with the availability reason

#### Scenario: The credits service cannot be reached

- **WHEN** the listing's source cannot be confirmed
- **THEN** a seller decision that would counter or accept, and any acceptance, is refused as retryable

### Requirement: API-credit system status is the administrator's signed read

The API-credit storefront's system status MUST be read only by its administrator,
through the same signed request and signed response every other administrator route
uses (operation `admin_system_status`, resource `system/status`), so the canonical
storefront client reads it and an unsigned request is refused. Beside its checks,
system status MUST report every lifecycle loop the storefront's loop controller holds,
by name: the loop's state and the outcome of its last cycle, in the shape the other
storefronts report.

#### Scenario: An unsigned status read is refused

- **WHEN** a caller requests the API-credit storefront's system status without the
  administrator's signature
- **THEN** the request is refused as unauthenticated and no status is returned

#### Scenario: The administrator reads every loop's state

- **WHEN** the administrator reads system status through the canonical storefront
  client
- **THEN** the signed response reports every lifecycle loop, the capacity-event
  pollers' sites among them, with its state and its last cycle's outcome

### Requirement: API credits composes the api family kit

The API-credits domain MUST compose the `api` family's vocabulary and kit for
every concern the kit owns — the purchase shape, issuance models and digests,
issuance evidence, the authority's key service and ledger, the storefront's
issuance and settlement composition, the negotiation adapters, the quota listing
binding and publication, the buyer flows, the mechanism stages, and the bearer
gate — and MUST retain no domain-local implementation of any of them. Its
runtime behaviour — wire shapes, authentication roles and operation names,
refusal status codes and error bodies, digests, database schema and migration
history, environment prefixes and settings keys, and its service's distribution
name, image, entry point, and version response — MUST be unchanged by that
composition, each held to a recorded baseline. The retirement of the
`arkhai-apicredits-middleware` Python distribution is a package and import
break, not a behaviour change, and every repository consumer of it MUST import
the gate library instead.

#### Scenario: A grant issued before the kit is read after it

- **WHEN** the family authority, composed by the API-credits service root, reads
  a grant and its request digest written by the pre-kit service
- **THEN** it recomputes the same fulfillment identity and digest and accepts an
  exact retry without a second grant

#### Scenario: A baseline is diffed

- **WHEN** a slice lands and the recorded baselines — route surface and OpenAPI
  document, authentication roles and operation names, refusal status codes and
  error bodies, environment variables and settings keys, schema and migration
  history, version response — are diffed against the service and storefront
- **THEN** every diff is empty

#### Scenario: Upgrade and rollback against a retained database

- **WHEN** the kit-composed service image starts over a copy of a pre-kit
  database, and the pre-kit image then starts over a database the kit-composed
  image has written
- **THEN** both start, serve the same routes, and read every row, so upgrade
  and rollback are each a change of image and configuration against the
  retained database

#### Scenario: A domain-local copy is sought

- **WHEN** the API-credits packages are searched for an issuance client, a
  digest function, a key service, a settlement stage, or a gate of their own
- **THEN** none is found; each is imported from a `domains/api` distribution

#### Scenario: A middleware consumer is sought

- **WHEN** the repository is searched for the `apicredits_middleware` Python
  package or the `arkhai-apicredits-middleware` Python distribution
- **THEN** no consumer remains; the sample app, the service's integration
  tests, the Python conformance runner, the READMEs, the cookbook, the
  workflows, and the Makefiles name the gate library, while the TypeScript and
  Rust gates under `domains/apicredits/middleware/` keep their own package
  names
