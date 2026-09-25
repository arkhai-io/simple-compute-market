## ADDED Requirements

### Requirement: Storefront holds no physical-resource authority

A storefront MUST NOT persist physical-resource inventory, host inventory, or
physical-allocation state. Authoritative physical state belongs to the site
authority and the provisioning service, and a storefront obtains it only through
projections. A storefront MAY persist commercial state — pricing, accepted
settlement terms, seller policy, and listing derivation records — including
per-pool commercial values keyed by a projected pool identity.

#### Scenario: Storefront persistence is inspected for physical state

- **WHEN** a storefront's persisted schema is reviewed
- **THEN** it contains no physical-resource inventory, host inventory, or
  physical-allocation records, while commercial and listing-derivation records
  remain

#### Scenario: Provisioning reports a physical lifecycle transition

- **WHEN** a physical resource is released or its lifecycle state changes
- **THEN** the authoritative record changes at the site authority and the
  storefront does not maintain a parallel physical state record to be updated

#### Scenario: Publication needs physical facts

- **WHEN** a storefront derives publishable listing candidates
- **THEN** the physical facts come from site projections, and no local physical
  inventory is consulted or retained as an alternative source

## REMOVED Requirements

### Requirement: Storefronts cache independent site projections

**Reason**: Its third paragraph and the "Projection-backed derivation has reached parity" scenario define a retained local-table derivation path as an explicit, non-default rollback option. This change deletes that path outright, so the requirement cannot be amended in place without leaving a scenario describing behavior no implementation can exhibit.

**Migration**: Replaced by "Projection-backed listing candidate derivation" below, which carries forward the projection-consumption, independent-versioning, and stale-generation semantics unchanged and replaces the parity/rollback provision with a prohibition on retaining a local path. No storefront behavior other than the removed local path changes; a deployment that had already defaulted to projection-backed derivation is unaffected.

## ADDED Requirements

### Requirement: Projection-backed listing candidate derivation

Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains resource-granular inside the provisioning site authority, which applies each pool provider's host requirement.

A storefront SHALL load the resource-pool and capacity-bucket projections at startup, poll their independent revision-and-digest identities, and replace each cached generation atomically. Refresh failure SHALL retain the last complete generation and mark it stale rather than representing an empty projection. Topology-sensitive authoritative errors MAY trigger one coalesced drift check but SHALL NOT automatically retry a state-changing request.

Projection-backed candidate derivation SHALL be a storefront's only listing-candidate path. A storefront SHALL NOT retain a local, non-projection physical-inventory table as an alternative source, and SHALL NOT expose a configuration option selecting between projection-backed and local derivation. Reverting to a local-inventory path is a code change rather than a configuration change.

#### Scenario: One projection refresh fails
- **WHEN** a storefront cannot refresh one site projection after previously loading a complete generation
- **THEN** it retains that generation as stale without replacing the other independently versioned projection

#### Scenario: Listing candidates are derived
- **WHEN** a storefront derives publishable listing candidates
- **THEN** they come from the site projections, with no local-table path available and no configuration option to select one

#### Scenario: Operator seeks to revert to local inventory
- **WHEN** an operator wants a storefront to derive candidates from local inventory
- **THEN** no configuration value produces that behavior and reverting requires deploying an earlier version

#### Scenario: Grouped capacity is used for publication
- **WHEN** a storefront publishes from the capacity-bucket projection
- **THEN** it treats grouped capacity as advisory publication input and never as an allocation target

## REMOVED Requirements

### Requirement: Storefront pool overrides are site-scoped and durable

**Reason**: Its second paragraph defines precedence over a home-site legacy override record, its status list carries an `inactive` state that only local-table derivation produces, and two of its scenarios ("An override is deleted over a legacy value", "Listings derive from local tables") describe behavior this change removes outright. A requirement cannot be amended in place to drop scenarios, so it is replaced.

**Migration**: Replaced by "Storefront pool overrides are the only override tier" below, which carries every other paragraph and scenario forward unchanged and adds one scenario for the retired legacy record. A deployment holding no legacy values is unaffected; one still taking a field from the legacy record resolves that field from the pool hint and the configured default after upgrade, as the operator guidance this change writes instructs.

## ADDED Requirements

### Requirement: Storefront pool overrides are the only override tier

A storefront's per-pool overrides MUST be stored durably, keyed by site, pool, and offering
mode. Each override belongs to exactly one offering mode and MUST be validated by the market
that serves that mode; a write for a mode no market serves MUST be refused. An override MAY
state its market's commercial terms, settlement clauses, and listing shapes. An override
MUST NOT state region or capacity backing, and its offering mode MUST NOT be defaulted. A field an override leaves unset MUST fall
through to the next precedence tier. Listing shapes and settlement clauses MUST each replace
the lower tier's list as a whole, and an empty shape list or an empty settlement-clause list
MUST be refused.

The site-scoped store is the storefront's only override tier: a storefront MUST NOT hold a
second, pool-keyed commercial override record beneath it, and a value the store does not
state resolves from the pool's own projected hint and then the storefront's configured
default.

Every listing-derivation path that computes a listing's derivation identity, including
source reconciliation and the inventory guard, MUST resolve the override tier, so that
publication and reconciliation derive the same listings.

An override MUST outlive the projection of its pool. The storefront's system status MUST
report every stored override in exactly one state, judged against the projection its
listings are derived from:

- `site_unconfigured` when the storefront does not configure the override's site;
- `unknown` when the site is configured but no projection of it is held;
- `orphaned` when the projection derived from holds no such pool;
- `applied` otherwise.

A site with no projection held MUST NOT make an override `orphaned`, because the pool's
absence is not known. An orphaned override has no effect. When its pool returns, the
override MUST apply again.

#### Scenario: One pool is overridden for two offering modes

- **WHEN** overrides are stored for the same site and pool under two offering modes
- **THEN** each applies only to that mode's listings and is validated by that mode's market

#### Scenario: No market serves the override's mode

- **WHEN** an administrator writes an override for an offering mode no installed market
  serves
- **THEN** the write is refused without contacting the site and nothing is stored

#### Scenario: Two sites name a pool identically

- **WHEN** overrides are stored for pool `gpu` at site `a` and at site `b`
- **THEN** each applies only to listings derived from its own site's pool

#### Scenario: A pool at a non-home site is overridden

- **WHEN** an override states an SLA for a pool at a site other than the storefront's first
  configured site
- **THEN** listings derived from that pool publish the overridden SLA

#### Scenario: A pool disappears and returns

- **WHEN** a pool with an override leaves its site's projection and later reappears
- **THEN** the override is retained and reported as orphaned while the pool is absent, and
  applies again once the pool is projected

#### Scenario: A site's projection has not loaded

- **WHEN** an override names a configured site whose projection the storefront has never
  loaded
- **THEN** system status reports the override as unknown rather than orphaned, and nothing
  is closed or published for it

#### Scenario: An override shapes a pool's listings

- **WHEN** an override states a shape for a pool and a publication cycle has published it
- **THEN** a later capacity reconciliation derives the same listing and does not close it

#### Scenario: A home-site pool has no override

- **WHEN** a home-site pool has no site-scoped override and the storefront was upgraded from a
  version that held a pool-keyed legacy override record for it
- **THEN** each commercial field resolves from the pool's hint and then the configured
  default, no legacy value is applied, and system status reports no legacy value in effect
