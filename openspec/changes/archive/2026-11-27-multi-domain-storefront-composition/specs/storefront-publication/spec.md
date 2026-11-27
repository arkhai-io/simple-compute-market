## MODIFIED Requirements

### Requirement: Commercial mapping identity
A VM or bare-metal listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM and bare-metal publication, reconciliation, close, and reopen MUST NOT read or write a domain-owned mapping table (`derived_compute_listings`, `derived_bare_metal_listings`); a closed listing is found again by its candidate's derivation key in the common binding. A bare-metal listing's derivation key MUST include its pool, so a Physical Resource moved to another pool derives a new listing and its old listing closes as a withdrawn source. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally, and MUST include the offering mode and the exact domain identity and contract version, since one pool may be published under more than one offering mode. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

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
