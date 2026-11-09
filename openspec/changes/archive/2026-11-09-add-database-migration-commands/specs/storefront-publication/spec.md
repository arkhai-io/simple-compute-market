## ADDED Requirements

### Requirement: A storefront retires registry listings it does not hold open

This requirement governs VM, API-credit, and bare-metal publication, beside the convergence of the listings a storefront records.

Every publication pass MUST list, at each configured registry it can reach, the open listings published under the storefront's own publisher principal for the offering modes it serves, and MUST close at that registry each one the storefront does not hold open locally, whether it is closed locally or unknown to the storefront. Listings of an offering mode the storefront does not serve MUST be left as they are. The pass MUST read every page of a registry's listings before closing any listing there, and MUST treat a registry it cannot reach, or whose read fails on any page, as unreachable: it closes nothing there and a later pass sweeps it. A listing the storefront holds open locally, including one held while its site's projection is unavailable, MUST NOT be closed. A preview pass MUST report each such close without making it.

#### Scenario: A registry holds an open listing the storefront has no record of

- **WHEN** a registry holds an open listing published under the storefront's principal, for an offering mode it serves, that the storefront does not record
- **THEN** the next publication pass closes it at that registry and reports the close with the reason that the storefront does not hold it

#### Scenario: A listing closed locally is still open at a registry the storefront no longer records

- **WHEN** a listing the storefront closed locally is open at a configured registry for which the storefront holds no publication record
- **THEN** the next publication pass closes it at that registry

#### Scenario: Another storefront's offering mode under the same principal

- **WHEN** the VM storefront and the bare-metal storefront publish under one principal and the VM storefront's pass finds an open bare-metal listing it does not record
- **THEN** it leaves that listing open

#### Scenario: A preview pass finds a listing it does not hold

- **WHEN** a preview publication pass finds an open registry listing the storefront does not hold open
- **THEN** it reports the close it would make and changes nothing at the registry

#### Scenario: A registry is unreachable during the sweep

- **WHEN** a configured registry cannot be reached during a publication pass
- **THEN** the pass sweeps the other registries and that registry is swept by a later pass

#### Scenario: A registry holds more open listings than one page

- **WHEN** a registry holds more open listings under the storefront's principal than one page of its listing query returns
- **THEN** the pass reads every page before closing, and closes each listing on any page that the storefront does not hold open

#### Scenario: A registry's listing read fails partway through

- **WHEN** a registry answers the first page of the sweep's listing read and fails on a later one
- **THEN** the pass closes nothing at that registry, and a later pass sweeps it

#### Scenario: A listing is held open during a site outage

- **WHEN** the storefront holds a listing open while its site's projection is unavailable, and a registry holds that listing open
- **THEN** the sweep leaves it open at that registry

### Requirement: Storefront holds no physical-resource authority or inventory

A storefront MUST NOT actively maintain physical-resource inventory, host
inventory, or physical-allocation state. Authoritative physical state belongs to the site
authority and the provisioning service, and a storefront obtains it only through
projections. A storefront MAY persist commercial state — pricing, accepted
settlement terms, seller policy, and listing derivation records — including
per-pool commercial values keyed by a projected pool identity.

Fresh storefront databases MUST NOT create the retired local inventory or
physical-allocation tables, columns, triggers, or indexes. The VM storefront's
migration chain MUST drop the retired inventory tables — `compute_allocations`,
`resources`, `hosts`, `resource_transition_events`, `compute_pool_members`,
`compute_capacity_pools`, and `compute_inventory_pools` — with their rows from a
database it adopts that holds them, so that a storefront's database holds no
physical-resource tables. Storefront code MUST NOT read or write any retired table,
including during startup, publication, negotiation, diagnostics, or reservation
cleanup.

#### Scenario: A fresh storefront database is initialized

- **WHEN** a storefront bootstraps a new database
- **THEN** it creates no retired local physical-inventory or allocation schema,
  while commercial and listing-derivation persistence remains

#### Scenario: An adopted VM storefront database holds the retired inventory tables

- **WHEN** the VM storefront's migration command runs against a database it adopts
  that holds retired inventory tables and their rows
- **THEN** those tables and their rows are gone, and the storefront reads and writes
  no physical-resource state

#### Scenario: Provisioning reports a physical lifecycle transition

- **WHEN** a physical resource is released or its lifecycle state changes
- **THEN** the authoritative record changes at the site authority and the
  storefront does not maintain a parallel physical state record to be updated

#### Scenario: Publication needs physical facts

- **WHEN** a storefront derives publishable listing candidates
- **THEN** the physical facts come from site projections, and no local physical
  inventory is consulted or retained as an alternative source

## REMOVED Requirements

### Requirement: Storefront identity state migrates atomically

**Reason**: The conversion it governs, of address-only identity rows to canonical principals, is part of every storefront's v0.3.0 floor: each database a storefront's migration command adopts has already run it, and the command refuses any older database as unsupported, so the conversion is deleted with core storefront's pre-floor chain.

**Migration**: An operator holding a storefront database from before the marketplace v0.3.0 release starts the storefront from a fresh database.

### Requirement: Storefront holds no physical-resource authority

**Reason**: Its permission for an upgraded database to retain the retired inventory schema and rows, its rule that the retirement not drop them, its paragraph on an operator's use of retained rows, and its scenarios "A populated legacy database is upgraded", "An operator uses retained inventory to seed provisioning", and "Physical state changes after the cutover" describe retained data no supported database still holds: a fresh database never creates the retired inventory tables, and the VM storefront's migration `20261109_002_vm_frozen_inventory_dropped` drops them, with their rows, from a database its migration command adopts. Its remaining rule is kept as "Storefront holds no physical-resource authority or inventory", which states that drop, since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator who wants the rows of a VM storefront's retired inventory tables extracts them before running the migration command; inventory is declared at provisioning, and the storefront's rule is otherwise unchanged under the new requirement's name.
