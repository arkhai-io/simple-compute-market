## ADDED Requirements

### Requirement: Storefront holds no physical-resource authority

A storefront MUST NOT actively maintain physical-resource inventory, host
inventory, or physical-allocation state. Authoritative physical state belongs to the site
authority and the provisioning service, and a storefront obtains it only through
projections. A storefront MAY persist commercial state — pricing, accepted
settlement terms, seller policy, and listing derivation records — including
per-pool commercial values keyed by a projected pool identity.

Fresh storefront databases MUST NOT create the retired local inventory or
physical-allocation tables, columns, triggers, or indexes. An upgraded database
MAY retain pre-existing schema and rows as inert historical data for code
rollback or operator-directed provisioning seeding. The retirement MUST NOT
drop that schema or delete or rewrite its retained rows. Current storefront
code MUST NOT read or write the retired data, including during startup,
publication, negotiation, diagnostics, or reservation cleanup.

Retained rows MUST NOT be treated as current physical truth. An operator MAY
use them to prepare host inventory, pool definitions, and capacity declarations
for provisioning's supported administration surfaces; that use MUST NOT restore
a storefront inventory read path or overwrite live site state automatically.

#### Scenario: A fresh storefront database is initialized

- **WHEN** a storefront bootstraps a new database
- **THEN** it creates no retired local physical-inventory or allocation schema,
  while commercial and listing-derivation persistence remains

#### Scenario: A populated legacy database is upgraded

- **WHEN** retirement is applied to a database containing retired local schema
  and rows, including resource-transition history
- **THEN** that schema and those rows are retained unchanged and current
  storefront code neither reads nor writes them

#### Scenario: An operator uses retained inventory to seed provisioning

- **WHEN** an operator prepares provisioning inventory from retained legacy rows
- **THEN** authoritative declarations enter through provisioning's supported
  administration surfaces, without automatic overwrite of live site state or
  reactivating storefront-local inventory

#### Scenario: Physical state changes after the cutover

- **WHEN** provisioning's physical state changes while historical storefront
  rows remain in the database
- **THEN** the historical rows remain unchanged and cannot be used as evidence
  of current availability for rollback or provisioning seeding

#### Scenario: Provisioning reports a physical lifecycle transition

- **WHEN** a physical resource is released or its lifecycle state changes
- **THEN** the authoritative record changes at the site authority and the
  storefront does not maintain a parallel physical state record to be updated

#### Scenario: Publication needs physical facts

- **WHEN** a storefront derives publishable listing candidates
- **THEN** the physical facts come from site projections, and no local physical
  inventory is consulted or retained as an alternative source

## REMOVED Requirements

### Requirement: Operator-visible acceptance state

**Reason**: Its inventory scenario requires a storefront-local resource-row
count, which retires with local inventory and CSV import.

**Migration**: Replaced by "Operator-visible acceptance and projection state"
below. Global negotiation-pause behavior is preserved. Operator checks use
counts under each site's projection-family status instead of the removed
top-level `resource_count`; provisioning owns inventory-import diagnostics.

### Requirement: Storefronts cache independent site projections

**Reason**: Its third paragraph and the "Projection-backed derivation has reached parity" scenario define a retained local-table derivation path as an explicit, non-default rollback option. This change deletes that path outright, so the requirement cannot be amended in place without leaving a scenario describing behavior no implementation can exhibit.

**Migration**: Replaced by "Projection-backed listing candidate derivation" below, which carries forward the projection-consumption, independent-versioning, and stale-generation semantics unchanged and replaces the parity/rollback provision with a prohibition on retaining a local path. No storefront behavior other than the removed local path changes; a deployment that had already defaulted to projection-backed derivation is unaffected.

## ADDED Requirements

### Requirement: Operator-visible acceptance and projection state

The storefront MUST expose enough operator state to distinguish global
negotiation pause from listing state, and a known-empty site projection from
one whose generation is not held.

System status MUST report `resource_count` separately under each site's
projection-family status, alongside that family's load state, revision,
digest, last error, and confirmation timestamp. The count MUST describe the
same cached generation as that state and identity. Status MUST NOT obtain a
separate generation just to compute a count, consult storefront-local physical
inventory, or replace per-site counts with a storefront-wide total. The
top-level storefront-local `resource_count` field MUST be removed.

For `resource_pool`, the count MUST be the number of projected members across
pools, including disabled declarations. For `capacity_bucket`, it MUST be the
sum of the projected groups' `resource_count` values, counting enabled
declarations including exhausted ones. These are declaration counts, not
counts of distinct physical machines, groups, dimension quantities, feasible
listing shapes, or published listings. Both counts MUST NOT be filtered
further by pool enablement or offering-mode authorization.

A held empty generation MUST report zero. A family with no generation held
MUST report null, not zero. A retained stale generation MUST retain its count
and be reported as stale. Each site and projection family MUST be reported
independently; a loaded family MUST NOT supply a count for an unknown one.

Inventory counts MUST NOT assert publication readiness or diagnose an import
failure from emptiness alone. Publication diagnostics and catalogue state
describe sellable listings; provisioning owns its inventory-import outcomes.
Liveness health MUST remain independent of these operator inventory counts.

#### Scenario: Storefront is globally paused

- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason
  until an authenticated operator resumes the process

#### Scenario: A site has a known-empty projection

- **WHEN** a cached site projection family holds an empty generation
- **THEN** system status reports zero resources for that site and family,
  with the held generation's identity and state

#### Scenario: A projection family has not loaded

