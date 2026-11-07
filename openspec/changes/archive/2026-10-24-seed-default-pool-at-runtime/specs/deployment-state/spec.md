## MODIFIED Requirements

### Requirement: Service-owned migration history
Each stateful service MUST run and record its own ordered migration chain against its owned database; a deployed provisioning service MUST apply pending migrations before application startup and MUST reject schema drift from its normal startup path instead of applying migrations in-process. The provisioning migration entrypoint MUST receive only its database and MUST NOT read operational configuration; configuration-driven seeding belongs to runtime initialization.

#### Scenario: Database initialization is repeated
- **WHEN** a service initializes a database whose migrations are already applied
- **THEN** initialization leaves the schema at the same current version without duplicate schema changes

#### Scenario: Provisioning deployment has pending migrations
- **WHEN** a provisioning pod is created with an older owned database
- **THEN** its migration init container applies the ordered migration chain before the application container starts

#### Scenario: Provisioning application sees schema drift
- **WHEN** the application process starts against a database missing the latest known migration
- **THEN** startup fails with an actionable schema-drift error and does not mutate the schema

#### Scenario: A service has no separate deployment step for migrations
- **WHEN** a stateful service has no Kubernetes init container or standalone migration CLI to apply migrations ahead of the application process (for example, the API-credit service, which has no Helm chart)
- **THEN** it MAY apply its own ordered migration chain in-process at application startup, before serving requests — this is a valid instantiation of service-owned migration history for a service without the provisioning service's deployment topology, not an exception to it

#### Scenario: Provisioning migration runs under different configuration
- **WHEN** the provisioning migration runs against the same database under two configurations that differ in playbooks, host defaults, or pool and seed documents
- **THEN** both runs produce the same schema and the same rows

## ADDED Requirements

### Requirement: The provisioning chart mounts operator files it gives no meaning
The provisioning chart MUST render each entry of `configFiles` verbatim into its ConfigMap and mount it read-only in the application container at `/app/config/<name>`, beside the rendered profile. The chart MUST NOT derive a setting from an operator file: a setting under `config` names it by that path. The values schema MUST refuse a name that is not a single file name, a name the chart mounts itself, and `config.yml` or `config-*.yml` and their `.yaml` forms, which the service would load as configuration profiles. A file's content and name MUST reach the container exactly as given.

#### Scenario: An operator supplies a fresh site's seed
- **WHEN** a release sets `configFiles` with a `pool-seed.yaml` entry and `config.pool_seed_path` to `/app/config/pool-seed.yaml`
- **THEN** the file renders and mounts at that path, and the rendered profile carries the setting as stated

#### Scenario: An operator file takes a reserved name
- **WHEN** a release names an operator file `pool-definitions.yaml`, `config.yml`, `config-production.yml`, `..`, or a path rather than a file name
- **THEN** rendering fails naming the refused name
