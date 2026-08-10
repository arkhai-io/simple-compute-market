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

### Requirement: Commercial pool override administration

A storefront MUST provide an operator write path for the per-pool commercial
values it owns, keyed by a pool identity that already exists in a site
projection. The write path MUST create the override record when none exists and
replace or partially update it when one does, and MUST NOT create a resource
pool. Where no override record exists for a pool, commercial resolution MUST
fall through to lower-precedence sources per field rather than failing or
treating the pool as unpublishable.

#### Scenario: Operator sets an override for a projected pool

- **WHEN** an operator writes commercial values for a pool that exists in a site
  projection and has no override record
- **THEN** the override record is created and those values take precedence over
  the pool's own projected hints

#### Scenario: Operator overrides only some fields

- **WHEN** an override record sets some commercial fields and leaves others unset
- **THEN** the unset fields resolve through the pool's projected hint and then the
  storefront's configured default, independently per field

#### Scenario: Pool has no override record

- **WHEN** a projected pool has no override record at all
- **THEN** it still publishes, with every commercial field resolved from lower
  tiers

#### Scenario: Write names a pool absent from every projection

- **WHEN** an operator writes commercial values naming a pool that no site
  projection contains
- **THEN** the write is rejected rather than creating a pool the storefront has no
  authority to define

## REMOVED Requirements

### Requirement: Storefronts cache independent site projections

**Reason**: Its third paragraph and the "Projection-backed derivation has reached parity" scenario define a retained local-table derivation path as an explicit, non-default rollback option. This change deletes that path outright, so the requirement cannot be amended in place without leaving a scenario describing behavior no implementation can exhibit.

**Migration**: Replaced by "Projection-backed listing candidate derivation" below, which carries forward the projection-consumption, independent-versioning, and stale-generation semantics unchanged and replaces the parity/rollback provision with a prohibition on retaining a local path. No storefront behavior other than the removed local path changes; a deployment that had already defaulted to projection-backed derivation is unaffected.

## ADDED Requirements

### Requirement: Projection-backed listing candidate derivation

Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains host-granular inside the provisioning site authority.

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
