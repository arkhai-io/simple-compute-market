## MODIFIED Requirements

### Requirement: Commercial mapping identity
A VM or bare-metal listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM and bare-metal publication, reconciliation, close, and reopen MUST NOT read or write a domain-owned mapping table (`derived_compute_listings`, `derived_bare_metal_listings`); a closed listing is found again by its candidate's derivation key in the common binding. A bare-metal listing's derivation key MUST include its pool, so a Physical Resource moved to another pool derives a new listing and its old listing closes as a withdrawn source. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally, and MUST include the offering mode and exact domain identity/version, since one pool may publish under more than one offering mode. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their listing bindings have distinct derivation keys and neither binding is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and binding one candidate does not overwrite another's

#### Scenario: A closed listing's slice becomes publishable again
- **WHEN** a closed VM listing's candidate is derived again with the same derivation identity
- **THEN** the listing bound under that derivation key reopens, rather than a new listing being bound under a colliding key

#### Scenario: A Physical Resource moves to another pool
- **GIVEN** an open bare-metal listing bound under a Physical Resource's pool
- **WHEN** the site projects that Physical Resource under a different pool that admits bare metal, and the operator runs bare-metal publication
- **THEN** the listing closes as a withdrawn source and a new listing publishes under the new pool's binding

#### Scenario: One pool exposes two offering modes
- **WHEN** one trusted pool can publish VM slices and a bare-metal whole-host offer from the same physical inventory
- **THEN** the resulting bindings and listing identities are distinct by offering mode/domain binding and neither publication overwrites the other

## ADDED Requirements

### Requirement: Published offering mode is exact and pool-authorized
Every compute-family listing MUST persist one canonical offering mode and exact domain binding before publication. The public `listing_resource.offering_mode` MUST equal that recorded mode using the registry's existing `vm`, `bare_metal`, or explicitly supported vocabulary. A candidate MUST be published only when the selected Resource Pool currently declares that exact deliverable mode and the registered domain can normalize the complete listing; absence or withdrawal MUST NOT widen to another mode.

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
- **WHEN** a publication attempt carries `offering_mode="vm"` for a record bound to `bare_metal`
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
