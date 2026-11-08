## MODIFIED Requirements

### Requirement: Service-owned migration history
Each stateful service — compute provisioning, the VM storefront, the bare-metal storefront, the API-credit storefront, the API-credit service, and the registry — MUST run and record its own ordered migration chain against its owned database through its packaged migration command, before its application starts, and MUST NOT apply migrations in-process. Its application startup MUST check its database without issuing DDL and MUST refuse a database that is absent, behind its chain, ahead of its chain, or below its supported baseline, naming the migration command and the migration IDs that differ. A database is compatible only when its recorded migrations are exactly its chain's. The migration command MUST receive only its database location and log level and MUST NOT read operational configuration; configuration-driven seeding belongs to runtime initialization, after the startup check passes.

#### Scenario: Database initialization is repeated
- **WHEN** a service's migration command runs against a database whose migrations are already applied
- **THEN** it leaves the schema at the same current version without duplicate schema changes or duplicated rows

#### Scenario: Provisioning deployment has pending migrations
- **WHEN** a provisioning pod is created with an older owned database
- **THEN** its migration init container applies the ordered migration chain before the application container starts

#### Scenario: Provisioning application sees schema drift
- **WHEN** the application process starts against a database missing the latest known migration
- **THEN** startup fails with an actionable schema-drift error and does not mutate the schema

#### Scenario: A service has no separate deployment step for migrations
- **WHEN** a stateful service has no Kubernetes chart, such as the API-credit service, which runs only under Compose
- **THEN** its migration command still runs before its application, as the command followed by the application in one container, and its application refuses a database behind its chain rather than migrating in-process

#### Scenario: Provisioning migration runs under different configuration
- **WHEN** the provisioning migration runs against the same database under two configurations that differ in playbooks, host defaults, or pool and seed documents
- **THEN** both runs produce the same schema and the same rows

#### Scenario: A deployment has pending migrations
- **WHEN** a service is deployed over an older owned database
- **THEN** its migration phase applies the pending migrations before the application process starts

#### Scenario: Application sees a database behind its chain
- **WHEN** the application process starts against a database missing migrations its chain lists
- **THEN** startup fails without mutating the schema, naming the migration command and each pending migration ID

#### Scenario: Application sees a database ahead of its chain
- **WHEN** the application process starts against a database recording a migration its chain does not list, such as after an image rollback over a migrated database, whether or not it also lacks migrations its chain lists
- **THEN** startup fails without mutating the schema, reporting the database ahead and naming each unknown migration ID and each pending one, and recovery is restoring the pre-upgrade backup or rolling forward

#### Scenario: The migration command meets an unknown migration
- **WHEN** a service's migration command runs against a database recording a migration its chain does not list
- **THEN** it applies nothing, changes nothing, and exits unsuccessfully reporting the database ahead with its unknown and pending migration IDs

#### Scenario: Application finds no database
- **WHEN** the application process starts and its database file does not exist or records no migrations
- **THEN** startup fails naming the migration command and creates no database file

#### Scenario: Migration runs under different configuration
- **WHEN** a service's migration command runs against the same database under two configurations that differ in anything but the database location and log level
- **THEN** both runs produce the same schema and the same rows

#### Scenario: The API-credit service starts on a fresh database
- **WHEN** the API-credit service starts against a database its migration command has just created
- **THEN** its startup seeds the `default` resource pool after the startup check passes, and its migrations wrote no pool

### Requirement: A deployment does not wait on a service's dependencies

A chart MUST NOT hold a service back with init containers that wait for or validate its
external dependencies, such as a registry, a chain, or a site, and a service MUST NOT
wait for one, or refuse to start because one is unreachable, in its own startup. The only
init container a chart runs for a service is that service's own migration, which acts on
its own state. The service MUST start while a dependency is unreachable, report the
dependency as degraded in its status while its process health check answers, and recover
without a restart when the dependency answers. A chart whose service starts slowly MUST
give it a startup probe, so that a slow start is not judged by its liveness probe.

#### Scenario: The VM storefront starts before its registry and chain

- **WHEN** the VM storefront starts while its registry, its site, and its chain are
  unreachable
- **THEN** it starts and answers its health check; its status reports the registry check
  unreachable, the storefront degraded, and Alkahest unready with a reachability blocker;
  its publication cycle holds the listings of the site whose projection it has not loaded
  and closes none of them
- **AND** Alkahest becomes ready once the chain answers, and publication reaches the
  registry once it answers, both without a restart

#### Scenario: A storefront starts before its site or service

- **WHEN** the VM storefront starts while its provisioning service is unreachable, or the
  API-credit storefront while its credits service is
- **THEN** it starts and answers its health check, calls to that service fail retryably,
  and they succeed once it answers, without a restart

#### Scenario: A storefront chart renders

- **WHEN** the VM or bare-metal storefront chart is rendered
- **THEN** its Deployment carries exactly one init container, the storefront's migration
  command from the application's image, none that waits on a dependency, and its
  container carries a startup probe

#### Scenario: The registry chart renders

- **WHEN** the registry chart is rendered
- **THEN** its Deployment carries exactly one init container, the registry's migration
  command from the application's image over the registry's data volume

## ADDED Requirements

### Requirement: One migration mechanism serves every stateful service

