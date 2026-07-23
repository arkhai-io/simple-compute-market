## ADDED Requirements

### Requirement: Complete bare-metal seller lifecycle

A bare-metal storefront MUST interpret bare-metal listings, messages, agreed terms, settlement materialization, receipts, and access results only through its injected domain contract. It MUST translate an accepted agreement into scheduling and fulfillment at the provisioning site selected by the Capacity Reservation and MUST reclaim through the recorded fulfillment and executor identity.

#### Scenario: Bare-metal agreement is fulfilled

- **WHEN** a buyer and bare-metal storefront accept valid terms and settlement is verified
- **THEN** the storefront schedules exclusive capacity at the reservation's selected site, starts bare-metal fulfillment, and exposes a normalized bare-metal receipt and result without using VM models

#### Scenario: Bare-metal request fails domain validation

- **WHEN** a listing, message, terms payload, or result violates the bare-metal domain schema
- **THEN** the storefront rejects that payload without coercing it through VM semantics or a generic fallback

#### Scenario: Bare-metal agreement is torn down

- **WHEN** an operator or lifecycle transition ends a fulfilled bare-metal agreement
- **THEN** the storefront requests teardown through the recorded fulfillment and bare-metal executor identity and does not release capacity until authoritative teardown policy permits it

### Requirement: Truthful pre-fulfillment seller protocol

Before selected-site fulfillment is composed, the runnable bare-metal storefront MUST expose listing and negotiation operations, durable commercial settlement verification, health, and persistent operator pause state without claiming that provisioning or access delivery is available. Settlement MUST use the terms accepted during negotiation and MUST NOT accept replacement access or routing input.

#### Scenario: Commercial settlement is verified before fulfillment is composed

- **WHEN** a buyer settles a successfully negotiated bare-metal agreement and escrow verification succeeds
- **THEN** the storefront durably reports `settlement_verified` with fulfillment unavailable and returns no provisioning job, credential, receipt, or access result

#### Scenario: Settlement is retried

- **WHEN** the same buyer retries an identical verified settlement
- **THEN** the storefront returns the existing verification result without duplicating state

#### Scenario: Storefront is paused and restarted

- **WHEN** an authenticated operator pauses the storefront and its process restarts
- **THEN** the paused state remains active and new negotiations are rejected until an authenticated resume operation

### Requirement: Trusted bare-metal resource projections

A provisioning site that supports specific-resource bare-metal publication MUST expose an operator-enabled complete projection generation in which each eligible resource carries distinct `physical_resource_id`, `physical_host_id`, and executor-local `machine_id` values together with authoritative availability, allocation mode, access methods, capacity, and allowlisted capabilities. The projection MUST exclude credentials, authority URLs, provider configuration, private inventory attributes, and routing metadata.

#### Scenario: Eligible machine is projected

- **WHEN** an operator enables a Physical Resource for specific bare-metal publication
- **THEN** one complete generation carries its distinct identities and availability without deriving one identity from another or joining an anonymous capacity bucket

#### Scenario: Projection generation is unavailable

- **WHEN** no complete generation is available from a trusted configured site
- **THEN** the storefront publishes and closes nothing for that site rather than interpreting missing data as zero capacity

#### Scenario: Site reports an authoritative empty generation

- **WHEN** a trusted site returns a complete generation containing no eligible bare-metal resources
- **THEN** the storefront closes its prior derived listings for that configured site

#### Scenario: Projection contains private or conflicting data

- **WHEN** a resource contains a credential, URL, provider configuration, unknown private attribute, or conflicting capacity/capability value
- **THEN** the projection is rejected or redacted according to the explicit allowlist and the unsafe value never enters a listing payload

### Requirement: Trusted selected-site routing

A bare-metal storefront MUST bind each configured `site_id` to an operator-trusted provisioning connection. Reservation, fulfillment, result polling, and teardown MUST use the site selected before reservation rather than a process-global default or routing data supplied by a buyer.

#### Scenario: One storefront uses several provisioning sites

- **WHEN** configured placement reserves bare-metal capacity at one of several eligible sites
- **THEN** every state-changing lifecycle call for that agreement routes to the selected site's trusted connection

#### Scenario: One site's projection refresh fails

- **WHEN** a configured site's version or snapshot request fails after a complete generation was loaded
- **THEN** that site's retained generation becomes stale while other sites continue loading and polling independently

#### Scenario: Agreement payload contains routing material

- **WHEN** buyer-controlled or opaque agreement data contains a provisioning URL, credential, or conflicting site assertion
- **THEN** the storefront ignores it for authority selection and uses its configured site binding