- **WHEN** a site projection family has no generation held, even if another
  family or site has loaded
- **THEN** its count is null and its own load state is reported, without
  borrowing another family's count or treating the site as empty

#### Scenario: Refresh fails after inventory has loaded

- **WHEN** refreshing a family fails after a complete generation was held
- **THEN** its count and identity describe that retained generation and its
  state is stale

#### Scenario: Grouped capacity carries resource multiplicity

- **WHEN** a site's capacity projection contains two groups with resource
  counts of three and two
- **THEN** its capacity-family status reports five resources, regardless of
  the groups' available dimension quantities

#### Scenario: Inventory includes disabled and exhausted declarations

- **WHEN** a site's resource-pool projection contains three declarations,
  one disabled and two enabled, one of which is exhausted, and its capacity
  projection contains those two enabled declarations
- **THEN** status reports three resource-pool members and two capacity-family
  resources, without asserting that either count proves sellable listings

#### Scenario: Sites have different inventory counts

- **WHEN** two sites hold resource-pool generations containing two and five
  members respectively
- **THEN** system status preserves the two site-scoped counts alongside their
  respective generation identities rather than replacing them with seven

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

## MODIFIED Requirements

### Requirement: A site whose projection is not held holds its listings

A storefront MUST treat a configured site whose resource-pool projection holds no value as
unknown, not empty: every listing derived from that site MUST be held, neither closed nor
refreshed, until the site's projection holds a value. A site whose projection is not held
MUST NOT yield listings from any other source in its place.

#### Scenario: The storefront starts while a site is unreachable

- **WHEN** a storefront with open listings from a site restarts while that site cannot be
  reached, and a publication cycle runs
- **THEN** those listings stay open, and none is closed as having lost its source

#### Scenario: No site's projection is held

- **WHEN** no configured site's projection holds a value and a publication cycle runs
- **THEN** no listing is derived and no listing is closed

#### Scenario: The site returns

- **WHEN** the unknown site's projection loads
- **THEN** its listings are reconciled against it as usual

#### Scenario: A bare-metal site is unreachable during a publication run

- **GIVEN** open bare-metal listings derived from a site
- **WHEN** the operator runs bare-metal publication while that site's projection cannot be
  fetched
- **THEN** those listings stay open and unchanged, and the run reports the site as unknown
- **AND** every other configured site is reconciled as usual

### Requirement: Publication pricing migration is preview-first and atomic

Storefront publication migration MUST support TOML configuration input through
explicit check and write modes. Check mode MUST produce a deterministic preview
without changing the source or creating a backup. Write mode MUST require a
backup, preserve an exact pre-migration copy, validate the complete proposed
document through the current structured clause model and every selected
mechanism's typed publication-input validator, and replace the source
atomically with restrictive permissions. A failed validation or write MUST
leave the source unchanged. Rechecking an already migrated input MUST be
idempotent.

Automatic conversion MUST occur only when one enabled mechanism, its asset
scale, and every legacy pricing input have one complete interpretation.
Dual-mechanism pricing, hidden reserves, per-model legacy pricing, a missing
asset scale, malformed legacy values, and any other ambiguous population MUST
be reported as conflicts without mutation. Migration MUST NOT guess units,
synthesize partial clauses, or reinterpret `min_price` or
`default_token_address` as a settlement rate or asset.

#### Scenario: Operator previews publication migration

- **WHEN** the operator runs check mode against a storefront TOML file
- **THEN** the tool reports the deterministic proposed changes and conflicts while the input bytes and backup set remain unchanged

#### Scenario: Unambiguous publication input is written

- **WHEN** one enabled mechanism and authoritative asset scale make every legacy price unambiguous and the operator requests write with backup
- **THEN** the tool fully validates the typed result, saves the exact original bytes, and atomically installs the restrictive-permission replacement

#### Scenario: Legacy pricing has competing interpretations

- **WHEN** dual mechanisms, hidden reserve pricing, per-model legacy pricing, or a missing scale could produce different clauses
- **THEN** check and write modes report the conflict and neither the source nor any existing backup is changed

#### Scenario: Generated clause fails typed mechanism validation

- **WHEN** a proposed migration contains an unknown field, invalid rate, unsupported asset, or invalid mechanism-owned input
- **THEN** migration fails before backup or mutation rather than persisting a partially validated document

## REMOVED Requirements

### Requirement: Per-resource settlement input uses the common clause contract

**Reason**: It lists imported resource records among settlement inputs, and its only scenario has one imported resource record replace the configured defaults. Resource import retires with this change, and a modified requirement cannot drop its scenario, so it is replaced.

**Migration**: Replaced by "Settlement input uses the common clause contract" below, which carries the parsing and failure rule forward for configured defaults, pool-declared hints, storefront pool overrides, and reconciliation inputs. Per-pool settlement clauses formerly supplied by a CSV row are entered as a storefront pool override.

## ADDED Requirements

### Requirement: Settlement input uses the common clause contract

Configured defaults, pool-declared hints, storefront pool overrides, and reconciliation inputs that describe settlement options MUST parse to the same typed settlement-clause model before option derivation. Unknown fields, conflicting duplicate values, role-inapplicable fields, and malformed rates MUST fail the affected candidate without creating a partially interpreted option.

#### Scenario: A pool override's clauses replace settlement defaults

- **WHEN** a storefront pool override for one site's pool supplies complete settlement clauses
- **THEN** those clauses replace the configured defaults for that pool's listings and are validated through the same grammar and registrations
