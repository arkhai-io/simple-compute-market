## MODIFIED Requirements

### Requirement: Service-owned migration history
Each stateful service — compute provisioning, the VM storefront, the bare-metal storefront, the API-credit storefront, the API-credit service, and the registry — MUST run and record its own ordered migration chain against its owned database through its packaged migration command, before its application starts, and MUST NOT apply migrations in-process. Its application startup MUST check its database without issuing DDL and MUST refuse a database that is absent, behind its chain, ahead of its chain, or below its supported baseline, naming the migration command and the migration IDs that differ. A database is compatible only when its recorded migrations are exactly its chain's. A database is ahead only when it records its chain's baselines and a migration its chain does not list, since only an image newer than this one leaves such a ledger. The migration command MUST receive only its database location and log level and MUST NOT read operational configuration; configuration-driven seeding belongs to runtime initialization, after the startup check passes.

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
- **WHEN** the application process starts against a database recording its chain's baselines and a migration its chain does not list, such as after an image rollback over a migrated database, whether or not it also lacks migrations its chain lists
- **THEN** startup fails without mutating the schema, reporting the database ahead and naming each unknown migration ID and each pending one, and recovery is restoring the pre-upgrade backup or rolling forward

#### Scenario: The migration command meets an unknown migration
- **WHEN** a service's migration command runs against a database recording its chain's baselines and a migration its chain does not list
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

### Requirement: A chain begins at its supported baseline

Each in-house chain MUST begin with baseline migrations, one for each package whose tables its database's startup builds, whose bodies are fixed DDL. The baselines of compute provisioning, the VM storefront, the bare-metal storefront, the API-credit storefront, and the API-credit service MUST reproduce the schema the marketplace v0.3.0 release builds at startup; the registry's chain MUST begin with one Alembic baseline revision reproducing its v0.3.0 schema. Every service's migration command MUST adopt a database its floor release ran on — one that records every migration the floor release's chain recorded and none of the chain's baselines, or, for the registry, one at its floor revision — whatever else it records: in one transaction, without running the baselines, it MUST remove every recorded ID its chain does not list and record the baselines, then apply the migrations after the baseline. A database recording some but not all of its floor's migrations and none of the chain's baselines, or, for the registry, at a revision of its history before its floor, MUST be refused as unsupported, naming the floor release and the migrations it lacks, saying the command cannot tell an older database of the service's own from another service's sharing its history, and directing the operator, once the database is confirmed as the service's, to upgrade it through the floor release first, never to a fresh database. A non-empty database the chain did not build that records none of its floor's migrations MUST be refused as unsupported, as not the service's database. A defect in data or schema a supported database carries MUST be repaired by an ordinary migration after the baseline, so that an adopted database is one the release can serve; a table an earlier release created that the release no longer reads MUST be dropped by such a migration where present. The tables and indexes the v0.3.0 release created outside its chain — when a store opened, or after the chain in the storefront's constructor — MUST be created by one such migration, which alone among migrations tolerates objects that already exist, since a v0.3.0 database may or may not hold them.

#### Scenario: A fresh database is migrated

- **WHEN** a service's migration command runs against an empty database
- **THEN** the baselines and every later migration run, producing the baseline schema followed by the later migrations

#### Scenario: A v0.3.0 database is adopted

- **WHEN** a service's migration command runs against a database that recorded every migration of the v0.3.0 chain, or, for the registry, one at its floor revision
- **THEN** it records the baselines as applied without running them, removes the v0.3.0 records, and applies the migrations after the baseline

#### Scenario: A database that reached v0.3.0 by upgrading is adopted

- **WHEN** the VM storefront's migration command runs against a database an earlier release built and v0.3.0 then ran on, which records every migration of the v0.3.0 chain and migrations v0.3.0 no longer lists
- **THEN** it adopts the database, removing the v0.3.0 records and every other record the chain does not list, records the baselines without running them, applies the migrations after the baseline, keeps the database's rows, and leaves the same schema and recorded migrations as a fresh database

#### Scenario: A v0.3.0 storefront database never opened a store's tables

- **WHEN** a VM storefront database that recorded every migration of the v0.3.0 chain lacks the deal-servicing tables because no deal was ever delivered, and its migration command runs
- **THEN** it adopts the database, and the migration after the baseline creates the missing tables and indexes, leaving those that exist unchanged

