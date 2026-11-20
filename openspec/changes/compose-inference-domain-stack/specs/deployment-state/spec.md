## ADDED Requirements

### Requirement: Local inference stack composition

The development stack MUST be able to stand up the inference market beside the
compute and API-credits markets: a registry instance selecting the packaged
`inference` filter specification by path, with its own authority identity, the inference authority,
the gateway in front of a model server, and the inference storefront. Each
signing role MUST have its own development credential supplied through an
explicit, role-scoped reference, and a signing role's credential MUST NOT be
committed in a stack definition. A lane overlay MAY state a public development
control token, labelled as one. The stack MUST run without a GPU and without
fetching a model from an external host.

#### Scenario: The full stack is brought up

- **WHEN** a contributor brings up the root development stack with the
  development identities
- **THEN** three registry instances serve three schema identities, and the
  inference authority, gateway, model server, and storefront report healthy

#### Scenario: The inference stack is brought up alone

- **WHEN** a contributor brings up the inference wrapper
- **THEN** the development chain and the inference services start with no VM or
  API-credits service

#### Scenario: A development credential is missing

- **WHEN** a required inference credential reference is unset
- **THEN** the stack refuses to start naming the missing reference

#### Scenario: A real model server is wanted locally

- **WHEN** a contributor selects the stack's model-server profile
- **THEN** the gateway fronts that model server and no other service's
  configuration changes

## MODIFIED Requirements

### Requirement: Service-owned migration history
Each stateful service — compute provisioning, the VM storefront, the bare-metal storefront, the API-credit storefront, the inference storefront, the API-credit service, the inference service, and the registry — MUST run and record its own ordered migration chain against its owned database through its packaged migration command, before its application starts, and MUST NOT apply migrations in-process. Its application startup MUST check its database without issuing DDL and MUST refuse a database that is absent, behind its chain, ahead of its chain, or below its supported baseline, naming the migration command and the migration IDs that differ. A database is compatible only when its recorded migrations are exactly its chain's. The migration command MUST receive only its database location and log level and MUST NOT read operational configuration; configuration-driven seeding belongs to runtime initialization, after the startup check passes.

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
- **WHEN** a stateful service has no Kubernetes chart, such as the API-credit service or either inference service, which run only under Compose
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

#### Scenario: An inference service is deployed
- **WHEN** the inference storefront or the inference service is deployed
- **THEN** `inference-storefront-migrate` or `inference-service-migrate` runs before its application, which checks its database, issues no DDL, and refuses one its chain did not build
