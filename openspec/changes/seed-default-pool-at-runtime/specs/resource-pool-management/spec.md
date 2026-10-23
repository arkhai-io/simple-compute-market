## MODIFIED Requirements

### Requirement: Explicit valid host membership

A provisioning host MAY reference one existing resource pool; a host that references none is unplaced. A host create, update, or inventory import that names a pool MUST be refused unless that pool exists. A create or a new inventory entry that names no pool MUST leave the host unplaced rather than assign a pool. On update, an omitted pool MUST leave the host's pool unchanged and an explicit `null` MUST unplace it. In an INI inventory, a non-empty `pool_id=` places or moves the host, an empty `pool_id=` unplaces it, and an absent `pool_id` leaves an existing host's pool unchanged. Every move, unplacing included, MUST pass the host authority's pool-change hooks, and a refusal MUST leave every host in the request or import unchanged.

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

### Requirement: Non-destructive pool lifecycle

Pool removal MUST disable the pool rather than delete it. No pool, `default` included, is exempt from being disabled.

#### Scenario: Operator deletes a non-default pool

- **WHEN** an operator sends DELETE for an existing pool
- **THEN** the service sets `enabled=false` and the pool remains retrievable by ID

#### Scenario: Operator attempts to disable the default pool

- **WHEN** create, replace, patch, delete, or authoritative import would leave a pool whose ID is `default` disabled
- **THEN** the service applies it as for any other pool, and the pool remains retrievable by ID

### Requirement: Strict lossless YAML validation

Pool YAML validation MUST reject malformed structure, unknown fields, duplicate IDs, unknown providers, and invalid provider configuration; it MUST accumulate all independently detectable structured problems and MUST NOT write data. A document MUST NOT be required to name any particular pool.

#### Scenario: Document contains several independent errors

- **WHEN** validation receives unknown fields, a duplicate ID, an invalid field type, and an unsupported provider in one document
- **THEN** the response is invalid, contains stable path/code/message entries for each detectable problem, has no reconciliation diff, and leaves persistence unchanged

#### Scenario: Valid document is dry-run

- **WHEN** validation receives a valid canonical document
- **THEN** it returns the proposed created, updated, disabled, and unchanged IDs without writing any pool or provider configuration

#### Scenario: A document names no pool called `default`

- **WHEN** validation receives an otherwise valid document with no pool whose ID is `default`
- **THEN** the document is valid

## REMOVED Requirements

### Requirement: The default pool is created with its intended provider

**Reason**: No pool is created implicitly. Migration seeds none, and a fresh site
is seeded from its seed document only when the operator configures no pool
document; `default` is an ordinary pool name.

**Migration**: Sites that hold pools keep them, including a pool named `default`.
A fresh site with a pool document creates its pools from it, as before; one without
is seeded with `vm-default` and `bare-metal-default` from `pool_seed_path`.

## ADDED Requirements

### Requirement: A fresh site is seeded from its seed document

Migration MUST create no Resource Pool. At startup, after the pool document import and before the stored-declaration check, the provisioning service MUST apply the pool document named by `pool_seed_path` when no `pool_definitions_path` is configured and no pool is stored, through the same validation and import as a pool document, in one transaction, recording no digest. It MUST NOT apply it when a pool document is configured or any pool is stored. An empty `pool_seed_path` MUST seed nothing. A seed document that is missing or fails validation MUST fail startup. The packaged default seed document declares `vm-default` (`vm.ansible`) and `bare-metal-default` (`bare_metal.ansible`), each delivering and advertising its own offering mode, backed, with empty provider configuration.

#### Scenario: A fresh site configures no pool document

- **WHEN** the service starts on a database storing no pool, with no `pool_definitions_path` and the default `pool_seed_path`
- **THEN** `vm-default` and `bare-metal-default` are created together with valid declarations, and no digest is recorded

#### Scenario: A fresh site configures a pool document

- **WHEN** the service starts on a database storing no pool, with a valid `pool_definitions_path`
- **THEN** the pools that document declares are created and the seed document is not applied

#### Scenario: A site already holds pools

- **WHEN** the service starts with no `pool_definitions_path` on a database storing any pool
- **THEN** the seed document is not applied and no pool changes

#### Scenario: Seeding is disabled

- **WHEN** the service starts on a database storing no pool, with no `pool_definitions_path` and an empty `pool_seed_path`
- **THEN** no pool is created and startup continues

#### Scenario: The seed document is invalid

- **WHEN** the seed document named by `pool_seed_path` is missing or fails pool document validation
- **THEN** startup fails and no pool is created

#### Scenario: Migration runs on a fresh database

- **WHEN** migration runs against an empty database, with or without a pool document configured
- **THEN** it creates no pool and reads no pool document or seed setting