#### Scenario: A database older than v0.3.0 is refused

- **WHEN** the migration command runs against a database that records some of the migrations the v0.3.0 chain recorded but not all, and none of its chain's baselines
- **THEN** it changes nothing and refuses the database as unsupported, naming marketplace 0.3.0 and the missing migrations, saying it cannot tell an older database of its own from another service's, and directing the operator, once the database is confirmed as the service's, to upgrade it through marketplace 0.3.0 first, then to this release

#### Scenario: Another storefront's database is refused

- **WHEN** the VM storefront's migration command runs against a database the v0.3.0 bare-metal storefront built, which records migrations the two storefronts share and lacks others of the VM storefront's floor
- **THEN** it changes nothing, does not adopt the database, and refuses it as unsupported with the same conditional direction, naming the VM storefront's floor migrations the database lacks

#### Scenario: A ledger recording none of the floor's migrations is refused

- **WHEN** a service's migration command runs against a database that records migrations, none of them its chain's baselines or its floor's
- **THEN** it changes nothing and refuses the database as unsupported, saying the command did not build it, and directs the operator neither to a fresh database nor to an upgrade

#### Scenario: A v0.3.0 API-credit database is adopted

- **WHEN** the API-credit storefront's or service's migration command runs against a database the v0.3.0 release's API-credit storefront or service built
- **THEN** it records the baselines as applied without running them, removes the v0.3.0 records, and applies the migrations after the baseline, keeping the database's rows

#### Scenario: The API-credit pair upgrades in order

- **WHEN** a Compose deployment holding a v0.3.0 API-credit storefront database and service database is upgraded to this release
- **THEN** the service's migration command runs first, the storefront's runs only once the service has migrated and is healthy, and a failed service migration leaves the storefront's database unchanged and the storefront not started

#### Scenario: An API-credit database is refused

- **WHEN** the API-credit storefront's or service's migration command runs against a database that records some of the migrations its v0.3.0 floor recorded but not all, and none of its chain's baselines
- **THEN** it refuses the database as unsupported, changes nothing, and directs the operator, once the database is confirmed as the service's, to upgrade it through marketplace 0.3.0 first

#### Scenario: A database the chain did not build is refused

- **WHEN** a service's migration command runs against a database holding tables but recording no migrations
- **THEN** it changes nothing and refuses the database as unsupported, saying the command did not build it, and directs the operator neither to a fresh database nor to an upgrade

#### Scenario: A table an earlier release created is dropped

- **WHEN** a bare-metal storefront database an earlier release built and v0.3.0 then ran on holds `bare_metal_hosted_lifecycle`, and its migration command runs
- **THEN** it adopts the database, and a migration after the baseline drops the table and its rows

## ADDED Requirements

### Requirement: Every migration chain declares its floor

Every in-house migration chain MUST declare a floor: the release it is supported from, by name, and the migration IDs that release's chain recorded. Chains MAY declare different floors. A chain with no earlier history MUST declare the floor `0.0.0`, recording no migration, and adopts no database. The shared migration engine MUST refuse to construct a chain that declares no floor. Each refusal of a database older than the floor MUST name the floor release, the registry's included. The migration command's `--check` mode MUST list, for a database awaiting adoption, the baselines it would record, the floor release whose records it replaces, by name, every recorded migration adoption would remove beyond the floor's, and the pending migrations.

#### Scenario: A chain without a floor cannot be built

- **WHEN** a service's composition declares its migration chain without a floor
- **THEN** constructing the chain fails, so the service's migration command and its startup check cannot run

#### Scenario: A chain whose floor is 0.0.0 meets a database it did not build

- **WHEN** a chain whose floor is `0.0.0` checks a non-empty database recording none of its baselines
- **THEN** it reports the database unsupported, as not built by its migrations, and adopts nothing

#### Scenario: An operator previews adopting an upgraded database

- **WHEN** an operator runs the VM storefront's migration command with `--check` against a database an earlier release built and v0.3.0 then ran on
- **THEN** it lists the baselines to be adopted, names marketplace 0.3.0 as the floor release whose records adoption replaces, lists each recorded migration adoption would remove beyond the floor's, and the pending migrations, changes nothing, and exits unsuccessfully
