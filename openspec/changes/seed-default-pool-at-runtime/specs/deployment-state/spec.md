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
