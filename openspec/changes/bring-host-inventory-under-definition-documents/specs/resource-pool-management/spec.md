## ADDED Requirements

### Requirement: A configured pool document is imported at startup or fails it

The provisioning service MAY be configured with a pool definitions document through `pool_definitions_path`. At startup it MUST reconcile that document under the digest contract of "Atomic authoritative reconciliation", before the fresh-site seed is considered and before host and capacity definitions are imported, so every pool the document declares exists when a host or a capacity declaration names it. A configured document that is missing or cannot be applied MUST fail startup and record no digest, and the seed document MUST NOT be applied in its place.

#### Scenario: A configured pool document is missing

- **WHEN** the service starts on a database storing no pool, with a `pool_definitions_path` naming no document
- **THEN** startup fails and no pool is created, from the seed or otherwise

#### Scenario: A configured pool document cannot be applied

- **WHEN** the service starts on a database storing no pool, with a `pool_definitions_path` whose document fails pool document validation
- **THEN** startup fails, no pool is created, the seed is not applied, and no digest is recorded

## MODIFIED Requirements

### Requirement: Explicit valid host membership

A provisioning host MAY reference one existing resource pool; a host that references none is unplaced. A host create, update, inventory import, or host definitions entry that names a pool MUST be refused unless that pool exists. A create or a new inventory entry that names no pool MUST leave the host unplaced rather than assign a pool. On update, an omitted pool MUST leave the host's pool unchanged and an explicit `null` MUST unplace it. In an INI inventory, a non-empty `pool_id=` places or moves the host, an empty `pool_id=` unplaces it, and an absent `pool_id` leaves an existing host's pool unchanged. A host definitions entry declares its host's whole placement: an entry that names no pool, or names a `null` one, leaves a new host unplaced and unplaces an existing one. Every move, unplacing included, MUST pass the host authority's pool-change hooks, and a refusal MUST leave every host in the request, import, or document unchanged.

#### Scenario: Existing schema is migrated

- **WHEN** the resource-pool migration runs against a database whose hosts predate resource pools and no `default` pool exists
- **THEN** it refuses with an actionable schema-drift error, creating no pool and assigning no host

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