Every stateful service MUST expose a packaged migration command named for its service command with a `-migrate` suffix, such as `market-storefront-migrate`, that applies its chain, and a `--check` mode that reports the startup check's result and the pending or unknown migration IDs, changes nothing, and exits successfully only for a compatible database. A deployment MUST run the command before the application: a chart as an init container from the application's image with the application's configuration and data volume, and Compose as the command followed by the application in one container. The in-house services MUST apply their chains through one shared migration engine; the registry MUST keep Alembic behind the same command, check result, and refusal message.

#### Scenario: An operator previews an upgrade

- **WHEN** an operator runs a service's migration command with `--check` against a database behind the new image's chain
- **THEN** it lists the pending migration IDs, changes nothing, and exits unsuccessfully

#### Scenario: A storefront under Compose has pending migrations

- **WHEN** a storefront container starts under Compose over a database behind its chain
- **THEN** its migration command applies the pending migrations and the storefront starts only after it succeeds

#### Scenario: The registry refuses a database behind its head

- **WHEN** the registry starts against a database whose Alembic revision is not its script head
- **THEN** startup fails without mutating the schema, naming the registry's migration command and both revisions, in the same form as every other service's refusal

### Requirement: A chain begins at its supported baseline

Each in-house chain MUST begin with baseline migrations, one for each package whose tables its database's startup builds, whose bodies are fixed DDL. The baselines of compute provisioning, the VM storefront, and the bare-metal storefront MUST reproduce the schema the marketplace v0.3.0 release builds at startup; the registry's chain MUST begin with one Alembic baseline revision reproducing its v0.3.0 schema; the baselines of the API-credit storefront and the API-credit service reproduce their schema as of their baseline. For compute provisioning, the VM storefront, the bare-metal storefront, and the registry, the migration command MUST adopt a database that records every migration the v0.3.0 chain recorded by replacing those records with the baseline's in one transaction, without running the baselines; every service MUST refuse any other non-empty database as unsupported. A defect in data or schema a supported database carries MUST be repaired by an ordinary migration after the baseline, so that an adopted database is one the release can serve. The tables and indexes the v0.3.0 release created outside its chain — when a store opened, or after the chain in the storefront's constructor — MUST be created by one such migration, which alone among migrations tolerates objects that already exist, since a v0.3.0 database may or may not hold them.

#### Scenario: A fresh database is migrated

- **WHEN** a service's migration command runs against an empty database
- **THEN** the baselines and every later migration run, producing the baseline schema followed by the later migrations

#### Scenario: A v0.3.0 database is adopted

- **WHEN** the migration command of compute provisioning, the VM storefront, the bare-metal storefront, or the registry runs against a database that recorded every migration of the v0.3.0 chain
- **THEN** it records the baselines as applied without running them, removes the v0.3.0 records, and applies the migrations after the baseline

#### Scenario: A v0.3.0 storefront database never opened a store's tables

- **WHEN** a VM storefront database that recorded every migration of the v0.3.0 chain lacks the deal-servicing tables because no deal was ever delivered, and its migration command runs
- **THEN** it adopts the database, and the migration after the baseline creates the missing tables and indexes, leaving those that exist unchanged

#### Scenario: A database older than v0.3.0 is refused

- **WHEN** the migration command runs against a database missing any migration the v0.3.0 chain recorded
- **THEN** it changes nothing and refuses the database as unsupported, naming the missing migrations and directing the operator to a fresh database

#### Scenario: An API-credit database is refused

- **WHEN** the API-credit storefront's or service's migration command runs against a non-empty database created before its baseline
- **THEN** it refuses the database as unsupported and changes nothing

### Requirement: A migration and its record commit together

The shared migration engine MUST apply each migration and record its ID in one transaction, so that a failed migration leaves the migrations before it recorded and itself neither applied nor recorded.

#### Scenario: A migration fails partway through a chain

- **WHEN** a migration raises after earlier migrations in the same run succeeded
- **THEN** the earlier migrations stay recorded, the failed one leaves no schema change and no record, the command exits unsuccessfully naming it, and application startup reports the database behind with that migration pending

### Requirement: Opening a store changes no schema

A service MUST NOT issue DDL outside its migration chain. Constructing a database client, opening a store, or starting the application MUST leave the database's schema unchanged.

#### Scenario: A storefront opens its stores on a migrated database

- **WHEN** a storefront starts and opens its database client and every store it composes against a database its migration command has migrated
- **THEN** the database's tables, columns, indexes, and triggers are the same before and after

### Requirement: Composition-owned migration ordering

A concrete storefront composition MUST declare its chain from the shared core storefront's migrations, the migrations of each kit it composes that owns tables, and its domain's migrations, in a deterministic declared order, and MUST expose one compatibility result to its application startup.

#### Scenario: Domain migration fails

- **WHEN** shared migrations succeed but a composition-specific migration fails
- **THEN** application startup does not begin and the failure identifies the unsuccessful migration without claiming a compatible chain

## REMOVED Requirements

### Requirement: Legacy storefront domain migration is transactional

**Reason**: Its only input is a storefront database from before the marketplace v0.3.0 release, which the migration baseline refuses as unsupported; the `migrate-storefront-domains` command that implemented it is removed.

**Migration**: An operator holding such a database starts the storefront from a fresh database.
