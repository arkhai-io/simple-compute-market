## MODIFIED Requirements

### Requirement: Commercial mapping identity
A storefront MUST retain one common derived-listing mapping between an authoritative site/pool/Physical Resource projection and each published listing, keyed by `listing_id`. The mapping MUST record the operator-configured trusted site, optional pool and resource identities, immutable offering-mode/domain binding, a collision-safe derivation key, and a versioned domain-owned source reference when additional reconciliation data is required. Pricing, settlement terms, and seller policy MUST remain on the generic listing record; domain-specific VM or bare-metal commercial mapping tables MUST NOT remain as parallel authorities after migration.

Each derivation key MUST include the owning `site_id`, offering mode, exact domain identity/version, and the pool or Physical Resource identity at the granularity published by that mode. The encoding MUST be unambiguous for arbitrary operator-chosen identifier text.

#### Scenario: One pool exposes two offering modes
- **WHEN** one trusted pool can publish VM slices and a bare-metal whole-host offer from the same physical inventory
- **THEN** the resulting mappings and listing identities are distinct by offering mode/domain binding and neither publication overwrites the other

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their derived-listing mapping rows have distinct derivation keys and neither row's mapping is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and recording one candidate's mapping does not overwrite another's

## ADDED Requirements

### Requirement: Published offering mode is exact and pool-authorized
Every compute-family listing MUST persist one canonical offering mode and exact domain binding before publication. The public `offer_resource.virtualization_type` MUST equal that recorded mode using the registry's existing `vm`, `bare_metal`, or explicitly supported vocabulary. A candidate MUST be published only when the selected Resource Pool currently declares that exact deliverable mode and the registered domain can normalize the complete listing; absence or withdrawal MUST NOT widen to another mode.

#### Scenario: A pool declares VM and bare metal
- **WHEN** independent VM and bare-metal publication policies both produce valid candidates from a pool declaring both modes
- **THEN** the storefront may publish separate listings whose public mode and durable bindings remain exact to their respective contracts

#### Scenario: A pool declares only VM
- **WHEN** a bare-metal publisher sees otherwise compatible inventory in that pool
- **THEN** no bare-metal listing is opened and the inventory is not relabeled or routed through VM

#### Scenario: A pool withdraws a mode after acceptance
- **WHEN** a pool no longer declares `bare_metal` after a listing has an accepted negotiation
- **THEN** reconciliation closes the listing against new negotiations while the accepted record retains its binding for recovery and teardown

#### Scenario: Public mode and durable binding disagree
- **WHEN** a publication attempt carries `virtualization_type="vm"` for a record bound to `bare_metal`
- **THEN** publication fails before a registry write and does not rewrite either value

### Requirement: Listing and mapping bindings are immutable
A listing's offering mode, domain identity, contract version, and trusted site mapping MUST be immutable after first persistence. An idempotent replay with the identical binding MAY update mutable publication state; a conflicting replay MUST fail and MUST NOT close, reopen, republish, or move the existing listing as another domain or site.

#### Scenario: Reconciliation retries an existing listing
- **WHEN** the publication worker repeats the same listing derivation with the identical site, offering mode, domain identity, version, and source identity
- **THEN** it updates the existing publication idempotently without changing its binding

#### Scenario: A retry changes domain version
- **WHEN** an upsert for an existing listing names a different contract version or offering mode
- **THEN** the storefront reports a binding conflict and preserves the original record

### Requirement: Trusted site routing applies across all offering modes
Capacity reservation, fulfillment status/result reads, and teardown for a mapped listing MUST use the operator-configured site recorded in its common mapping. Buyer payloads and remotely asserted site values MUST NOT override that site. Refusal, outage, missing trust, or mode mismatch at the selected site MUST surface as a failure and MUST NOT fan out to another site.

#### Scenario: Another site has compatible capacity
- **WHEN** a VM or bare-metal listing is mapped to site A, site A refuses the request, and site B could satisfy it
- **THEN** the storefront leaves site B untouched and reports the site-A refusal under the listing's accepted binding

#### Scenario: Site trust configuration is missing after restart
- **WHEN** a recoverable record points to a site whose exact configured authority/principal binding is absent
- **THEN** recovery fails closed with the missing trusted site and performs no call against any other configured authority
