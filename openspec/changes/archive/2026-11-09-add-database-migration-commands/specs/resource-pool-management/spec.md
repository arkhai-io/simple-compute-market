## ADDED Requirements

### Requirement: Explicit valid host placement

A provisioning host MAY reference one existing resource pool; a host that references none is unplaced. A host create, update, inventory import, or host definitions entry that names a pool MUST be refused unless that pool exists. A create or a new inventory entry that names no pool MUST leave the host unplaced rather than assign a pool. On update, an omitted pool MUST leave the host's pool unchanged and an explicit `null` MUST unplace it. In an INI inventory, a non-empty `pool_id=` places or moves the host, an empty `pool_id=` unplaces it, and an absent `pool_id` leaves an existing host's pool unchanged. A host definitions entry declares its host's whole placement: an entry that names no pool, or names a `null` one, leaves a new host unplaced and unplaces an existing one. Every move, unplacing included, MUST pass the host authority's pool-change hooks, and a refusal MUST leave every host in the request, import, or document unchanged.

#### Scenario: Host names an unknown pool

- **WHEN** an operator creates or updates a host with a pool ID that does not exist
- **THEN** the service rejects the host mutation without changing the stored host

#### Scenario: A host is created without a pool

- **WHEN** an operator creates a host, or imports an inventory entry for a new host, naming no pool
- **THEN** the host is stored unplaced and is not assigned to any pool

#### Scenario: An update omits the pool

- **WHEN** an operator updates a placed host without stating a pool
- **THEN** the host keeps its pool

#### Scenario: An update unplaces a host

- **WHEN** an operator updates a placed host with an explicit `null` pool and no pool-change hook refuses
- **THEN** the host is stored unplaced

#### Scenario: An inventory import unplaces a host

- **WHEN** an INI inventory entry for an existing placed host carries an empty `pool_id=`
- **THEN** the host is unplaced if every pool-change hook allows it, and otherwise the whole import is refused and no host changes

#### Scenario: An inventory entry states no pool for an existing host

- **WHEN** an INI inventory entry for an existing placed host carries no `pool_id`
- **THEN** the host keeps its pool

#### Scenario: A host definitions entry omits the pool of a placed host

- **WHEN** a reconciled host definitions entry for an existing placed host states no `pool_id`
- **THEN** the host is unplaced if every pool-change hook allows it, and otherwise the whole document is refused and no host changes

### Requirement: Pool-declared deliverable offering modes

Each Resource Pool MUST declare the set of offering modes its configured provider can deliver under the domain-neutral `deliverable_modes` policy tag. The shared resource-pool capability MUST validate this declaration as a JSON-compatible set of unique, non-empty strings and expose typed resolution and membership behavior without defining which names are meaningful to a domain. An absent or empty declaration authorizes no mode and MUST NOT be widened by a default.

Create, replace, patch, bulk import, projection, and canonical export MUST use the existing policy-tag channel and precedence.

#### Scenario: Pool declares two modes

- **WHEN** an operator stores `deliverable_modes: [bare_metal, vm]`
- **THEN** typed resolution returns exactly those two opaque mode names through ordinary projection and administration paths

#### Scenario: Declaration is absent

- **WHEN** a Resource Pool has no `deliverable_modes` tag
- **THEN** typed resolution returns an empty set and the pool delivers no offering mode

#### Scenario: Declaration is malformed

- **WHEN** any Resource Pool write supplies a non-list, duplicate, empty, or non-string deliverable mode
- **THEN** validation rejects the write without changing the pool

### Requirement: Complete emission of advertisement and backing tags

Create, replace, patch, bulk import, projection, and canonical export MUST carry
both tags on the existing policy-tag channel. A producer that emits either tag MUST
emit it for every Resource Pool it projects, so that a consumer can distinguish a
producer that predates the tag from a producer that omitted it for one pool.

#### Scenario: A producer emits the tags incompletely

- **WHEN** a producer emits `capacity_backing` for some Resource Pools and omits it for another it projects
- **THEN** the projection is malformed with respect to this requirement, and the omitted pool is not treated as predating the tag

### Requirement: VM provider registration is namespaced

The VM adapter MUST register as `vm.ansible`, alongside `bare_metal.ansible`.
Runtime documents and callers MUST use the canonical name; no historical-name alias
is required.

#### Scenario: A canonical VM pool is administered

- **WHEN** an operator creates or edits a VM pool with provider `vm.ansible`
- **THEN** the VM adapter validates its configuration and handles fulfillment through that registration

## REMOVED Requirements

### Requirement: Explicit valid host membership

**Reason**: Its scenario "Existing schema is migrated" governs the resource-pool migration (`20260713_002_resource_pools_and_hosts_pool_id`), which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its normative text is kept unchanged as "Explicit valid host placement", with every other scenario, since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: Pool-declared offering modes

**Reason**: Its derivation of an existing pool's initial set, and its scenarios "Existing default pool is migrated" and "Legacy declaration is wider than configuration", govern the migration `20260815_001_pool_declared_offering_modes`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its remaining rule is kept unchanged as "Pool-declared deliverable offering modes", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: Complete emission and upgrade derivation

**Reason**: Its upgrade derivation, and its scenarios "An existing pool is migrated", "An existing pool held an opaque value under a new key", and "A migrated site is projected", govern the migration `20260922_001_pool_advertisement_and_backing`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. The API-credit service's own pool migration goes with that service's pre-baseline chain, since its chain starts at its baseline with no adoption path and no existing API-credit database is migrated. The emission rule is kept unchanged as "Complete emission of advertisement and backing tags", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release, or any existing API-credit service database, starts that service from a fresh database; the emission rule is unchanged under the new requirement's name.

### Requirement: VM provider identity is namespaced

**Reason**: Its canonicalization of historical `ansible` routing columns, and its scenario "Existing VM state is upgraded", govern the migration `20261019_001_vm_provider_identity`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its registration rule is kept unchanged as "VM provider registration is namespaced", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the registration rule is unchanged under the new requirement's name.
