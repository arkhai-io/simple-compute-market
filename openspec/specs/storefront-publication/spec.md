# Storefront Publication Specification

## Purpose

Define seller storefront ownership, listing publication/reconciliation, and domain-runtime composition.

## Requirements

### Requirement: Seller protocol surface
A storefront MUST expose authenticated listing, negotiation, settlement, identity, health, and operator control surfaces while keeping domain-specific behavior behind injected adapters.

#### Scenario: Buyer settles accepted terms
- **WHEN** the buyer submits a settlement request for an accepted negotiation
- **THEN** the storefront verifies the agreed terms and settlement evidence before scheduling fulfillment

### Requirement: Operator-visible acceptance state
The storefront MUST expose enough operator state to distinguish global negotiation pause from listing state and an empty resource projection from an inventory import failure.

#### Scenario: Storefront is globally paused
- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason until an authenticated operator resumes the process

#### Scenario: Storefront has no imported resources
- **WHEN** the active storefront database contains no resource rows
- **THEN** system status reports `resource_count` as zero and new negotiations cannot match inventory

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

### Requirement: Commercial mapping identity
A storefront's derived-listing mapping (`derived_compute_listings`, `derived_bare_metal_listings`) is the commercial-mapping table between an authoritative physical or capacity identity and a published listing; it MUST NOT be duplicated as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — the mapping row carries no commercial fields of its own. Each mapping row's derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their derived-listing mapping rows have distinct derivation keys and neither row's mapping is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and recording one candidate's mapping does not overwrite another's

### Requirement: Site-pinned claim routing
A capacity claim for a listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every listing with a site mapping, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A listing with no recorded site mapping MAY be routed by placement policy across configured sites.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_mode` and `max_reservation_hold_seconds` policy tags. Each domain MUST own its accepted `listing_mode` values and structural default; an absent or unrecognized value MUST fall back to that default with an operator-visible explanation rather than failing projection ingestion or blocking publication. A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can currently satisfy, never by a sum across members, and MUST be sourced from grouped `site_capacity_buckets` data when it is available; a `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

#### Scenario: Listing mode is absent or invalid
- **WHEN** a projected pool omits `listing_mode` or supplies a value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion

#### Scenario: A fungible pool's members have unequal availability
- **WHEN** a fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

#### Scenario: A specific-resource pool has more than one member
- **WHEN** a pool resolves to `specific_resource` and has multiple currently enabled members
- **THEN** the storefront derives one listing candidate per member rather than one pooled candidate

#### Scenario: Hold preference is shorter than storefront policy
- **WHEN** a valid positive `max_reservation_hold_seconds` is lower than the storefront's configured acceptance-hold TTL
- **THEN** the storefront requests no more than the projected preference while live site admission remains authoritative

### Requirement: Domain publication capability
A domain that supports seller publication MUST provide its publication source and listing interpretation through the domain contract while registry fan-out remains schema-opaque core orchestration.

#### Scenario: Domain publication plugin is selected
- **WHEN** an operator selects a registered domain source
- **THEN** the core runner invokes it through the publication-source contract and publishes its opaque payloads

#### Scenario: Domain capacity changes
- **WHEN** a domain publication source observes a change in its authoritative inventory or quota
- **THEN** it produces domain listings through its contract and the shared runner publishes or reconciles their opaque payloads

### Requirement: Domain runtime composition
The shared storefront role MUST consume the selected market-domain contract for listing, message, agreed-terms, materialization, receipt, and result codecs plus the lifecycle hooks declared by that domain. A concrete storefront composition MUST supply its implementations explicitly, and generic storefront services MUST NOT import or branch on concrete domains.

#### Scenario: Current storefront composition selects a domain
- **WHEN** a VM or API-credit storefront is assembled
- **THEN** its composition root supplies a validated domain contract used by every shared storefront service that interprets domain behavior

#### Scenario: Domain validation fails
- **WHEN** a domain codec or hook rejects a payload
- **THEN** the storefront surfaces the domain validation failure without coercing it through a different domain or a generic fallback

### Requirement: Trusted provisioning-site identity
A storefront MUST bind each provisioning connection to an operator-configured `site_id`. It MUST derive routing and ownership from that trusted binding rather than accepting a counterparty-provided site identity.

#### Scenario: Provisioner reports a conflicting site identity
- **WHEN** a configured provisioning connection reports a `site_id` different from the storefront binding
- **THEN** the storefront retains the configured identity and rejects or ignores the conflicting assertion

### Requirement: Storefronts cache independent site projections
Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains host-granular inside the provisioning site authority.

A storefront SHALL load the resource-pool and capacity-bucket projections at startup, poll their independent revision-and-digest identities, and replace each cached generation atomically. Refresh failure SHALL retain the last complete generation and mark it stale rather than representing an empty projection. Topology-sensitive authoritative errors MAY trigger one coalesced drift check but SHALL NOT automatically retry a state-changing request.

#### Scenario: One projection refresh fails
- **WHEN** a storefront cannot refresh one site projection after previously loading a complete generation
- **THEN** it retains that generation as stale without replacing the other independently versioned projection

## Evidence

- Generic publication source, runner, and plugin discovery: `core/storefront/tests/unit/test_publication_sources.py`, `test_publication_runner.py`, and `test_publication_plugins.py`.
- Registry fan-out and publication persistence: `core/storefront/tests/unit/test_registry_publication.py` and `domains/vms/storefront/tests/unit/test_publications_wiring.py`.
- Domain-runtime bundle and VM wiring: `core/storefront/tests/unit/test_domain_runtime.py` and `domains/vms/storefront/tests/unit/test_domain_runtime_wiring.py`.
- Global pause state: `domains/vms/storefront/tests/unit/test_order_pause_state.py` and `tests/integration/test_admin_api.py`.
- Resource-count diagnosis: `domains/vms/storefront/src/market_storefront/services/system_service.py` and `e2e-tests/tests/smoke/test_storefront_smoke.py`.
- Site-scoped derivation keys and collision resistance (VM and bare-metal): `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/bare_metal/tests/test_publication.py`, and `domains/bare_metal/tests/test_storefront_publication.py`.
- Site-pinned claim routing, including the collision case placement policy would otherwise choose wrongly: `core/storefront/tests/unit/test_aggregation.py`. Mapped-listing routing reached through the real admin, negotiation-hold, and settlement/fulfillment entry points: `domains/vms/storefront/tests/integration/test_admin_api.py`, `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, and `domains/vms/storefront/tests/unit/test_settlement_jobs.py`.
- Domain-owned listing-mode resolution, bucket-sourced fungible candidates, multi-member specific-resource derivation, the resource-keyed derivation-key collision fix, and the live (never persisted) hold-preference cap: `domains/vms/storefront/tests/unit/test_reconciler.py`, `domains/vms/storefront/tests/unit/test_listing_mode.py`, `domains/vms/storefront/tests/unit/test_sync_negotiation_hold_cap.py`, `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`, and `domains/bare_metal/tests/test_listing_mode.py`.

Replacing the domain-owned storefront executables remains proposed work rather than baseline behavior. Bare metal currently supplies domain codecs and publication semantics but not a complete runnable storefront composition.
