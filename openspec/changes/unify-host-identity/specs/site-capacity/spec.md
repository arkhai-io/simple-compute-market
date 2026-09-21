## ADDED Requirements

### Requirement: A capacity declaration names the host it is delivered through

A capacity declaration MUST name the host its capacity is delivered through as a
`host_id` field of the declaration, not as one of its attributes, and at most one
declaration MAY name a given host. A registration naming a host another declaration
names MUST be refused. Execution references and a reservation's claim facts MUST
take the host from that field.

#### Scenario: A second declaration names a held host

- **WHEN** a declaration is registered with a `host_id` another declaration names
- **THEN** the registration is refused as a conflict and neither declaration changes

#### Scenario: A reservation is bound to a host

- **WHEN** a reservation is admitted against a declaration that names a host
- **THEN** its execution reference carries that declaration's `host_id`

## MODIFIED Requirements

### Requirement: Storefront capacity-claim identity
VM compute listings MUST normalize surrounding whitespace and carry at least one valid `pool_id` or `resource_id`. Every supplied identity MUST begin with an alphanumeric character, contain only letters, digits, `.`, `_`, `:`, or `-`, and contain at most 128 characters. A pool-only listing produces a pool-scoped reservation claim. A listing carrying `resource_id`, whether alone or with `pool_id`, produces a resource-specific claim and excludes `pool_id`. Ordinary pool-scoped claims MUST NOT require or select a `host_id` or `resource_id`.

Claim construction MUST reject a missing, empty, or malformed settlement order and any extracted claim lacking both identities before probing or reserving capacity. Stored listings that violate the identity invariant MUST fail closed on publication or republication. Resuming such a listing MUST return an actionable conflict before changing pause state or contacting a registry; the seller-authenticated close operation MUST remain available without implicit identity backfill or automatic unpublication.

#### Scenario: Pool-only listing creates an ordinary reservation
- **WHEN** a buyer reserves through a listing carrying `pool_id` without `resource_id`
- **THEN** the claim carries `pool_id` and capacity/shape attributes without requiring or selecting a specific host or resource

#### Scenario: Resource-only listing creates a specific reservation
- **WHEN** a buyer reserves through a listing carrying `resource_id` without `pool_id`
- **THEN** the claim carries the explicit `resource_id` and does not require pool-scoped matching

#### Scenario: Listing carries both capacity identities
- **WHEN** a listing carries both `pool_id` and `resource_id`
- **THEN** the claim carries `resource_id` and drops `pool_id`

#### Scenario: Listing carries neither capacity identity
- **WHEN** a compute listing is created without `pool_id` or `resource_id`
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Listing carries a malformed capacity identity
- **WHEN** a supplied identity is empty, whitespace-only, malformed, or too long
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Settlement order is absent or malformed
- **WHEN** VM fulfillment receives no valid non-empty settlement order
- **THEN** fulfillment fails before probing or reserving capacity rather than constructing an unscoped claim

#### Scenario: Legacy-invalid listing is resumed
- **WHEN** an operator resumes a stored listing that lacks a valid capacity identity
- **THEN** the storefront returns an actionable conflict without changing pause state or contacting a registry

#### Scenario: Legacy-invalid listing is explicitly closed
- **WHEN** the operator invokes the seller-authenticated close operation after the validation conflict
- **THEN** the storefront removes it from active registry discovery without inventing a capacity identity

### Requirement: Requested offering mode is explicit and bounded by the pool

Every capacity probe and reservation claim MUST carry a non-empty canonical `offering_mode` naming the requested offering mode, and that key MUST be required. It is the same value a Resource Pool declares as deliverable, the same value the durable listing binding records, and the same value the published listing carries; no surface may name it `executor_kind`, `offering_type`, or `virtualization_type`. The site authority MUST persist that exact value on the Capacity Reservation and MUST NOT infer it from `host_id`, `physical_host_id`, resource kind, market name, matched-resource attributes, or any default. A matching Resource Pool MUST currently declare the requested mode before a new hold is created.

The claim's site-inventory discriminator remains a separate field and a separate axis. Naming the offering mode consistently MUST NOT merge the two.

`executor` MUST NOT be used as vocabulary for the offering mode, for the machine, or for the delivery handler. The machine is a host, the handler is a provider, and the mode is an offering mode.

Legacy reservations, settlement assignments, and executor jobs that predate the field MUST be backfilled only when durable request, settlement, provider-input, or executor-reference evidence proves exactly one mode. A reservation persisted under the retired key MUST be migrated to the settled one rather than read through a compatibility mapping, so that a search for the retired name is trustworthy evidence no surface still produces it. An active row with no proof or conflicting proof MUST be quarantined from execution; a completed row keeps its terminal lifecycle state while recording the quarantine. A settlement or request identity that conflicts with an already explicit reservation identity is schema drift, not a precedence choice.

#### Scenario: Claim omits the requested mode

- **WHEN** a capacity probe or reservation claim omits `offering_mode`
- **THEN** the site authority rejects it before matching resources and does not infer `vm` from a matched resource

#### Scenario: Claim names the requested mode under a retired key

- **WHEN** a capacity probe or reservation claim carries the requested mode under `executor_kind`
- **THEN** the claim is treated as carrying no offering mode and is refused

#### Scenario: Pool does not declare the requested mode

- **WHEN** a Physical Resource matches the requested shape but its Resource Pool does not declare the claim's offering mode
- **THEN** reservation is refused with the mode and pool identified before a Capacity Reservation or debit exists

#### Scenario: Legacy identity has one durable proof

- **WHEN** a legacy reservation has no recorded offering mode and durable provider or placement fields prove exactly one mode
- **THEN** migration records that mode on the reservation and propagates it to its settlement and executor job

#### Scenario: Legacy identity is unproved or conflicting

- **WHEN** a live legacy reservation or executor job has no single provable mode
- **THEN** migration moves it to the durable unmanaged or failed quarantine path without selecting `vm` or another fallback

### Requirement: Cross-mode physical accounting
Shareable VM slices and exclusive bare-metal allocations referring to the same physical host MUST conflict according to allocation mode before executor work starts.

A capacity declaration carries the fields this accounting reads — `physical_host_id` and `allocation_mode` — at the top level of its attributes and nowhere else. A domain's publication settings MUST NOT repeat them, so the value the site authority accounts with is the only value there is.

#### Scenario: VM slice is held
- **WHEN** an exclusive bare-metal reservation targets the same physical host
- **THEN** the site ledger rejects the exclusive reservation

#### Scenario: A bare-metal declaration is registered
- **WHEN** a bare-metal declaration names its physical machine and allocation mode
- **THEN** both are top-level attributes, and its publication settings carry neither

### Requirement: Capacity accounting is private to the site authority
The site authority SHALL account reservable capacity with `CapacityBucket` rows and SHALL store each active reservation's current backing in `CapacityReservationDebit`. A storefront-facing capacity reservation SHALL NOT expose a bucket identifier or backing physical-resource identifier. This extends to domain-specific physical-placement fields carried on the reservation (for example the `host_id` a reservation's execution reference carries), not only the site authority's own generic accounting identifiers -- any field that identifies which concrete physical resource is serving a reservation is a backing physical-resource identifier for the purposes of this requirement, regardless of which domain named it. Scheduling MAY atomically replace the current debit when it selects a different eligible bucket.

#### Scenario: Storefront reads a capacity reservation
- **WHEN** a storefront reads an admitted reservation
- **THEN** it receives lifecycle state and reserved dimensions without private bucket or backing-resource identity
